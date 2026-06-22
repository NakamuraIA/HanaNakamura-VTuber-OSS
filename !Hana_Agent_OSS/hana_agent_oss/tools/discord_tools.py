"""Discord notification outbox: let Hana DM Operador on Discord when SHE decides.

The reminder scheduler runs in the backend process, but only the Discord bot
process holds the discord.py connection that can send a DM. They communicate
one-way (bot -> backend over HTTP), so the backend cannot push a DM directly.

Instead, Hana's ``discord_notify`` tool enqueues a message into a small outbox
(persisted in MemoryStore settings). The Discord bot polls the outbox, DMs the
owner (Operador) mentioning her, and marks the entry delivered. This keeps the
existing architecture intact and survives restarts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

OUTBOX_SETTING = "discord_outbox"
MAX_OUTBOX = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load(memory: Any) -> list[dict[str, Any]]:
    data = memory.get_setting(OUTBOX_SETTING, [])
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def discord_notify(memory: Any, message: str) -> dict[str, Any]:
    """Queue a DM for the Discord bot to deliver to Operador (she gets mentioned).

    Hana calls this when she decides to ping Operador on Discord (e.g. after
    setting an alarm, or to flag something). It does NOT fire on its own.
    """
    text = str(message or "").strip()
    if not text:
        return {"ok": False, "error": "discord_message_empty"}
    entry = {
        "id": uuid.uuid4().hex[:12],
        "message": text[:1800],
        "created_at": _now_iso(),
        "delivered": False,
    }
    outbox = _load(memory)
    outbox.append(entry)
    memory.set_setting(OUTBOX_SETTING, outbox[-MAX_OUTBOX:])
    return {"ok": True, "queued": True, "id": entry["id"]}


def pending_outbox(memory: Any) -> list[dict[str, Any]]:
    """Return undelivered outbox entries for the Discord bot to send."""
    return [item for item in _load(memory) if not item.get("delivered")]


def mark_delivered(memory: Any, ids: list[str]) -> int:
    """Mark the given outbox entries as delivered. Returns how many were updated."""
    wanted = {str(i) for i in (ids or [])}
    if not wanted:
        return 0
    outbox = _load(memory)
    changed = 0
    for item in outbox:
        if str(item.get("id")) in wanted and not item.get("delivered"):
            item["delivered"] = True
            item["delivered_at"] = _now_iso()
            changed += 1
    if changed:
        memory.set_setting(OUTBOX_SETTING, outbox)
    return changed
