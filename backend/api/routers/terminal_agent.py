from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from backend.api.services.terminal_agent import (
    TERMINAL_AGENT_CHANNEL,
    TERMINAL_EVENT_KINDS,
    append_terminal_event,
    clear_terminal_events as clear_terminal_event_log,
    list_terminal_events,
    subscribe_terminal_stream,
    sanitize_tts_text,
    terminal_tts_payload,
    unsubscribe_terminal_stream,
)
from backend.modules.voice.audio_control import request_global_stop
from backend.modules.voice.runtime import VoiceRuntime
from backend.modules.voice.speech_state import set_speaking

router = APIRouter(prefix="/api/terminal-agent", tags=["Terminal Agente"])


def _runtime(request: Request) -> VoiceRuntime | None:
    return getattr(request.app.state, "voice_runtime", None)


@router.get("/events", summary="Ler o log do agente")
async def terminal_events(request: Request, limit: int = 200) -> dict[str, Any]:
    return {
        "channel": TERMINAL_AGENT_CHANNEL,
        "events": list_terminal_events(request.app.state.memory, limit=limit),
        "supportedKinds": sorted(TERMINAL_EVENT_KINDS),
    }


@router.websocket("/stream")
async def terminal_stream(websocket: WebSocket) -> None:
    """Envia apenas o texto parcial; o evento final continua vindo do banco."""
    await websocket.accept()
    subscription = subscribe_terminal_stream()
    queue = subscription[1]
    try:
        while True:
            await websocket.send_json(await queue.get())
    except WebSocketDisconnect:
        return
    except Exception:
        return
    finally:
        unsubscribe_terminal_stream(subscription)


@router.post("/events", summary="Escrever um evento no log")
async def create_terminal_event(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "event": append_terminal_event(request.app.state.memory, payload)}


@router.post("/clear", summary="Limpar o log")
async def clear_terminal_events(request: Request) -> dict[str, Any]:
    return {"status": "ok", **clear_terminal_event_log(request.app.state.memory)}


@router.delete("/events", summary="Apagar eventos do log")
async def delete_terminal_events(request: Request) -> dict[str, Any]:
    return {"status": "ok", **clear_terminal_event_log(request.app.state.memory)}


@router.post("/tts-readable", summary="Deixar um texto legível pra fala")
async def terminal_tts_readable(payload: dict[str, Any]) -> dict[str, Any]:
    return terminal_tts_payload(payload)


@router.post("/sanitize-tts", summary="Tirar markdown e ruído antes de falar")
async def sanitize_terminal_tts(payload: dict[str, Any]) -> dict[str, Any]:
    return {"text": sanitize_tts_text(str(payload.get("text") or ""))}


@router.post("/tts/stop", summary="Parar a fala do agente")
async def stop_terminal_tts(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    reason = str((payload or {}).get("reason") or "terminal_agent_stop")
    request_global_stop(reason)
    runtime = _runtime(request)
    if runtime is not None:
        runtime.interrupt(reason=reason, append_event=False)
    set_speaking(False)
    event = append_terminal_event(
        request.app.state.memory,
        {
            "kind": "speaking",
            "source": "tts",
            "displayText": "TTS stop requested.",
            "speechText": "",
            "status": "stopped",
            "metadata": {"tts": False, "reason": reason},
        },
    )
    return {"status": "ok", "stopped": True, "reason": reason, "event": event}
