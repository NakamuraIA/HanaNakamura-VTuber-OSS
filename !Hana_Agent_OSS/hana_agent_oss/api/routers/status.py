from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from hana_agent_oss.api.services.status import emotions_payload, health_payload, logs_payload, status_payload

router = APIRouter(tags=["Status and Health"])


@router.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    return health_payload(started_at=request.app.state.started_at, memory=request.app.state.memory)


@router.get("/api/logs")
async def logs(request: Request, limit: int = 100) -> dict[str, Any]:
    return logs_payload(request.app.state.memory, limit=limit)


@router.get("/api/status")
async def status(request: Request) -> dict[str, Any]:
    return status_payload(request.app.state.memory)


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(status_payload(websocket.scope["app"].state.memory))
            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        return
    except Exception:
        return


@router.websocket("/ws/emotions")
async def websocket_emotions(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(emotions_payload())
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
    except Exception:
        return
