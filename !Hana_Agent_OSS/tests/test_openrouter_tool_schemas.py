from __future__ import annotations

from typing import Any

from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.providers.contracts import ProviderRequest
from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider


def _all_enum_values(value: Any) -> list[Any]:
    """Collect nested enum values from one OpenAI-compatible tool schema."""
    if isinstance(value, list):
        collected: list[Any] = []
        for item in value:
            collected.extend(_all_enum_values(item))
        return collected
    if not isinstance(value, dict):
        return []

    collected = list(value.get("enum", [])) if isinstance(value.get("enum"), list) else []
    for item in value.values():
        collected.extend(_all_enum_values(item))
    return collected


def test_openrouter_sanitizes_empty_nested_enum_values() -> None:
    """Defensive schema cleanup removes blank options before provider submission."""
    schema = {
        "type": "function",
        "function": {
            "parameters": {
                "type": "object",
                "properties": {
                    "shell": {"type": "string", "enum": ["", "cmd", None, "powershell"]},
                    "unused": {"type": "string", "enum": ["", None]},
                },
            },
        },
    }

    sanitized = OpenRouterProvider._sanitize_tool_schema(schema)

    assert sanitized["function"]["parameters"]["properties"]["shell"]["enum"] == ["cmd", "powershell"]
    assert "enum" not in sanitized["function"]["parameters"]["properties"]["unused"]


def test_openrouter_tool_bundle_exposes_mcp_and_local_hands(tmp_path) -> None:
    """The OpenRouter tool bundle exposes MCP + local hands and stays provider-valid."""
    memory = MemoryStore(
        db_path=tmp_path / "memory.sqlite3",
        events_path=tmp_path / "events.jsonl",
    )
    request = ProviderRequest(
        provider="openrouter",
        model="google/gemini-3.1-flash-lite",
        messages=[{"role": "user", "content": "oi"}],
        memory=memory,
    )

    schemas, runners = OpenRouterProvider()._tool_schemas_and_runners(
        request,
        supports_tools=True,
    )

    function_names = [schema["function"]["name"] for schema in schemas]
    assert function_names[:2] == ["mcp_discover", "mcp_invoke"]
    assert "terminal_run" in function_names
    assert "terminal_inspect_dir" in function_names
    assert "terminal_run" in runners
    assert "" not in _all_enum_values(schemas)
