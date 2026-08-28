"""Cria as tabelas internas do Agent Core no banco principal."""

from __future__ import annotations

import sqlite3

AGENT_CORE_TABLES = (
    "agent_core_messages",
    "agent_core_events",
    "agent_core_tool_runs",
    "agent_core_working_context",
)


def criar_tabelas_agent_core(conexao: sqlite3.Connection) -> None:
    """Cria tabelas com prefixo próprio para não colidir com a memória curta."""

    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_core_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          channel TEXT,
          context_json TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS agent_core_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          type TEXT NOT NULL,
          message TEXT NOT NULL,
          payload_json TEXT,
          source TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS agent_core_tool_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tool TEXT NOT NULL,
          args_json TEXT,
          result_json TEXT,
          ok INTEGER NOT NULL,
          error TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS agent_core_working_context (
          id TEXT PRIMARY KEY,
          state_json TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conexao.commit()

