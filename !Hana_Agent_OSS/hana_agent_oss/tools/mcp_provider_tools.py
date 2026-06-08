from __future__ import annotations

import re
from typing import Any, Callable

from hana_agent_oss.mcp.client import run_async
from hana_agent_oss.mcp.contracts import McpCallRequest
from hana_agent_oss.mcp.manager import McpManager


_URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+")


def extract_sources_from_mcp(result: Any, *, limit: int = 8) -> list[dict[str, str]]:
    """Best-effort extraction of {title, uri} sources from an arbitrary MCP tool result.

    Tavily and most web MCP tools return either structured items carrying a ``url``
    field or text blobs containing links. We walk both so the chat can render a
    ChatGPT-style sources card regardless of the exact server payload shape.
    """
    sources: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(uri: str, title: str = "") -> None:
        uri = (uri or "").strip().rstrip(".,);]")
        if not uri or uri in seen or not uri.lower().startswith("http"):
            return
        seen.add(uri)
        sources.append({"title": (title or "").strip() or uri, "uri": uri})

    def _walk(node: Any) -> None:
        if len(sources) >= limit:
            return
        if isinstance(node, dict):
            url = node.get("url") or node.get("uri") or node.get("link")
            if isinstance(url, str) and url.lower().startswith("http"):
                _add(url, str(node.get("title") or node.get("name") or node.get("source") or ""))
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, str):
            for match in _URL_RE.findall(node):
                _add(match)

    _walk(result)
    return sources[:limit]


def append_mcp_terminal_event(memory: Any, *, kind: str, status: str, tool_name: str, display_text: str, metadata: dict[str, Any]) -> None:
    """Mirror provider-triggered MCP calls into Terminal Agent without speaking raw tool results."""
    if memory is None:
        return
    try:
        from hana_agent_oss.api.services.terminal_agent import append_terminal_event

        append_terminal_event(
            memory,
            {
                "kind": kind,
                "source": "mcp_provider",
                "displayText": display_text,
                "speechText": "",
                "status": status,
                "toolName": tool_name,
                "metadata": {"tts": False, **metadata},
            },
        )
    except Exception:
        return


def mcp_discover_call(memory: Any, server_id: str = "") -> dict[str, Any]:
    """Discover enabled MCP servers/tools through the same manager used by Agent Core."""
    normalized_server = str(server_id or "").strip()
    append_mcp_terminal_event(
        memory,
        kind="tool_call",
        status="running",
        tool_name="mcp.discover",
        display_text=f"Descobrindo tools MCP{f' em {normalized_server}' if normalized_server else ''}.",
        metadata={"serverId": normalized_server},
    )
    try:
        result = run_async(McpManager().discover(normalized_server or None))
        append_mcp_terminal_event(
            memory,
            kind="tool_result",
            status="success",
            tool_name="mcp.discover",
            display_text="Discovery MCP finalizado.",
            metadata={"result": result},
        )
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001 - external MCP errors are returned to the model.
        append_mcp_terminal_event(
            memory,
            kind="tool_result",
            status="failed",
            tool_name="mcp.discover",
            display_text=f"Falha no discovery MCP: {exc}",
            metadata={"error": str(exc), "serverId": normalized_server},
        )
        return {"ok": False, "error": str(exc), "server_id": normalized_server}


def mcp_invoke_call(
    memory: Any,
    server_id: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    collector: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Invoke one allowlisted MCP tool on one enabled server."""
    normalized_server = str(server_id or "").strip()
    normalized_tool = str(tool or "").strip()
    normalized_args = arguments if isinstance(arguments, dict) else {}
    append_mcp_terminal_event(
        memory,
        kind="tool_call",
        status="running",
        tool_name="mcp.invoke",
        display_text=f"Chamando MCP {normalized_server}.{normalized_tool}.",
        metadata={"serverId": normalized_server, "tool": normalized_tool, "arguments": normalized_args},
    )
    if not normalized_server or not normalized_tool:
        result = {"ok": False, "error": "server_id and tool are required."}
    else:
        tool_result = run_async(
            McpManager().call_tool(
                McpCallRequest(
                    server_id=normalized_server,
                    tool=normalized_tool,
                    arguments=normalized_args,
                )
            )
        )
        result = tool_result.to_dict()
    append_mcp_terminal_event(
        memory,
        kind="tool_result",
        status="success" if result.get("ok") else "failed",
        tool_name="mcp.invoke",
        display_text=str(result.get("error") or f"MCP {normalized_tool} retornou resultado."),
        metadata={"toolResult": result},
    )
    if collector is not None:
        collector.append(
            {
                "tool": normalized_tool,
                "server": normalized_server,
                "query": str(
                    normalized_args.get("query")
                    or normalized_args.get("q")
                    or normalized_args.get("search")
                    or normalized_args.get("url")
                    or ""
                ),
                "ok": bool(result.get("ok")),
                "sources": extract_sources_from_mcp(result),
            }
        )
    return result


def mcp_openai_schemas() -> list[dict[str, Any]]:
    """Return OpenAI/OpenRouter-compatible schemas for Hana MCP provider tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "mcp_discover",
                "description": "Discover configured MCP servers and tools. Disabled servers are not connected.",
                "parameters": {
                    "type": "object",
                    "properties": {"server_id": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_invoke",
                "description": "Invoke one allowlisted tool on one enabled MCP server.",
                "parameters": {
                    "type": "object",
                    "required": ["server_id", "tool"],
                    "properties": {
                        "server_id": {"type": "string"},
                        "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
            },
        },
    ]


def mcp_openai_runners(
    memory: Any,
    collector: list[dict[str, Any]] | None = None,
) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    """Return OpenRouter runners for MCP discovery and invocation.

    When ``collector`` is provided, each invocation appends a run record (tool, query,
    sources) so the chat can render a search/sources card after the turn.
    """
    return {
        "mcp_discover": lambda args: mcp_discover_call(memory, str(args.get("server_id") or "")),
        "mcp_invoke": lambda args: mcp_invoke_call(
            memory,
            str(args.get("server_id") or ""),
            str(args.get("tool") or args.get("tool_name") or ""),
            args.get("arguments") if isinstance(args.get("arguments"), dict) else {},
            collector=collector,
        ),
    }


def mcp_tool_instruction(*, enabled: bool) -> str:
    """Build provider prompt guidance for MCP tool usage."""
    if not enabled:
        return (
            "\n\n[MCP TOOL STATUS]\n"
            "MCP provider tools are not available in this turn. Do not write mcp_discover(...) or mcp_invoke(...) as visible text.\n"
            "If Nakamura asks for Tavily/MCP, explain that a tools-capable model/provider is required.\n"
        )
    return (
        "\n\n[MCP TOOL MANUAL]\n"
        "Use mcp_discover to inspect enabled MCP servers and available tools when needed.\n"
        "Use mcp_invoke only for tools that are enabled and allowlisted by the backend.\n"
        "Use Tavily MCP for current web research, sources, recent facts, news, and external verification.\n"
        "Do not use MCP for normal chat, TTS, STT, image generation, Omni, or local PC automation.\n"
        "Never write mcp_discover(...) or mcp_invoke(...) as visible text; use actual tool calls only.\n"
        "If a tool returns ok=false, quote the returned error exactly and do not invent causes.\n"
    )
