from __future__ import annotations

import json
import os
from pathlib import Path

from hana_agent_oss.core.protocol import AgentEvent, AgentRequest, AgentResponse, ToolCall, ToolResult, WorkingContext
from hana_agent_oss.memory.sqlite import SQLiteStore


from hana_agent_oss.paths import RUNTIME_DB as DEFAULT_RUNTIME_DB


class RuntimeStore(SQLiteStore):
    """Small local SQLite store for the new Hana runtime."""

    def __init__(self, db_path: str | Path | None = None):
        env_db_path = os.environ.get("HANA_RUNTIME_DB")
        selected_path = db_path or env_db_path or DEFAULT_RUNTIME_DB
        super().__init__(selected_path)
        self._init_db()

    def _init_db(self) -> None:
        self._executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              channel TEXT,
              context_json TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT NOT NULL,
              message TEXT NOT NULL,
              payload_json TEXT,
              source TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tool_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tool TEXT NOT NULL,
              args_json TEXT,
              result_json TEXT,
              ok INTEGER NOT NULL,
              error TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS working_context (
              id TEXT PRIMARY KEY,
              state_json TEXT NOT NULL,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    def save_request(self, request: AgentRequest) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO messages (role, content, channel, context_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "user",
                    request.message,
                    request.channel,
                    json.dumps(request.context.to_dict() if request.context else {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def save_response(self, response: AgentResponse) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO messages (role, content, channel, context_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "assistant",
                    response.response,
                    response.channel,
                    json.dumps(response.context.to_dict() if response.context else {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def save_event(self, event: AgentEvent) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO events (type, message, payload_json, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.type,
                    event.message,
                    json.dumps(event.payload, ensure_ascii=False, default=str),
                    event.source,
                    event.created_at,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def save_tool_run(self, call: ToolCall, result: ToolResult) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tool_runs (tool, args_json, result_json, ok, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    call.tool,
                    json.dumps(call.args, ensure_ascii=False, default=str),
                    json.dumps(result.to_dict(), ensure_ascii=False, default=str),
                    1 if result.ok else 0,
                    result.error,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def load_working_context(self) -> WorkingContext:
        with self._connect() as conn:
            row = conn.execute("SELECT state_json FROM working_context WHERE id = ?", ("default",)).fetchone()
            if not row:
                return WorkingContext()
            return WorkingContext.from_dict(json.loads(row["state_json"]))

    def save_working_context(self, context: WorkingContext) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO working_context (id, state_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                  state_json = excluded.state_json,
                  updated_at = CURRENT_TIMESTAMP
                """,
                ("default", json.dumps(context.to_dict(), ensure_ascii=False, default=str)),
            )
            conn.commit()

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "messages": int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]),
                "events": int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
                "tool_runs": int(conn.execute("SELECT COUNT(*) FROM tool_runs").fetchone()[0]),
                "working_context": int(conn.execute("SELECT COUNT(*) FROM working_context").fetchone()[0]),
            }
