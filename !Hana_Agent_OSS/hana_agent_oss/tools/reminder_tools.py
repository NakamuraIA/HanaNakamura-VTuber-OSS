"""Reminder tools: let Hana create, list and cancel time-based reminders.

These call the process-wide ReminderScheduler. Like the terminal hands, they are
exposed to tool-capable providers so Hana can set a reminder mid-conversation
(e.g. "me lembra do remedio as 16h").
"""

from __future__ import annotations

from typing import Any

from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.core.registry import RegisteredTool, ToolRegistry
from hana_agent_oss.modules.reminders import get_reminder_scheduler


def _scheduler():
    return get_reminder_scheduler()


def reminder_create(args: dict[str, Any]) -> ToolResult:
    scheduler = _scheduler()
    if scheduler is None:
        return ToolResult(ok=False, tool="reminder.create", output={}, error="scheduler_not_ready")
    result = scheduler.create(
        text=str(args.get("text") or args.get("message") or ""),
        at=str(args.get("at") or ""),
        in_minutes=args.get("in_minutes"),
        in_seconds=args.get("in_seconds"),
        date=str(args.get("date") or ""),
        repeat=str(args.get("repeat") or "none"),
    )
    return ToolResult(ok=bool(result.get("ok")), tool="reminder.create", output=result, error=None if result.get("ok") else str(result.get("error")))


def reminder_list(args: dict[str, Any]) -> ToolResult:
    scheduler = _scheduler()
    if scheduler is None:
        return ToolResult(ok=False, tool="reminder.list", output={}, error="scheduler_not_ready")
    reminders = scheduler.list(include_done=bool(args.get("include_done")))
    return ToolResult(ok=True, tool="reminder.list", output={"reminders": reminders, "count": len(reminders)})


def reminder_cancel(args: dict[str, Any]) -> ToolResult:
    scheduler = _scheduler()
    if scheduler is None:
        return ToolResult(ok=False, tool="reminder.cancel", output={}, error="scheduler_not_ready")
    result = scheduler.cancel(str(args.get("id") or args.get("reminder_id") or ""))
    return ToolResult(ok=bool(result.get("ok")), tool="reminder.cancel", output=result, error=None if result.get("ok") else str(result.get("error")))


def register_reminder_tools(registry: ToolRegistry) -> None:
    registry.register(RegisteredTool(
        "reminder.create",
        "Create a time-based reminder/alarm. Use 'at' (HH:MM), 'in_minutes' or 'in_seconds'; optional repeat='daily'.",
        reminder_create,
        {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string"},
                "at": {"type": "string", "description": "Hora HH:MM (hoje, ou amanha se ja passou)"},
                "in_minutes": {"type": "number"},
                "in_seconds": {"type": "number"},
                "date": {"type": "string", "description": "Data opcional YYYY-MM-DD"},
                "repeat": {"type": "string", "enum": ["none", "daily"]},
            },
        },
        {"type": "object"},
        "low",
        "reminder.module",
    ))
    registry.register(RegisteredTool(
        "reminder.list",
        "List active reminders.",
        reminder_list,
        {"type": "object", "properties": {"include_done": {"type": "boolean"}}},
        {"type": "object"},
        "low",
        "reminder.module",
    ))
    registry.register(RegisteredTool(
        "reminder.cancel",
        "Cancel a reminder by id.",
        reminder_cancel,
        {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
        {"type": "object"},
        "low",
        "reminder.module",
    ))
