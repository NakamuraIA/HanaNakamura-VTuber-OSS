"""Nucleo da memoria principal da Hana no arquivo hana_memory.sqlite3.

    messages         curta   conversa recente, por canal, entra no prompt
    pinned           fixa    regras que SO a Nakamura escreve; a Hana so le
    chat_log         front   historico da tela; NUNCA vai pra LLM
    settings         config  configuracao do app (era .env/.json espalhado)

A "memoria longa" (fatos que a Hana salva sozinha, buscados por RAG) NAO mora
aqui — mora em `memory_items` (`backend/memory/store.py`, `MemoryStore`), que
e quem alimenta o prompt de verdade. Existiu uma tabela `facts` aqui fazendo
esse papel em paralelo (nunca lida pelo RAG de verdade, so pela tela) —
removida em 2026-08-05, sem perda de dado (era copia identica de
`memory_items`). Ver `docs/MEMORIA.md`.

Tres regras que valem pra tudo aqui:

1. CHECK/NOT NULL protegem a estrutura no banco; o codigo tambem valida e
   limita entradas antes de gravar.
2. `messages` e `pinned` entram no prompt. `chat_log` e `settings` NUNCA
   entram. E a divisao mais importante do arquivo.
3. Resultado de ferramenta nao vira memoria: a resposta da Hana ja e o resumo.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal

from backend.memory.sqlite import SQLiteStore
from backend.memory.fixed.rules import FixedMemory
from backend.memory.short_term.history import ShortTermMemory

logger = logging.getLogger(__name__)

Role = Literal["user", "assistant"]

CHANNELS = ("chat", "discord", "terminal", "voice")
PINNED_KINDS = ("regra", "giria", "tarefa", "fato")

SHORT_TERM_LIMIT = 80
MAX_CONTENT_CHARS = 8000
PINNED_MAX_CHARS = 1000

_WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")

SCHEMA = """
-- ============ MEMORIA CURTA: a conversa ============
CREATE TABLE IF NOT EXISTS messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  role       TEXT NOT NULL CHECK (role IN ('user','assistant')),
  author     TEXT NOT NULL,
  content    TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 8000),
  channel    TEXT NOT NULL CHECK (channel IN ('chat','discord','terminal','voice')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel, id DESC);

-- Memoria longa mora em `memory_items` (backend/memory/store.py), nao aqui —
-- ver docstring do modulo. `facts`/`facts_fts` removidas em 2026-08-05.
DROP TABLE IF EXISTS facts;
DROP TABLE IF EXISTS facts_fts;

-- ============ MEMORIA FIXA: so a Nakamura escreve ============
CREATE TABLE IF NOT EXISTS pinned (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  text       TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 1000),
  kind       TEXT NOT NULL DEFAULT 'regra' CHECK (kind IN ('regra','giria','tarefa','fato')),
  position   INTEGER NOT NULL DEFAULT 100,
  enabled    INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pinned_enabled ON pinned(enabled, position, id);

-- ============ HISTORICO DO FRONT: nunca vai pra LLM ============
CREATE TABLE IF NOT EXISTS chat_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role       TEXT NOT NULL,
  author     TEXT NOT NULL DEFAULT '',
  content    TEXT NOT NULL DEFAULT '',
  channel    TEXT NOT NULL DEFAULT 'chat',
  meta_json  TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_log_session ON chat_log(session_id, id);

-- ============ CONFIGURACAO ============
-- CUIDADO: esta tabela e compartilhada com o MemoryStore antigo (store.py), que
-- a cria SEM o DEFAULT. Por isso todo INSERT daqui passa updated_at explicito —
-- so assim funciona nos dois casos (banco criado por um ou pelo outro).
-- Quando o store.py morrer, o DEFAULT passa a valer e nada quebra.
CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ SKILLS: os manuais que a Hana le e escreve ============
-- Eram arquivos .md soltos em backend/skills/. No banco a Hana edita pela tela,
-- as notas dela nao precisam reescrever arquivo, e o backup continua sendo UMA
-- pasta. Script continua sendo arquivo de verdade: terminal.run precisa executar.
CREATE TABLE IF NOT EXISTS skills (
  name       TEXT PRIMARY KEY,
  title      TEXT NOT NULL DEFAULT '',
  content    TEXT NOT NULL,
  notes      TEXT NOT NULL DEFAULT '',   -- dicas que ela mesma anota usando
  enabled    INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  use_count  INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _stamp(created_at: str, author: str, *, agora: bool = False) -> str:
    """Carimbo legivel dentro do texto: [sab 27/07 14:35 - Naka]."""
    try:
        moment = datetime.fromisoformat(created_at)
        when = f"{_WEEKDAYS[moment.weekday()]} {moment:%d/%m %H:%M}"
    except (ValueError, TypeError):
        when = created_at
    return f"[{'AGORA - ' if agora else ''}{when} - {author}]"


def _slug(nome: str) -> str:
    """Nome de skill seguro: minusculo, so letra/numero/underscore."""
    limpo = "".join(c if (c.isalnum() or c in "_-") else "_" for c in (nome or "").strip().lower())
    return limpo.strip("_-")[:60]


def _primeira_linha(texto: str) -> str:
    """Titulo automatico: a primeira linha nao vazia, sem o '#' do Markdown."""
    for linha in texto.splitlines():
        limpa = linha.strip().lstrip("#").strip()
        if limpa:
            return limpa[:120]
    return ""


def _clamp(text: str, limite: int) -> str:
    """Corta em vez de rejeitar: perder o fim e melhor que perder a mensagem."""
    text = (text or "").strip()
    if len(text) > limite:
        return text[: limite - 14] + "\n[...cortado]"
    return text


class HanaMemory(ShortTermMemory, FixedMemory, SQLiteStore):
    """Acesso as tabelas centrais do banco principal da Hana."""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._executescript(SCHEMA)

    # ---------------- memoria curta ---------------------------------- #



    # ---------------- memoria fixa ----------------------------------- #





    # ---------------- historico do front (fora do prompt) ------------ #




    # ---------------- configuracao ----------------------------------- #

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value_json"])
        except (TypeError, ValueError):
            return default

    def set_setting(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value_json, updated_at) VALUES (?,?,datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,"
                " updated_at = excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            conn.commit()

    def all_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
        saida: dict[str, Any] = {}
        for r in rows:
            try:
                saida[r["key"]] = json.loads(r["value_json"])
            except (TypeError, ValueError):
                continue
        return saida

    # ---------------- skills ----------------------------------------- #

    def list_skills(self, *, only_enabled: bool = True) -> list[dict[str, Any]]:
        """So nome/titulo — o conteudo completo sai no read_skill.

        O prompt recebe apenas este indice: injetar o corpo de toda skill faria
        o system prompt crescer sem limite conforme ela aprende coisas novas.
        """
        sql = "SELECT name, title, use_count, enabled FROM skills"
        if only_enabled:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def read_skill(self, name: str) -> dict[str, Any] | None:
        """Skill completa, com as notas dela coladas no fim. Conta o uso."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skills WHERE name = ?", (name.strip().lower(),)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE skills SET use_count = use_count + 1 WHERE name = ?", (row["name"],))
            conn.commit()
        item = dict(row)
        if item["notes"]:
            item["content"] = f"{item['content']}\n\n## Notas da Hana (aprendidas em uso)\n{item['notes']}"
        return item

    def save_skill(self, name: str, content: str, *, title: str = "") -> str:
        """Cria ou substitui uma skill. Preserva as notas — sao aprendizado dela."""
        chave = _slug(name)
        if not chave:
            raise ValueError("nome de skill invalido")
        texto = (content or "").strip()
        if not texto:
            raise ValueError("skill vazia")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skills (name, title, content) VALUES (?,?,?)"
                " ON CONFLICT(name) DO UPDATE SET title = excluded.title,"
                " content = excluded.content, updated_at = datetime('now')",
                (chave, title.strip() or _primeira_linha(texto), texto),
            )
            conn.commit()
        return chave

    def note_skill(self, name: str, note: str) -> bool:
        """Anexa uma dica curta. Vai pra coluna `notes`, nao mexe no manual."""
        chave = _slug(name)
        dica = " ".join((note or "").split())[:300]
        if not (chave and dica):
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT notes FROM skills WHERE name = ?", (chave,)).fetchone()
            if row is None:
                return False
            hoje = datetime.now().strftime("%Y-%m-%d")
            linha = f"- [{hoje}] {dica}"
            if dica in (row["notes"] or ""):
                return True  # ja anotou isso; nao duplica
            novas = f"{row['notes']}\n{linha}".strip()
            conn.execute("UPDATE skills SET notes = ?, updated_at = datetime('now') WHERE name = ?", (novas, chave))
            conn.commit()
        return True

    def delete_skill(self, name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM skills WHERE name = ?", (_slug(name),))
            conn.commit()
            return cur.rowcount > 0

    # ---------------- panorama --------------------------------------- #

    def status(self) -> dict[str, Any]:
        """Contagem por tabela usada pela tela e por ``/api/memoria/status``."""
        with self._connect() as conn:
            def n(sql: str, *a: Any) -> int:
                return int(conn.execute(sql, a).fetchone()[0])

            return {
                "mensagens": n("SELECT COUNT(*) FROM messages"),
                "mensagensPorCanal": {
                    r["channel"]: r["n"]
                    for r in conn.execute(
                        "SELECT channel, COUNT(*) AS n FROM messages GROUP BY channel"
                    ).fetchall()
                },
                "fixas": n("SELECT COUNT(*) FROM pinned WHERE enabled=1"),
                "historicoFront": n("SELECT COUNT(*) FROM chat_log"),
                "configuracoes": n("SELECT COUNT(*) FROM settings"),
                "modelosEmCache": n("SELECT COUNT(*) FROM llm_models"),
            }


# ---------------- montagem do prompt --------------------------------- #

def _fts_query(query: str) -> str:
    """Transforma texto livre em query FTS5 segura.

    Duas armadilhas do FTS5, as duas ja tendo derrubado a busca aqui:

    1. Simbolo e sintaxe. Aspas, asterisco e parenteses do usuario viravam
       operador. Resolvido trocando tudo que nao e letra/numero por espaco.

    2. Palavra reservada. AND, OR, NOT e NEAR em MAIUSCULA sao operadores — e
       sobreviviam ao filtro acima porque sao alfanumericas. Uma pergunta com
       "python AND rust" virava `python OR AND OR rust` e explodia com
       `fts5: syntax error near "AND"`.

    Por isso cada termo sai entre ASPAS: entre aspas o FTS5 trata como texto
    literal, nunca como operador. Vale pra reservada de hoje e pra qualquer
    outra que apareça numa versao futura do SQLite.
    """
    palavras = [p for p in "".join(c if c.isalnum() else " " for c in (query or "")).split() if len(p) >= 3]
    return " OR ".join(f'"{p}"' for p in palavras[:12])


def build_prompt_messages(
    mem: HanaMemory,
    *,
    channel: str,
    pergunta: str,
    system_prompt: str,
    author: str = "Naka",
    limit: int = SHORT_TERM_LIMIT,
) -> list[dict[str, str]]:
    """Monta o que a LLM recebe, na ordem que importa.

        1. system prompt   codigo     quem ela e
        2. pinned          banco      as regras da dona
        3. messages        banco      as ultimas falas DO CANAL
        4. a pergunta      agora      com o carimbo [AGORA]

    A memoria longa (RAG) NAO entra aqui — mora em `memory_items`
    (`backend/memory/store.py`) e e injetada por `unified_history.py`, no
    caminho de verdade do chat. Esta funcao monta so o que HanaMemory sabe.

    O relogio fica no fim, junto da pergunta — nao no system prompt. No topo ele
    mudaria o prefixo a cada turno e mataria o cache do provider.
    """
    blocos: list[str] = [system_prompt.strip()]

    fixas = mem.list_pinned()
    if fixas:
        linhas = "\n".join(f"- ({p['kind']}) {p['text']}" for p in fixas)
        blocos.append(f"[REGRAS FIXAS DA NAKAMURA — valem sempre]\n{linhas}")

    saida: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(blocos)}]

    for row in mem.recent_messages(channel, limit=limit):
        saida.append(
            {"role": row["role"], "content": f"{_stamp(row['created_at'], row['author'])} {row['content']}"}
        )

    agora = _stamp(datetime.now().isoformat(timespec="seconds"), author, agora=True)
    saida.append({"role": "user", "content": f"{agora} {pergunta}"})
    return saida


# ---------------- auto-teste ------------------------------------------ #

def _self_check() -> None:
    """Trava o que quebrou de verdade um dia: canal, ordem, e o que NAO vai pro prompt."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        mem = HanaMemory(str(Path(tmp) / "t.db"))

        # --- curta: isolamento por canal (o bug do vazamento) ---
        mem.add_message(role="user", author="Naka", content="oi pelo chat", channel="chat")
        mem.add_message(role="assistant", author="Hana", content="oi!", channel="chat")
        mem.add_message(role="user", author="Naka", content="segredo do terminal", channel="terminal")

        chat = mem.recent_messages("chat")
        assert len(chat) == 2, f"vazou canal: {chat}"
        assert chat[0]["content"] == "oi pelo chat", "ordem invertida"
        assert mem.recent_messages("chat", limit=1)[0]["content"] == "oi!", "limit tem que pegar a MAIS NOVA"

        for ruim in (
            dict(role="tool", author="x", content="y", channel="chat"),
            dict(role="user", author="x", content="y", channel="Discord"),
        ):
            try:
                mem.add_message(**ruim)  # type: ignore[arg-type]
            except Exception:
                pass
            else:
                raise AssertionError(f"o banco devia recusar: {ruim}")

        assert mem.add_message(role="user", author="Naka", content="x" * 20000, channel="chat") > 0

        # --- fixa: ordem e liga/desliga ---
        mem.add_pinned("responda curto", kind="regra", position=1)
        desligada = mem.add_pinned("regra velha", kind="regra", position=2)
        mem.update_pinned(desligada, enabled=0)
        fixas = mem.list_pinned()
        assert len(fixas) == 1 and fixas[0]["text"] == "responda curto"

        # --- front: entra no banco, NAO entra no prompt ---
        mem.log_chat(session_id="s1", role="assistant", content="SO_NA_TELA " * 5000, meta={"tool": "busca"})
        assert len(mem.chat_history("s1")) == 1, "historico do front tem que aceitar texto gigante"
        assert mem.chat_sessions()[0]["mensagens"] == 1

        # --- config ---
        mem.set_setting("llm", {"provider": "deepseek"})
        assert mem.get_setting("llm")["provider"] == "deepseek"
        mem.set_setting("llm", {"provider": "groq"})
        assert mem.get_setting("llm")["provider"] == "groq", "set_setting tem que sobrescrever"

        # --- o prompt final ---
        prompt = build_prompt_messages(
            mem, channel="chat", pergunta="qual era o repo?", system_prompt="Voce e a Hana."
        )
        assert prompt[0]["role"] == "system" and "responda curto" in prompt[0]["content"]
        assert "regra velha" not in prompt[0]["content"], "fixa desligada nao pode entrar"
        assert prompt[-1]["role"] == "user" and "AGORA" in prompt[-1]["content"]
        assert "segredo do terminal" not in json.dumps(prompt), "conversa de outro canal vazou pro prompt"
        assert "SO_NA_TELA" not in json.dumps(prompt), "historico do front nao pode entrar no prompt"

        st = mem.status()
        assert st["fixas"] == 1 and st["historicoFront"] == 1

    _check_espelho()
    print("ok: memoria (curta + fixa + front + config + modelos + espelho) passou")


def _check_espelho() -> None:
    """O MemoryStore antigo tem que espelhar cada fala na tabela `messages`.

    Enquanto o front nao migra, quem escreve de verdade e o append_event do
    store antigo. Se esse espelho parar, a memoria curta nova fica vazia sem
    ninguem perceber — e o dia da troca vira um buraco no historico.
    """
    import tempfile
    from pathlib import Path

    from backend.memory.store import MemoryStore

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "m.db"
        store = MemoryStore(str(db), events_path=str(Path(tmp) / "e.jsonl"))
        store.append_event("user", "oi", channel="control_center")
        store.append_event("hana", "oi!", channel="control_center")
        store.append_event("user", "e no discord?", channel="discord")
        store.append_event("system", "PTT pressionado", channel="voice")

        mem = HanaMemory(str(db))
        assert mem.status()["mensagens"] == 3, "system/ferramenta nao pode virar memoria curta"
        chat = mem.recent_messages("chat")
        assert [m["role"] for m in chat] == ["user", "assistant"]
        assert chat[0]["author"] == "Nakamura" and chat[1]["author"] == "Hana"
        assert len(mem.recent_messages("discord")) == 1, "canal tem que continuar isolado no espelho"

        # O historico da TELA guarda mais: inclusive o evento de sistema que a
        # memoria curta recusou. E o ponto da tabela separada — a tela mostra
        # tudo, o prompt recebe so conversa.
        st = mem.status()
        assert st["historicoFront"] == 4, f"chat_log devia ter os 4 eventos, tem {st['historicoFront']}"
        assert st["historicoFront"] > st["mensagens"], "a tela tem que ver mais que o prompt"
        sessoes = {s["session_id"] for s in mem.chat_sessions()}
        assert any(s.startswith("chat-") for s in sessoes) and any(s.startswith("discord-") for s in sessoes), (
            f"sessao tem que separar por canal: {sessoes}"
        )


if __name__ == "__main__":
    _self_check()
