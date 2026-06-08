from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["System Control"])


@router.post("/api/tts/speak")
async def speak(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "")
    request.app.state.memory.append_event("system", f"TTS requested but voice integration is optional: {text[:120]}", channel="control_center")
    return {"status": "disabled", "message": "TTS is now an optional integration."}


@router.post("/api/system/shutdown")
async def system_shutdown() -> dict[str, Any]:
    return {"status": "ok", "message": "Shutdown acknowledged. Stop the root supervisor to close all local processes."}


@router.get("/api/vts/state")
async def vts_state() -> dict[str, Any]:
    return {
        "enabled": False,
        "connected": False,
        "authenticated": False,
        "status": "optional_disabled",
        "mode": "optional_subagent",
        "host": "localhost",
        "port": 8001,
        "hotkeys": 0,
        "expressions": 0,
        "mouth_parameter": "N/A",
        "tracking_mode": "disabled",
        "last_error": "VTube integration is optional and disabled.",
        "last_expression": "",
        "updated_at": 0,
    }
