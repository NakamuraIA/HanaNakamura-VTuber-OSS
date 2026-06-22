from __future__ import annotations

import asyncio
from typing import Any

from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.mcp.client import McpEnvMissing, McpSdkUnavailable, McpStdioClient
from hana_agent_oss.mcp.config import McpConfigStore
from hana_agent_oss.mcp.contracts import McpCallRequest, McpServerConfig, McpToolInfo


def _unwrap_exc(exc: BaseException) -> str:
    """Flatten an ExceptionGroup to the real leaf causes.

    anyio/MCP wrap transport failures in a TaskGroup, so ``str(exc)`` is only the
    useless "unhandled errors in a TaskGroup (1 sub-exception)" — hiding the actual
    timeout / 401 / closed-stream error. We recurse into ``.exceptions`` and report the
    leaves with their type, so the panel finally says WHY Tavily died.
    """
    sub = getattr(exc, "exceptions", None)
    if sub:
        return "; ".join(_unwrap_exc(inner) for inner in sub)
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class McpManager:
    def __init__(self, config_store: McpConfigStore | None = None, client: McpStdioClient | None = None) -> None:
        self.config_store = config_store or McpConfigStore()
        self.client = client or McpStdioClient()

    def list_servers(self) -> list[dict[str, Any]]:
        return [self._server_payload(server) for server in self.config_store.list_servers()]

    async def discover(self, server_id: str | None = None) -> dict[str, Any]:
        servers = self.config_store.list_servers()
        if server_id:
            servers = [server for server in servers if server.id == server_id]
        results = []
        for server in servers:
            if not server.enabled:
                results.append({**self._server_payload(server), "status": "disabled", "tools": []})
                continue
            result = await self.list_tools(server.id)
            results.append(result)
        return {"servers": results}

    async def list_tools(self, server_id: str) -> dict[str, Any]:
        server = self.config_store.get_server(server_id)
        if not server:
            return {"status": "error", "error": "mcp_server_not_found", "server_id": server_id, "tools": []}
        if not server.enabled:
            return {**self._server_payload(server), "status": "disabled", "error": "mcp_server_disabled", "tools": []}
        try:
            tools = await self.client.list_tools(server)
            return {**self._server_payload(server), "status": "ok", "tools": [self._tool_payload(server, tool) for tool in tools]}
        except McpEnvMissing as exc:
            return {**self._server_payload(server), "status": "error", "error": str(exc), "tools": []}
        except McpSdkUnavailable as exc:
            return {**self._server_payload(server), "status": "error", "error": str(exc), "tools": []}
        except asyncio.TimeoutError:
            return {**self._server_payload(server), "status": "error", "error": "mcp_server_timeout", "tools": []}
        except Exception as exc:  # noqa: BLE001 - surfaced as runtime status.
            return {**self._server_payload(server), "status": "error", "error": f"mcp_server_unavailable: {_unwrap_exc(exc)}", "tools": []}

    async def call_tool(self, request: McpCallRequest) -> ToolResult:
        server = self.config_store.get_server(request.server_id)
        tool_name = request.tool
        if not server:
            return ToolResult(False, "mcp.invoke", error="mcp_server_not_found", output={"server_id": request.server_id})
        if not server.enabled:
            return ToolResult(False, "mcp.invoke", error="mcp_server_disabled", output={"server_id": server.id, "tool": tool_name})
        # Match tolerant to dash/underscore: providers rename tools across versions
        # (Tavily: "tavily-search" -> "tavily_search"), which would otherwise reject a
        # perfectly valid call as mcp_tool_not_allowed. Normalize both sides.
        def _norm(name: str) -> str:
            return str(name or "").strip().lower().replace("-", "_")

        allowed_norm = {_norm(item) for item in server.allowed_tools}
        if _norm(tool_name) not in allowed_norm:
            return ToolResult(False, "mcp.invoke", error="mcp_tool_not_allowed", output={"server_id": server.id, "tool": tool_name})
        try:
            result = await self.client.call_tool(server, tool_name, request.arguments)
        except McpEnvMissing as exc:
            return ToolResult(False, "mcp.invoke", error=str(exc), output={"server_id": server.id, "tool": tool_name})
        except McpSdkUnavailable as exc:
            return ToolResult(False, "mcp.invoke", error=str(exc), output={"server_id": server.id, "tool": tool_name})
        except asyncio.TimeoutError:
            return ToolResult(False, "mcp.invoke", error="mcp_server_timeout", output={"server_id": server.id, "tool": tool_name})
        except Exception as exc:  # noqa: BLE001 - external process/protocol error.
            return ToolResult(False, "mcp.invoke", error=f"mcp_server_unavailable: {_unwrap_exc(exc)}", output={"server_id": server.id, "tool": tool_name})

        return ToolResult(
            ok=result.ok,
            tool="mcp.invoke",
            output={"server_id": server.id, "tool": tool_name, **result.to_dict()},
            error=result.error if not result.ok else None,
        )

    def enable_server(self, server_id: str, enabled: bool) -> dict[str, Any]:
        server = self.config_store.update_server(server_id, enabled=enabled)
        if not server:
            return {"status": "error", "error": "mcp_server_not_found", "server_id": server_id}
        return {"status": "ok", "server": self._server_payload(server)}

    def set_tool_allowed(self, server_id: str, tool_name: str, allowed: bool) -> dict[str, Any]:
        server = self.config_store.set_tool_allowed(server_id, tool_name, allowed)
        if not server:
            return {"status": "error", "error": "mcp_server_not_found", "server_id": server_id}
        return {"status": "ok", "server": self._server_payload(server), "tool": tool_name, "allowed": allowed}

    def upsert_preset(self, preset_id: str) -> dict[str, Any]:
        """Install a known MCP preset into the local runtime config."""
        server = self.config_store.upsert_preset(preset_id)
        if not server:
            return {"status": "error", "error": "mcp_preset_not_found", "preset_id": preset_id}
        return {"status": "ok", "server": self._server_payload(server)}

    @staticmethod
    def _server_payload(server: McpServerConfig) -> dict[str, Any]:
        data = server.to_dict()
        data["env"] = {
            key: (value if "${" in str(value) else "[redacted]" if any(token in key.upper() for token in ("KEY", "TOKEN", "SECRET", "PASSWORD")) else value)
            for key, value in data.get("env", {}).items()
        }
        data["allowed_tool_count"] = len(server.allowed_tools)
        return data

    @staticmethod
    def _tool_payload(server: McpServerConfig, tool: McpToolInfo) -> dict[str, Any]:
        data = tool.to_dict()
        _allowed_norm = {str(item or "").strip().lower().replace("-", "_") for item in server.allowed_tools}
        data["allowed"] = str(tool.name or "").strip().lower().replace("-", "_") in _allowed_norm
        return data
