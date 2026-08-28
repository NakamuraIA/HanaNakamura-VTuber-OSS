from __future__ import annotations

import json
from pathlib import Path

from backend.bd.agent_core import criar_tabelas_agent_core
from backend.core.protocol import AgentEvent, AgentRequest, AgentResponse, ToolCall, ToolResult, WorkingContext
from backend.memory.sqlite import SQLiteStore
from backend.paths import MEMORY_DB as DEFAULT_MEMORY_DB


class RuntimeStore(SQLiteStore):
    """Persistência interna do Agent Core no banco principal da Hana."""

    def __init__(self, db_path: str | Path | None = None):
        selected_path = db_path or DEFAULT_MEMORY_DB
        super().__init__(selected_path)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            criar_tabelas_agent_core(conn)

    def save_request(self, request: AgentRequest) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_core_messages (role, content, channel, context_json)
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
                INSERT INTO agent_core_messages (role, content, channel, context_json)
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
                INSERT INTO agent_core_events (type, message, payload_json, source, created_at)
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
                INSERT INTO agent_core_tool_runs (tool, args_json, result_json, ok, error)
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
            row = conn.execute(
                "SELECT state_json FROM agent_core_working_context WHERE id = ?",
                ("default",),
            ).fetchone()
            if not row:
                return WorkingContext()
            return WorkingContext.from_dict(json.loads(row["state_json"]))

    def save_working_context(self, context: WorkingContext) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_core_working_context (id, state_json, updated_at)
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
                "messages": int(conn.execute("SELECT COUNT(*) FROM agent_core_messages").fetchone()[0]),
                "events": int(conn.execute("SELECT COUNT(*) FROM agent_core_events").fetchone()[0]),
                "tool_runs": int(conn.execute("SELECT COUNT(*) FROM agent_core_tool_runs").fetchone()[0]),
                "working_context": int(conn.execute("SELECT COUNT(*) FROM agent_core_working_context").fetchone()[0]),
            }
