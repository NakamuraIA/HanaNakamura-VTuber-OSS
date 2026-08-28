from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from backend.api.routers.config import DEFAULT_PORTABILITY_CONFIG, normalize_portability_config
from backend.api.services.chat import handle_chat_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


@router.get("/api/media/image/{filename}", summary="Baixar uma imagem gerada")
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


@router.get("/api/chat/history", summary="Histórico do chat")
async def chat_history(request: Request, limit: int = 50) -> dict[str, Any]:
    events = request.app.state.memory.recent_events(limit=limit, channel="control_center")
    messages = [{"role": item.get("role", "system"), "content": item.get("content", "")} for item in events]
    return {"messages": messages}


@router.post("/api/chat/cancel", summary="Cancelar a resposta em andamento")
async def cancel_chat(request: Request) -> dict[str, Any]:
    tasks: set[asyncio.Task[Any]] = getattr(request.app.state, "active_chat_tasks", set())
    active = [task for task in tasks if not task.done()]
    for task in active:
        task.cancel()
    return {"status": "ok", "cancelled": len(active)}


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    tasks: set[asyncio.Task[Any]] = getattr(websocket.app.state, "active_chat_tasks", None)
    if tasks is None:
        tasks = set()
        websocket.app.state.active_chat_tasks = tasks
    try:
        while True:
            payload = json.loads(await websocket.receive_text())
            task = asyncio.create_task(
                handle_chat_payload(
                    websocket,
                    payload,
                    core=websocket.app.state.core,
                    memory=websocket.app.state.memory,
                )
            )
            tasks.add(task)
            try:
                await task
            except asyncio.CancelledError:
                try:
                    await websocket.send_json({"type": "cancelled"})
                    await websocket.send_json({"type": "done"})
                except (RuntimeError, WebSocketDisconnect):
                    return
            finally:
                tasks.discard(task)
    except WebSocketDisconnect:
        return
