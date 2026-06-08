from __future__ import annotations

import asyncio
from pathlib import Path

from hana_agent_oss.api.services.chat import run_text_turn
from hana_agent_oss.core.protocol import AgentRequest
from hana_agent_oss.core.runtime import HanaAgentCore
from hana_agent_oss.memory.storage import RuntimeStore
from hana_agent_oss.memory.store import MemoryStore


def test_agent_core_registers_builtin_tools_and_reads_file(tmp_path: Path) -> None:
    core = HanaAgentCore(store=RuntimeStore(tmp_path / "runtime.sqlite3"))
    target = tmp_path / "note.txt"
    target.write_text("hana agent core v1", encoding="utf-8")

    response = core.run(AgentRequest(f"file.read {target}", channel="terminal_agent"))

    tool_names = {tool.name for tool in core.tools.list()}
    assert {"file.read", "file.exists", "memory.search", "mcp.discover"} <= tool_names
    assert response.ok is True
    assert response.tool_result is not None
    assert response.tool_result.tool == "file.read"
    assert "hana agent core v1" in response.response
    assert response.working_context is not None
    assert response.working_context.active_file == str(target)


def test_run_text_turn_agent_core_preserves_channel_and_terminal_events(tmp_path: Path) -> None:
    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    core = HanaAgentCore(store=RuntimeStore(tmp_path / "runtime.sqlite3"))
    target = tmp_path / "exists.txt"
    target.write_text("ok", encoding="utf-8")

    result = asyncio.run(
        run_text_turn(
            {
                "text": f"file.exists {target}",
                "provider": "agent_core",
                "model": "structured-planner",
                "channel": "voice",
            },
            core=core,
            memory=memory,
        )
    )

    assert result["ok"] is True
    assert result["media"] == []
    assert str(target) in result["text"]
    assert memory.recent_events(limit=1, channel="voice")[0]["role"] == "hana"
    terminal_events = memory.recent_events(limit=10, channel="terminal_agent")
    assert any(item["role"] == "agent_core" and "Planner selected" in item["content"] for item in terminal_events)
    assert any(item["metadata"].get("toolName") == "file.exists" for item in terminal_events)
