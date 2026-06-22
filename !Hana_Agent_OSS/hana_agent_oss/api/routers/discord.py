from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from hana_agent_oss.api.routers.config import normalize_connections_config
from hana_agent_oss.api.services.catalog import DEFAULT_CHAT_CONFIG, DEFAULT_CONNECTIONS, DEFAULT_LLM_CONFIG
from hana_agent_oss.api.services.chat import run_text_turn
from hana_agent_oss.api.services.terminal_agent import append_terminal_event
from hana_agent_oss.api.services.unified_history import build_unified_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discord", tags=["Discord"])


def _connections(request: Request) -> dict[str, Any]:
    """Return persisted Discord feature toggles with defaults for older configs."""
    stored = request.app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
    return normalize_connections_config(stored if isinstance(stored, dict) else {})


def _llm_fields(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve the LLM selection for Discord turns from the main Cerebro config."""
    payload = payload or {}
    llm_config = request.app.state.memory.get_setting("llm_config", dict(DEFAULT_LLM_CONFIG))
    chat_config = request.app.state.memory.get_setting("chat_config", dict(DEFAULT_CHAT_CONFIG))
    if not isinstance(llm_config, dict):
        llm_config = dict(DEFAULT_LLM_CONFIG)
    if not isinstance(chat_config, dict):
        chat_config = dict(DEFAULT_CHAT_CONFIG)
    return {
        "provider": payload.get("provider") or chat_config.get("provider") or llm_config.get("llmProvider") or "gemini_api",
        "model": payload.get("model") or chat_config.get("model") or llm_config.get("llmModel") or "structured-planner",
        "temperature": payload.get("temperature", llm_config.get("llmTemperature", 0.7)),
        "native_search_mode": payload.get("native_search_mode") or chat_config.get("nativeSearchMode") or "auto",
        "safety_mode": payload.get("safety_mode") or "safe",
    }


def _discord_user_label(payload: dict[str, Any]) -> str:
    """Build a stable label for prompting and terminal logs."""
    display_name = str(payload.get("displayName") or payload.get("display_name") or payload.get("username") or "").strip()
    user_id = str(payload.get("userId") or payload.get("user_id") or "").strip()
    if display_name and user_id:
        return f"{display_name} ({user_id})"
    return display_name or user_id or "Usuario Discord"


async def _run_discord_turn(request: Request, *, text: str, metadata: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send one Discord-originated text turn through the normal Hana chat pipeline."""
    fields = _llm_fields(request, payload)
    user_label = _discord_user_label(metadata)
    prompt_text = f"Mensagem do Discord de {user_label}: {text}"
    append_terminal_event(
        request.app.state.memory,
        {
            "kind": "user_text",
            "source": "discord",
            "displayText": f"{user_label}: {text}",
            "speechText": "",
            "status": "received",
            "metadata": {"tts": False, **metadata},
        },
    )
    # Use unified history (discord channel) so a long conversation keeps context.
    discord_history = build_unified_history(request.app.state.memory, channel="discord")

    turn_payload: dict[str, Any] = {
        "text": prompt_text,
        "provider": fields["provider"],
        "model": fields["model"],
        "temperature": fields["temperature"],
        "native_search_mode": fields["native_search_mode"],
        "safety_mode": fields["safety_mode"],
        "channel": "discord",
        "history": discord_history,
    }
    # Anexos enviados pelo /hana (arquivo) entram como contexto (visão/doc).
    if payload and isinstance(payload.get("attachments"), list) and payload["attachments"]:
        turn_payload["attachments"] = payload["attachments"]
    result = await run_text_turn(
        turn_payload,
        core=request.app.state.core,
        memory=request.app.state.memory,
    )
    append_terminal_event(
        request.app.state.memory,
        {
            "kind": "assistant_text",
            "source": "hana/discord",
            "displayText": str(result.get("text") or ""),
            "speechText": "",
            "status": result.get("status", {}).get("stage", "done") if isinstance(result.get("status"), dict) else "done",
            "metadata": {"tts": False, **metadata, "meta": result.get("meta", {})},
        },
    )
    return result


@router.get("/config")
async def discord_config(request: Request) -> dict[str, Any]:
    return {"ok": True, "connections": _connections(request)}


@router.get("/bot/status")
async def discord_bot_status(request: Request) -> dict[str, Any]:
    """Report whether the auto-managed Discord bot subprocess is running."""
    manager = getattr(request.app.state, "discord_bot", None)
    if manager is None:
        return {"ok": True, "running": False, "tokenPresent": False}
    return {"ok": True, **manager.status()}


@router.get("/outbox")
async def discord_outbox(request: Request) -> dict[str, Any]:
    """Pending DMs Hana queued for Operador; the Discord bot polls this."""
    from hana_agent_oss.tools.discord_tools import pending_outbox

    owner_id = str(__import__("os").environ.get("HANA_OWNER_ID") or "0").strip()
    return {"ok": True, "ownerId": owner_id, "pending": pending_outbox(request.app.state.memory)}


@router.post("/outbox/delivered")
async def discord_outbox_delivered(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Mark outbox entries as delivered after the bot DMs them."""
    from hana_agent_oss.tools.discord_tools import mark_delivered

    ids = payload.get("ids") if isinstance(payload.get("ids"), list) else []
    updated = mark_delivered(request.app.state.memory, [str(i) for i in ids])
    return {"ok": True, "updated": updated}


@router.post("/message")
async def discord_message(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    if not _connections(request).get("discord"):
        raise HTTPException(status_code=409, detail="Discord integration is disabled.")
    text = str(payload.get("text") or payload.get("message") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Discord message text is required.")
    metadata = {
        "userId": payload.get("userId") or payload.get("user_id"),
        "displayName": payload.get("displayName") or payload.get("display_name") or payload.get("username"),
        "guildId": payload.get("guildId") or payload.get("guild_id"),
        "textChannelId": payload.get("textChannelId") or payload.get("text_channel_id"),
    }
    assistant = await _run_discord_turn(request, text=text, metadata=metadata, payload=payload)
    return {"ok": bool(assistant.get("ok")), "text": assistant.get("text") or "", "assistant": assistant}
