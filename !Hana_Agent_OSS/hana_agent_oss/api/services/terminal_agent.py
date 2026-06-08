from __future__ import annotations

from typing import Any

from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text, tts_payload


TERMINAL_AGENT_CHANNEL = "terminal_agent"
TERMINAL_EVENT_KINDS = {
    "listening",
    "processing",
    "speaking",
    "transcription",
    "response",
    "tool",
    "user_speech",
    "user_text",
    "assistant_thought",
    "tool_call",
    "tool_result",
    "assistant_text",
    "assistant_speech",
    "error",
    "system",
}

TERMINAL_EVENT_KIND_ALIASES = {
    "ouvindo": "listening",
    "escutando": "listening",
    "processando": "processing",
    "falando": "speaking",
    "transcricao": "transcription",
    "transcrição": "transcription",
    "resposta": "response",
    "ferramenta": "tool",
}


def normalize_terminal_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize terminal events while preserving explicit no-TTS decisions."""
    kind = str(payload.get("kind") or "system").strip().lower()
    kind = TERMINAL_EVENT_KIND_ALIASES.get(kind, kind)
    if kind not in TERMINAL_EVENT_KINDS:
        kind = "system"

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    tts_disabled = metadata.get("tts") is False or payload.get("speakable") is False
    display_text = str(payload.get("displayText") or payload.get("display_text") or payload.get("text") or payload.get("content") or "").strip()
    speech_text = str(
        payload.get("speechText")
        or payload.get("speech_text")
        or payload.get("ttsText")
        or payload.get("tts_text")
        or ""
    ).strip()
    if not speech_text and not tts_disabled and kind in {"assistant_text", "assistant_speech", "response", "speaking", "error", "system"}:
        speech_text = sanitize_tts_text(display_text)
    elif speech_text:
        speech_text = sanitize_tts_text(speech_text)

    return {
        "kind": kind,
        "source": str(payload.get("source") or "control_panel"),
        "displayText": display_text,
        "speechText": speech_text,
        "toolName": str(payload.get("toolName") or payload.get("tool_name") or ""),
        "status": str(payload.get("status") or ""),
        "metadata": metadata,
    }


def append_terminal_event(memory: MemoryStore, payload: dict[str, Any]) -> dict[str, Any]:
    event = normalize_terminal_event(payload)
    stored = memory.append_event(
        event["source"],
        event["displayText"],
        channel=TERMINAL_AGENT_CHANNEL,
        metadata={
            **event["metadata"],
            "kind": event["kind"],
            "speechText": event["speechText"],
            "tts_text": event["speechText"],
            "toolName": event["toolName"],
            "status": event["status"],
        },
    )
    return terminal_event_from_store(stored)


def list_terminal_events(memory: MemoryStore, *, limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 200), 500))
    return [terminal_event_from_store(item) for item in memory.recent_events(limit=safe_limit, channel=TERMINAL_AGENT_CHANNEL)]


def terminal_event_from_store(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "id": item.get("id"),
        "kind": metadata.get("kind") or "system",
        "source": item.get("role") or "system",
        "displayText": item.get("content") or "",
        "speechText": metadata.get("speechText") or "",
        "text": item.get("content") or "",
        "toolName": metadata.get("toolName") or "",
        "status": metadata.get("status") or "",
        "createdAt": item.get("created_at") or "",
        "created_at": item.get("created_at") or "",
        "tts": {
            "speakable": bool(metadata.get("speechText")),
            "text": metadata.get("speechText") or "",
        },
        "metadata": {key: value for key, value in metadata.items() if key not in {"kind", "speechText", "tts_text", "toolName", "status"}},
    }


def clear_terminal_events(memory: MemoryStore) -> dict[str, Any]:
    return memory.clear_events(channel=TERMINAL_AGENT_CHANNEL)


def terminal_tts_payload(payload: dict[str, Any]) -> dict[str, str]:
    display_text = str(payload.get("displayText") or payload.get("display_text") or payload.get("text") or "")
    explicit_tts = payload.get("speechText") or payload.get("speech_text") or payload.get("ttsText") or payload.get("tts_text")
    return tts_payload(display_text, str(explicit_tts) if explicit_tts is not None else None)
