from __future__ import annotations

from typing import Any

from backend.core.protocol import ToolResult
from backend.core.registry import RegisteredTool, ToolRegistry
from backend.mcp.client import run_async
from backend.mcp.contracts import McpCallRequest
from backend.mcp.manager import McpManager


def register_mcp_tools(registry: ToolRegistry, manager: McpManager | None = None) -> None:
    mcp_manager = manager or McpManager()

    def discover(args: dict[str, Any]) -> ToolResult:
        server_id = str(args.get("server_id") or "").strip() or None
        result = run_async(mcp_manager.discover(server_id))
        return ToolResult(ok=True, tool="mcp.discover", output=result)

    def invoke(args: dict[str, Any]) -> ToolResult:
        server_id = str(args.get("server_id") or "").strip()
        tool = str(args.get("tool") or args.get("tool_name") or "").strip()
        arguments = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}

        if not server_id or not tool:
            return ToolResult(False, "mcp.invoke", error="server_id and tool are required.")

        request = McpCallRequest(
            server_id=server_id,
            tool=tool,
            arguments=arguments,
        )
        return run_async(mcp_manager.call_tool(request))

    registry.register(
        RegisteredTool(
            "mcp.discover",
            "Discover configured MCP servers and tools. Disabled servers are not connected.",
            discover,
            {"type": "object", "properties": {"server_id": {"type": "string"}}},
            {"type": "object"},
            risk="low",
            capability_id="mcp.provider",
        )
    )
    registry.register(
        RegisteredTool(
            "mcp.invoke",
            "Invoke one allowlisted tool on one enabled MCP server.",
            invoke,
            {
                "type": "object",
                "required": ["server_id", "tool"],
                "properties": {
                    "server_id": {"type": "string"},
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                },
            },
            {"type": "object"},
            risk="medium",
            capability_id="mcp.provider",
        )
    )
