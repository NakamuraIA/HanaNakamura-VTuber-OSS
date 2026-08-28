from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from backend.mcp.client import run_async
from backend.mcp.config import McpConfigStore
from backend.mcp.contracts import McpCallRequest
from backend.mcp.manager import McpManager


_FALLBACK_MCP_MANAGER = McpManager()


_URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+")

# Cache curto de pesquisa. O loop de ferramentas costuma repetir a MESMA query
# dentro do mesmo assunto (varias rodadas de tool no mesmo turno, ou a Nakamura
# reformulando a pergunta), e cada repeticao gasta credito do Tavily. 5 min cobre
# o "mesmo papo" sem servir resultado velho pra uma pergunta nova.
_SEARCH_CACHE_TTL_SECONDS = 300.0
_SEARCH_CACHE_MAX_ENTRIES = 64
_search_cache: dict[str, tuple[float, dict[str, Any]]] = {}

# SO tool de LEITURA pode ser cacheada. Cachear tool com efeito colateral
# (escrever arquivo, clicar, postar, apagar) devolveria "sucesso" sem ter
# executado nada — bug silencioso e caro de achar.
_CACHEABLE_TOOL_HINTS = ("search", "research", "extract", "crawl", "map")
_NEVER_CACHE_HINTS = ("write", "create", "delete", "remove", "update", "post", "send", "click", "run", "exec")


def _search_cache_key(server: str, tool: str, arguments: dict[str, Any]) -> str:
    """Stable key for one read-only tool call (args order must not matter)."""
    try:
        args = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return ""
    return f"{server}::{tool}::{args}"


def _is_cacheable_tool(tool: str) -> bool:
    """True only for read-only search-style tools."""
    name = str(tool or "").strip().lower()
    if not name or any(bad in name for bad in _NEVER_CACHE_HINTS):
        return False
    return any(hint in name for hint in _CACHEABLE_TOOL_HINTS)


def _search_cache_get(key: str) -> dict[str, Any] | None:
    if not key:
        return None
    entry = _search_cache.get(key)
    if not entry:
        return None
    stored_at, payload = entry
    if (time.monotonic() - stored_at) > _SEARCH_CACHE_TTL_SECONDS:
        _search_cache.pop(key, None)
        return None
    return payload


def _search_cache_put(key: str, payload: dict[str, Any]) -> None:
    if not key or not isinstance(payload, dict) or not payload.get("ok"):
        return  # nunca cachear falha: a proxima tentativa tem que ir na rede
    if len(_search_cache) >= _SEARCH_CACHE_MAX_ENTRIES:
        oldest = min(_search_cache, key=lambda k: _search_cache[k][0])
        _search_cache.pop(oldest, None)
    _search_cache[key] = (time.monotonic(), payload)


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
        from backend.api.services.terminal_agent import append_terminal_event

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


def mcp_discover_call(
    memory: Any,
    server_id: str = "",
    *,
    manager: McpManager | None = None,
) -> dict[str, Any]:
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
        result = run_async((manager or _FALLBACK_MCP_MANAGER).discover(normalized_server or None))
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
    manager: McpManager | None = None,
    collector: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Invoke one allowlisted MCP tool on one enabled server."""
    normalized_server = str(server_id or "").strip()
    normalized_tool = str(tool or "").strip()
    normalized_args = arguments if isinstance(arguments, dict) else {}

    # Server inference: weak models routinely omit server_id or guess it wrong
    # (e.g. "tavily_mcp_research" instead of "tavily"), which used to hard-fail the
    # whole turn. If the given server_id is missing or unknown, find the enabled
    # server whose allowlist contains this tool (dash/underscore tolerant).
    def _norm(name: str) -> str:
        return str(name or "").strip().lower().replace("-", "_")

    if normalized_tool:
        try:
            servers = McpConfigStore().list_servers()
            known_ids = {s.id for s in servers}
            if not normalized_server or normalized_server not in known_ids:
                tool_n = _norm(normalized_tool)
                match = next(
                    (s.id for s in servers if s.enabled and tool_n in {_norm(t) for t in s.allowed_tools}),
                    "",
                )
                if match:
                    normalized_server = match
        except Exception:
            pass
    append_mcp_terminal_event(
        memory,
        kind="tool_call",
        status="running",
        tool_name="mcp.invoke",
        display_text=f"Chamando MCP {normalized_server}.{normalized_tool}.",
        metadata={"serverId": normalized_server, "tool": normalized_tool, "arguments": normalized_args},
    )
    cache_key = ""
    cached = None
    if _is_cacheable_tool(normalized_tool):
        cache_key = _search_cache_key(normalized_server, normalized_tool, normalized_args)
        cached = _search_cache_get(cache_key)

    if not normalized_server or not normalized_tool:
        result = {"ok": False, "error": "server_id and tool are required."}
    elif cached is not None:
        # Mesma pesquisa, menos de 5 min atras: devolve sem gastar credito da API.
        result = cached
    else:
        tool_result = run_async(
            (manager or _FALLBACK_MCP_MANAGER).call_tool(
                McpCallRequest(
                    server_id=normalized_server,
                    tool=normalized_tool,
                    arguments=normalized_args,
                )
            )
        )
        result = tool_result.to_dict()
        _search_cache_put(cache_key, result)
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
                "description": (
                    "Invoke one allowlisted tool on an enabled MCP server. "
                    "Pass 'tool' (e.g. tavily_search) and 'arguments'. 'server_id' is "
                    "optional: if omitted, the backend finds the server that owns the tool."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["tool"],
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
    *,
    manager: McpManager | None = None,
) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    """Return OpenRouter runners for MCP discovery and invocation.

    When ``collector`` is provided, each invocation appends a run record (tool, query,
    sources) so the chat can render a search/sources card after the turn.
    """
    return {
        "mcp_discover": lambda args: mcp_discover_call(
            memory,
            str(args.get("server_id") or ""),
            manager=manager,
        ),
        "mcp_invoke": lambda args: mcp_invoke_call(
            memory,
            str(args.get("server_id") or ""),
            str(args.get("tool") or args.get("tool_name") or ""),
            args.get("arguments") if isinstance(args.get("arguments"), dict) else {},
            manager=manager,
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
        "Do not use MCP for normal chat, TTS, STT, image generation, or local PC automation (use the terminal tools for that).\n"
        "Never write mcp_discover(...) or mcp_invoke(...) as visible text; use actual tool calls only.\n"
        "If a tool returns ok=false, quote the returned error exactly and do not invent causes.\n"
    )
