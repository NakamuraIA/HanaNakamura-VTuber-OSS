"""Resolve anexos efêmeros do turno de chat."""

from __future__ import annotations

from typing import Any

from backend.memory.store import MemoryStore


def resolve_chat_attachments(
    payload: dict[str, Any],
    *,
    memory: MemoryStore,
    text: str,
    channel: str = "control_center",
) -> list[dict[str, Any]]:
    """Devolve apenas anexos do turno atual, sem persistência ou recuperação antiga."""
    del memory, text, channel
    attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
    return [item for item in attachments if isinstance(item, dict)]
