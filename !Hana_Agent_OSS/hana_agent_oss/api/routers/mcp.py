from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from hana_agent_oss.mcp.contracts import McpCallRequest

router = APIRouter(prefix="/api/mcp", tags=["MCP Tools"])


def _manager(request: Request):
    return request.app.state.core.mcp


@router.get("/servers")
async def list_mcp_servers(request: Request) -> dict[str, Any]:
    return {"servers": _manager(request).list_servers()}


@router.get("/servers/{server_id}/tools")
async def list_mcp_tools(request: Request, server_id: str) -> dict[str, Any]:
    return await _manager(request).list_tools(server_id)


@router.post("/servers/{server_id}/enable")
async def enable_mcp_server(request: Request, server_id: str) -> dict[str, Any]:
    return _manager(request).enable_server(server_id, True)


@router.post("/servers/{server_id}/disable")
async def disable_mcp_server(request: Request, server_id: str) -> dict[str, Any]:
    return _manager(request).enable_server(server_id, False)


@router.post("/servers/{server_id}/tools/{tool_name}/allow")
async def allow_mcp_tool(request: Request, server_id: str, tool_name: str) -> dict[str, Any]:
    return _manager(request).set_tool_allowed(server_id, tool_name, True)


@router.post("/servers/{server_id}/tools/{tool_name}/block")
async def block_mcp_tool(request: Request, server_id: str, tool_name: str) -> dict[str, Any]:
    return _manager(request).set_tool_allowed(server_id, tool_name, False)


@router.post("/presets/{preset_id}/install")
async def install_mcp_preset(request: Request, preset_id: str) -> dict[str, Any]:
    return _manager(request).upsert_preset(preset_id)


@router.post("/call")
async def call_mcp_tool(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    result = await _manager(request).call_tool(
        McpCallRequest(
            server_id=str(payload.get("server_id") or "").strip(),
            tool=str(payload.get("tool") or payload.get("tool_name") or "").strip(),
            arguments=payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {},
        )
    )
    return result.to_dict()
