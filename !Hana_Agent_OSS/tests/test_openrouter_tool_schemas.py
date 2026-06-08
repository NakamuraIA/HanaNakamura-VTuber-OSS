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


def test_openrouter_agent_cancel_schema_has_no_empty_enum_value() -> None:
    """Google-backed OpenRouter models must receive only valid agent enum choices."""
    schema = OpenRouterProvider._agent_job_cancel_schema()

    agent_schema = schema["function"]["parameters"]["properties"]["agent"]
    assert agent_schema["enum"] == ["omni", "grok"]


def test_openrouter_sanitizes_empty_nested_enum_values() -> None:
    """Defensive schema cleanup removes blank options before provider submission."""
    schema = {
        "type": "function",
        "function": {
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "enum": ["", "omni", None, "grok"]},
                    "unused": {"type": "string", "enum": ["", None]},
                },
            },
        },
    }

    sanitized = OpenRouterProvider._sanitize_tool_schema(schema)

    assert sanitized["function"]["parameters"]["properties"]["agent"]["enum"] == ["omni", "grok"]
    assert "enum" not in sanitized["function"]["parameters"]["properties"]["unused"]


def test_openrouter_omni_tool_bundle_contains_no_blank_enums(tmp_path) -> None:
    """Enabling Omni must keep the complete OpenRouter tool bundle provider-valid."""
    memory = MemoryStore(
        db_path=tmp_path / "memory.sqlite3",
        events_path=tmp_path / "events.jsonl",
    )
    memory.set_setting(
        "connections_config",
        {"omni": True, "omniUrl": "http://127.0.0.1:8060"},
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
    assert function_names[:4] == [
        "mcp_discover",
        "mcp_invoke",
        "omni_supervise",
        "agent_job_cancel",
    ]
    assert "omni_supervise" in runners
    assert "agent_job_cancel" in runners
    assert "" not in _all_enum_values(schemas)
