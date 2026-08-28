"""Gate persistente do backfill v1->v2 de memória (memory.backfill_v2.done).

Cobre a correção do custo O(N): com a marca gravada, criar MemoryStore não
pode regravar memory_items nem reconstruir o FTS. Todos os bancos aqui são
SQLite temporários e descartáveis (tmp_path).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from backend.memory.store import MEMORY_BACKFILL_V2_MARKER_KEY, MemoryStore

_V1_SCHEMA = """
CREATE TABLE memory_items (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'note',
  source TEXT NOT NULL DEFAULT 'manual',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

_LEGADO = (
    ("legado-ativo", "fato antigo preservado da dona", "{}"),
    ("legado-apagado", "rascunho que nunca deve voltar ao FTS", '{"status": "deleted"}'),
)


def _criar_banco_legado(path: Path) -> None:
    """Banco pré-v2: só as colunas antigas, sem settings e sem marca."""
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(_V1_SCHEMA)
        for id_, texto, meta in _LEGADO:
            connection.execute(
                "INSERT INTO memory_items (id, text, metadata_json, created_at, updated_at) "
                "VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
                (id_, texto, meta),
            )
        connection.commit()


def _tem_marca(db_path: Path) -> bool:
    with closing(sqlite3.connect(db_path)) as connection:
        try:
            row = connection.execute(
                "SELECT 1 FROM settings WHERE key = ?", (MEMORY_BACKFILL_V2_MARKER_KEY,)
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    return row is not None


def _fts(db_path: Path) -> set[str]:
    # Shadow table do FTS5: c0 é a coluna UNINDEXED "id", c1 é o texto.
    with closing(sqlite3.connect(db_path)) as connection:
        return {
            str(row[0])
            for row in connection.execute("SELECT c0 FROM memory_fts_content").fetchall()
        }


def _dump_memoria(db_path: Path) -> list[tuple]:
    with closing(sqlite3.connect(db_path)) as connection:
        items = connection.execute(
            "SELECT id, text, kind, source, metadata_json, status, category, pinned "
            "FROM memory_items ORDER BY id"
        ).fetchall()
        fts = connection.execute(
            "SELECT rowid, c0, c1 FROM memory_fts_content ORDER BY rowid"
        ).fetchall()
    return items + [("__fts__", str(fts))]


def test_banco_legado_sem_marca_executa_backfill_e_grava_marca(tmp_path: Path) -> None:
    database = tmp_path / "legado.sqlite3"
    _criar_banco_legado(database)

    MemoryStore(database, events_path=tmp_path / "events.jsonl")

    assert _tem_marca(database)
    with closing(sqlite3.connect(database)) as connection:
        colunas = {str(row[1]) for row in connection.execute("PRAGMA table_info(memory_items)")}
    esperadas = {"status", "category", "importance_score", "embedding_state"}
    assert esperadas <= colunas
    # Ativo indexado; excluído (por metadado legado) fora do FTS.
    assert _fts(database) == {"legado-ativo"}


def test_segunda_criacao_nao_regrava_memory_items_nem_fts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "gate.sqlite3"
    MemoryStore(database, events_path=tmp_path / "events.jsonl")

    escritas = {"n": 0}
    original_connect = sqlite3.connect

    def connect_vigiada(*args: object, **kwargs: object):
        connection = original_connect(*args, **kwargs)  # type: ignore[arg-type]

        def _trace(statement: str) -> None:
            limpo = statement.lstrip().upper()
            if limpo.startswith(("INSERT", "UPDATE", "DELETE")) and (
                "memory_items" in statement or "memory_fts" in statement
            ):
                escritas["n"] += 1

        connection.set_trace_callback(_trace)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect_vigiada)
    try:
        MemoryStore(database, events_path=tmp_path / "events.jsonl")
    finally:
        monkeypatch.undo()

    assert escritas["n"] == 0


def test_memoria_excluida_continua_fora_do_fts(tmp_path: Path) -> None:
    database = tmp_path / "exclusao.sqlite3"
    store = MemoryStore(database, events_path=tmp_path / "events.jsonl")
    criada = store.add_memory("anotação para ser apagada", kind="long_term", source="teste")
    id_criada = str(criada["id"])
    assert store.delete_memory(id_criada, hard=False)

    # Nova instância NÃO roda o backfill (marca presente); o FTS precisa já
    # estar coerente pelos caminhos normais de escrita.
    MemoryStore(database, events_path=tmp_path / "events.jsonl")

    ids = _fts(database)
    assert id_criada not in ids


def test_memoria_ativa_continua_pesquisavel(tmp_path: Path) -> None:
    database = tmp_path / "busca.sqlite3"
    store = MemoryStore(database, events_path=tmp_path / "events.jsonl")
    criada = store.add_memory(
        "receita secreta de bolo da vovó com laranja", kind="long_term", source="teste"
    )

    # Recriação com marca presente não pode perder o índice.
    outra = MemoryStore(database, events_path=tmp_path / "events.jsonl")
    resultados = outra.search("bolo laranja", touch=False)

    assert str(criada["id"]) in {str(r["id"]) for r in resultados}


def test_falha_controlada_no_backfill_nao_grava_marca(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "falha.sqlite3"
    _criar_banco_legado(database)

    def backfill_quebrado(self: MemoryStore, conn: sqlite3.Connection) -> None:
        raise RuntimeError("falha controlada do backfill")

    monkeypatch.setattr(MemoryStore, "_backfill_memory_item_v2", backfill_quebrado)
    with pytest.raises(RuntimeError):
        MemoryStore(database, events_path=tmp_path / "events.jsonl")

    # Sem marca: a próxima inicialização tem que tentar de novo.
    assert not _tem_marca(database)


def test_proxima_tentativa_apos_falha_conclui_normalmente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "falha-e-retry.sqlite3"
    _criar_banco_legado(database)

    def backfill_quebrado(self: MemoryStore, conn: sqlite3.Connection) -> None:
        raise RuntimeError("falha controlada do backfill")

    monkeypatch.setattr(MemoryStore, "_backfill_memory_item_v2", backfill_quebrado)
    with pytest.raises(RuntimeError):
        MemoryStore(database, events_path=tmp_path / "events.jsonl")

    monkeypatch.undo()
    MemoryStore(database, events_path=tmp_path / "events.jsonl")

    assert _tem_marca(database)
    assert _fts(database) == {"legado-ativo"}


def test_banco_novo_continua_funcionando(tmp_path: Path) -> None:
    database = tmp_path / "novo.sqlite3"
    store = MemoryStore(database, events_path=tmp_path / "events.jsonl")

    assert _tem_marca(database)
    criada = store.add_memory("memória em banco novo", kind="long_term", source="teste")
    encontrados = store.search("banco novo", touch=False)
    assert str(criada["id"]) in {str(r["id"]) for r in encontrados}


def test_criacao_com_marca_presente_nao_altera_dados_existentes(tmp_path: Path) -> None:
    database = tmp_path / "intacto.sqlite3"
    store = MemoryStore(database, events_path=tmp_path / "events.jsonl")
    store.add_memory("lembrança um", kind="long_term", source="teste")
    apagada = store.add_memory("lembrança apagável", kind="long_term", source="teste")
    store.delete_memory(str(apagada["id"]), hard=False)
    antes = _dump_memoria(database)

    MemoryStore(database, events_path=tmp_path / "events.jsonl")

    assert _dump_memoria(database) == antes
