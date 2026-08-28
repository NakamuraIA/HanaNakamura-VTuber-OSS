"""Responsabilidade extraída durante a fase 9"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal

from backend.memory.sqlite import SQLiteStore

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




class FixedMemory:
    def list_pinned(self, *, only_enabled: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM pinned"
        if only_enabled:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY position, id"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]


    def add_pinned(self, text: str, *, kind: str = "regra", position: int = 100) -> int:
        clean = _clamp(text, PINNED_MAX_CHARS)
        if not clean:
            raise ValueError("memoria fixa vazia")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO pinned (text, kind, position) VALUES (?,?,?)", (clean, kind, position)
            )
            conn.commit()
            return int(cur.lastrowid)


    def update_pinned(self, pin_id: int, **campos: Any) -> bool:
        permitido = {"text", "kind", "position", "enabled"}
        usar = {k: v for k, v in campos.items() if k in permitido and v is not None}
        if not usar:
            return False
        if "text" in usar:
            usar["text"] = _clamp(str(usar["text"]), PINNED_MAX_CHARS)
        if "enabled" in usar:
            usar["enabled"] = int(bool(usar["enabled"]))
        sets = ", ".join(f"{k} = ?" for k in usar)
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE pinned SET {sets} WHERE id = ?", [*usar.values(), pin_id])
            conn.commit()
            return cur.rowcount > 0


    def delete_pinned(self, pin_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM pinned WHERE id = ?", (pin_id,))
            conn.commit()
            return cur.rowcount > 0

