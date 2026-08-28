"""Fluxo de primeira instalação acionado pelo startup do backend.

Cobre ``garantir_instalacao_inicial``: a decisão de semear os catálogos usa
somente a marca persistente em ``settings``, nunca a existência do arquivo.
Todos os testes operam em SQLite temporário e descartável (``tmp_path``).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from backend.api import server as api_server
from backend.api.server import app as app_padrao
from backend.setup import database as setup_database
from backend.setup.database import (
    SETUP_MARKER_KEY,
    garantir_instalacao_inicial,
    installation_status,
    preview_defaults,
)

_TABELAS = ("llm_models", "tts_models", "stt_models")


def _scalar(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> object:
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute(sql, parameters).fetchone()[0]


def test_banco_novo_sem_marca_recebe_catalogos_e_marca(tmp_path: Path) -> None:
    database = tmp_path / "hana.sqlite3"
    preview = preview_defaults("all")

    result = garantir_instalacao_inicial(database)

    assert result["changed"] is True
    assert installation_status(database)["status"] == "initialized"
    for tabela in _TABELAS:
        esperado = preview["catalogs"][tabela.removesuffix("_models")]["count"]
        assert _scalar(database, f"SELECT COUNT(*) FROM {tabela}") == esperado
    assert _scalar(database, "SELECT COUNT(*) FROM settings WHERE key = ?", (SETUP_MARKER_KEY,)) == 1


def test_segunda_execucao_nao_duplica_nem_reimporta(tmp_path: Path) -> None:
    database = tmp_path / "hana.sqlite3"
    garantir_instalacao_inicial(database)
    contagens = {tabela: _scalar(database, f"SELECT COUNT(*) FROM {tabela}") for tabela in _TABELAS}

    # Diretório de defaults que não existe: se a segunda execução tentasse
    # reimportar qualquer coisa, falharia ao abrir os JSONs.
    result = garantir_instalacao_inicial(database, tmp_path / "defaults-inexistentes")

    assert result["changed"] is False
    for tabela, contagem in contagens.items():
        assert _scalar(database, f"SELECT COUNT(*) FROM {tabela}") == contagem


def test_modelo_removido_pelo_usuario_nao_reaparece(tmp_path: Path) -> None:
    database = tmp_path / "hana.sqlite3"
    garantir_instalacao_inicial(database)
    removido = ("deepseek", "deepseek-v4-flash")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "DELETE FROM llm_models WHERE provider = ? AND model_id = ?", removido
        )
        connection.commit()

    garantir_instalacao_inicial(database)

    assert (
        _scalar(
            database,
            "SELECT COUNT(*) FROM llm_models WHERE provider = ? AND model_id = ?",
            removido,
        )
        == 0
    )


def test_modelo_personalizado_continua_intacto(tmp_path: Path) -> None:
    database = tmp_path / "hana.sqlite3"
    garantir_instalacao_inicial(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "INSERT INTO llm_models (provider, model_id, label) "
            "VALUES ('local', 'meu-modelo', 'Meu modelo personalizado')"
        )
        connection.commit()

    garantir_instalacao_inicial(database)

    assert (
        _scalar(
            database,
            "SELECT label FROM llm_models WHERE provider = 'local' AND model_id = 'meu-modelo'",
        )
        == "Meu modelo personalizado"
    )


def test_falha_na_importacao_nao_grava_marca_e_permite_reinicio_seguro(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "pendente.sqlite3"
    # Simula o banco deixado por um startup antigo interrompido: arquivo existe,
    # tabela de configuração existe, mas a instalação nunca foi concluída.
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT)"
        )
        connection.commit()
    # O ramo automático de banco sem marca usa "inserir se não existir".
    original = setup_database._insert_missing_catalog

    def falha_no_tts(
        connection: sqlite3.Connection,
        catalog: setup_database.CatalogName,
        models: list[dict[str, object]],
    ) -> None:
        if catalog == "tts":
            raise sqlite3.DatabaseError("falha controlada")
        original(connection, catalog, models)

    monkeypatch.setattr(setup_database, "_insert_missing_catalog", falha_no_tts)

    with pytest.raises(sqlite3.DatabaseError):
        garantir_instalacao_inicial(database)

    # Marca ausente e nada gravado pela tentativa interrompida (transação única).
    assert installation_status(database)["status"] == "existing_unmarked"
    assert _scalar(database, "SELECT COUNT(*) FROM llm_models") == 0

    monkeypatch.undo()
    result = garantir_instalacao_inicial(database)
    assert result["changed"] is True
    assert installation_status(database)["status"] == "initialized"


def test_banco_legado_sem_tabela_settings_recebe_catalogos_e_marca(tmp_path: Path) -> None:
    database = tmp_path / "legado.sqlite3"
    preview = preview_defaults("all")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE anotacoes_legadas (valor TEXT NOT NULL)")
        connection.execute("INSERT INTO anotacoes_legadas VALUES ('preservar')")
        connection.commit()

    result = garantir_instalacao_inicial(database)

    assert result["changed"] is True
    assert installation_status(database)["status"] == "initialized"
    # Dado legado preservado, tabela settings criada e marca gravada.
    assert _scalar(database, "SELECT valor FROM anotacoes_legadas") == "preservar"
    for tabela in _TABELAS:
        esperado = preview["catalogs"][tabela.removesuffix("_models")]["count"]
        assert _scalar(database, f"SELECT COUNT(*) FROM {tabela}") == esperado
    assert _scalar(database, "SELECT COUNT(*) FROM settings WHERE key = ?", (SETUP_MARKER_KEY,)) == 1


def test_banco_sem_marca_preserva_publico_editado_e_insere_so_ausentes(tmp_path: Path) -> None:
    database = tmp_path / "sem-marca.sqlite3"
    garantir_instalacao_inicial(database)
    total_seed = {
        tabela: _scalar(database, f"SELECT COUNT(*) FROM {tabela}") for tabela in _TABELAS
    }

    # Simula um banco que perdeu a marca com: modelo público editado pela dona,
    # um modelo público removido e um personalizado extra.
    with closing(sqlite3.connect(database)) as connection:
        vitima = connection.execute(
            "SELECT provider, model_id FROM llm_models "
            "WHERE NOT (provider = 'deepseek' AND model_id = 'deepseek-v4-flash') "
            "ORDER BY provider, model_id LIMIT 1"
        ).fetchone()
        connection.execute(
            "DELETE FROM llm_models WHERE provider = ? AND model_id = ?", vitima
        )
        connection.execute(
            "UPDATE llm_models SET label = 'Editado pela dona', supports_tools = 0 "
            "WHERE provider = 'deepseek' AND model_id = 'deepseek-v4-flash'"
        )
        connection.execute(
            "INSERT INTO llm_models (provider, model_id, label) "
            "VALUES ('local', 'meu-modelo', 'Meu modelo')"
        )
        connection.execute("DELETE FROM settings WHERE key = ?", (SETUP_MARKER_KEY,))
        connection.commit()

    result = garantir_instalacao_inicial(database)

    assert result["changed"] is True
    with closing(sqlite3.connect(database)) as connection:
        editado = connection.execute(
            "SELECT label, supports_tools FROM llm_models "
            "WHERE provider = 'deepseek' AND model_id = 'deepseek-v4-flash'"
        ).fetchone()
        personalizado = connection.execute(
            "SELECT label FROM llm_models WHERE provider = 'local' AND model_id = 'meu-modelo'"
        ).fetchone()
    # Modelo público existente preservado exatamente como estava (sem upsert).
    assert editado == ("Editado pela dona", 0)
    # Modelo público ausente foi inserido; nada duplicou (seed + o personalizado).
    assert (
        _scalar(
            database,
            "SELECT COUNT(*) FROM llm_models WHERE provider = ? AND model_id = ?",
            vitima,
        )
        == 1
    )
    apos_carga = {
        tabela: _scalar(database, f"SELECT COUNT(*) FROM {tabela}") for tabela in _TABELAS
    }
    assert apos_carga["llm_models"] == total_seed["llm_models"] + 1
    # Personalizado extra intacto.
    assert personalizado == ("Meu modelo",)

    # Segunda inicialização: não altera nem duplica nada.
    segunda = garantir_instalacao_inicial(database)
    assert segunda["changed"] is False
    for tabela, contagem in apos_carga.items():
        assert _scalar(database, f"SELECT COUNT(*) FROM {tabela}") == contagem
    with closing(sqlite3.connect(database)) as connection:
        assert (
            connection.execute(
                "SELECT label FROM llm_models "
                "WHERE provider = 'deepseek' AND model_id = 'deepseek-v4-flash'"
            ).fetchone()[0]
            == "Editado pela dona"
        )


def test_startup_direto_estilo_uvicorn_aciona_o_fluxo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "uvicorn.sqlite3"
    preview = preview_defaults("all")
    # create_app lê o caminho do próprio módulo e o MemoryStore lê a env.
    monkeypatch.setattr(api_server, "MEMORY_DB", database)
    monkeypatch.setenv("HANA_MEMORY_DB", str(database))

    created = api_server.create_app()

    try:
        assert created.title == "Hana Agent OSS API"
        assert installation_status(database)["status"] == "initialized"
        assert (
            _scalar(database, "SELECT COUNT(*) FROM llm_models")
            == preview["catalogs"]["llm"]["count"]
        )
        assert _scalar(database, "SELECT COUNT(*) FROM settings WHERE key = ?", (SETUP_MARKER_KEY,)) == 1
    finally:
        # create_app registra singletons globais; devolve os do app padrão para
        # não vazar o banco temporário para os outros testes da suíte.
        api_server.set_agent_job_manager(app_padrao.state.agent_jobs)
        api_server.set_reminder_scheduler(app_padrao.state.reminders)
