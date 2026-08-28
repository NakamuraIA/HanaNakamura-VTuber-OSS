from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from backend.mcp.contracts import McpCallRequest

router = APIRouter(prefix="/api/mcp", tags=["MCP (ferramentas externas)"])


def _manager(request: Request):
    return request.app.state.core.mcp


@router.get("/servers", summary="Listar servidores MCP")
async def list_mcp_servers(request: Request) -> dict[str, Any]:
    return {"servers": _manager(request).list_servers()}


@router.get("/servers/{server_id}/tools", summary="Ferramentas de um servidor")
async def list_mcp_tools(request: Request, server_id: str) -> dict[str, Any]:
    return await _manager(request).list_tools(server_id)


@router.post("/servers/{server_id}/enable", summary="Ligar um servidor")
async def enable_mcp_server(request: Request, server_id: str) -> dict[str, Any]:
    return _manager(request).enable_server(server_id, True)


@router.post("/servers/{server_id}/disable", summary="Desligar um servidor")
async def disable_mcp_server(request: Request, server_id: str) -> dict[str, Any]:
    return _manager(request).enable_server(server_id, False)


@router.post("/servers/{server_id}/tools/{tool_name}/allow", summary="Liberar uma ferramenta pra Hana")
async def allow_mcp_tool(request: Request, server_id: str, tool_name: str) -> dict[str, Any]:
    return _manager(request).set_tool_allowed(server_id, tool_name, True)


@router.post("/servers/{server_id}/tools/{tool_name}/block", summary="Bloquear uma ferramenta")
async def block_mcp_tool(request: Request, server_id: str, tool_name: str) -> dict[str, Any]:
    return _manager(request).set_tool_allowed(server_id, tool_name, False)


@router.post("/presets/{preset_id}/install", summary="Instalar um preset pronto")
async def install_mcp_preset(request: Request, preset_id: str) -> dict[str, Any]:
    return _manager(request).upsert_preset(preset_id)


@router.post("/call", summary="Chamar uma ferramenta MCP na mão")
async def call_mcp_tool(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    result = await _manager(request).call_tool(
        McpCallRequest(
            server_id=str(payload.get("server_id") or "").strip(),
            tool=str(payload.get("tool") or payload.get("tool_name") or "").strip(),
            arguments=payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {},
        )
    )
    return result.to_dict()


@router.post("/servers/{server_id}/update", summary="Editar um servidor")
async def update_mcp_server(request: Request, server_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _manager(request).update_server_config(server_id, payload)
