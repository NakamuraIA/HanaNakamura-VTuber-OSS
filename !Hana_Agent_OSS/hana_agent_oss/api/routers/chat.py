from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from hana_agent_oss.api.routers.config import DEFAULT_PORTABILITY_CONFIG, normalize_portability_config
from hana_agent_oss.api.services.chat import handle_chat_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat Engine"])


@router.get("/api/media/image/{filename}")
async def get_media_image(filename: str, request: Request):
    """Serve locally generated images securely by resolving path from SQLite portabilidade_config."""
    config = normalize_portability_config(request.app.state.memory.get_setting("portabilidade_config", dict(DEFAULT_PORTABILITY_CONFIG)))
    output_dir = config.get("mediaOutputPath") or os.path.join(os.path.expanduser("~"), "Pictures", "Hana Artista")
    output_dir = os.path.abspath(os.path.expanduser(os.path.expandvars(output_dir)))
    filepath = os.path.abspath(os.path.join(output_dir, filename))

    # Path traversal validation.
    if os.path.commonpath([output_dir, filepath]) != output_dir:
        raise HTTPException(status_code=400, detail="Caminho de arquivo invalido.")

    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Imagem nao encontrada.")

    return FileResponse(filepath)


@router.get("/api/chat/history")
async def chat_history(request: Request, limit: int = 50) -> dict[str, Any]:
    events = request.app.state.memory.recent_events(limit=limit, channel="control_center")
    messages = [{"role": item.get("role", "system"), "content": item.get("content", "")} for item in events]
    return {"messages": messages}


@router.post("/api/chat/cancel")
async def cancel_chat() -> dict[str, Any]:
    return {"status": "ok", "message": "No active provider stream is running."}


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            payload = json.loads(await websocket.receive_text())
            await handle_chat_payload(websocket, payload, core=websocket.app.state.core, memory=websocket.app.state.memory)
    except WebSocketDisconnect:
        return
