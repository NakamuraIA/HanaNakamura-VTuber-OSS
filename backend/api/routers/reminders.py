"""Reminders API: list/create/cancel reminders and read recently fired ones.

The fired log powers the Control Panel toast: the frontend polls it and shows a
notification for entries it has not displayed yet.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from backend.modules.reminders.scheduler import FIRED_LOG_SETTING

router = APIRouter(tags=["Lembretes"])


def _scheduler(request: Request):
    return request.app.state.reminders


@router.get("/api/reminders", summary="Listar lembretes")
async def list_reminders(request: Request) -> dict[str, Any]:
    """Return active reminders for the Control Panel list."""
    return {"ok": True, "reminders": _scheduler(request).list()}


@router.post("/api/reminders", summary="Criar um lembrete")
async def create_reminder(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a reminder from the Control Panel."""
    return _scheduler(request).create(
        text=str(payload.get("text") or ""),
        at=str(payload.get("at") or ""),
        in_minutes=payload.get("in_minutes"),
        in_seconds=payload.get("in_seconds"),
        date=str(payload.get("date") or ""),
        repeat=str(payload.get("repeat") or "none"),
        discord=bool(payload.get("discord")),
    )


@router.post("/api/reminders/{reminder_id}/cancel", summary="Cancelar um lembrete")
async def cancel_reminder(request: Request, reminder_id: str) -> dict[str, Any]:
    """Cancel one reminder by id."""
    return _scheduler(request).cancel(reminder_id)


@router.get("/api/reminders/fired", summary="Lembretes que já dispararam")
async def fired_reminders(request: Request) -> dict[str, Any]:
    """Return the recent fired-reminder log used by the panel toast."""
    log = request.app.state.memory.get_setting(FIRED_LOG_SETTING, [])
    return {"ok": True, "fired": log if isinstance(log, list) else []}
