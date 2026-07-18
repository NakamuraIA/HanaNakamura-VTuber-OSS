from __future__ import annotations

from hana_agent_oss.providers.provider_selector.openai_compatible import OpenAICompatibleProvider


def test_tool_arguments_valid_json() -> None:
    assert OpenAICompatibleProvider._tool_arguments('{"query": "oi"}') == {"query": "oi"}
    assert OpenAICompatibleProvider._tool_arguments({"a": 1}) == {"a": 1}
    assert OpenAICompatibleProvider._tool_arguments("") == {}
    assert OpenAICompatibleProvider._tool_arguments(None) == {}


def test_tool_arguments_invalid_json_returns_error_marker() -> None:
    # JSON quebrado NAO pode virar {} silencioso: o loop transforma o marcador
    # em erro estruturado pro modelo em vez de rodar a tool "vazia".
    args = OpenAICompatibleProvider._tool_arguments('{"query": "oi"')
    assert "_args_json_error" in args


def test_tool_run_record_extracts_nested_mcp_query() -> None:
    # mcp_invoke aninha os args reais: {tool, arguments:{query}}. O card de
    # pesquisa deve mostrar a QUERY, nao o nome da tool.
    record = OpenAICompatibleProvider._tool_run_record(
        "mcp_invoke",
        {"tool": "tavily_search", "arguments": {"query": "Kimi Code preço"}},
        {"ok": True},
    )
    assert record["query"] == "Kimi Code preço"


def test_tool_run_record_no_query_for_toolname_only() -> None:
    # Sem query real em lugar nenhum -> query vazia (nome da tool NAO e query).
    record = OpenAICompatibleProvider._tool_run_record(
        "mcp_invoke",
        {"tool": "tavily_search", "arguments": {}},
        {"ok": True},
    )
    assert record["query"] == ""
