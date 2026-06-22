"""Lean reminder/alarm scheduler for Hana.

In-process, no external service. A background thread checks persisted reminders
every few seconds; when one is due it (a) speaks a short TTS notice if voice is
enabled and (b) logs a notification event the Control Panel can show. Reminders
survive restarts (stored in the MemoryStore settings).

Time handling uses LOCAL time (what the user means by "16h"). Computation of the
due time is done in Python (reliable), not by the LLM.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from hana_agent_oss.memory.store import MemoryStore

REMINDERS_SETTING = "reminders"
FIRED_LOG_SETTING = "reminders_fired"
MAX_FIRED_LOG = 50
CHECK_INTERVAL_SECONDS = 15
VALID_REPEATS = {"none", "daily"}


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def compute_due(*, at: str = "", in_minutes: Any = None, in_seconds: Any = None, date: str = "") -> tuple[str, str | None]:
    """Compute an absolute local ISO due time from flexible inputs.

    Returns (due_iso, error). Priority: in_seconds > in_minutes > at(+date).
    """
    now = _now()
    # Relative seconds/minutes.
    for value, unit in ((in_seconds, "s"), (in_minutes, "m")):
        if value not in (None, ""):
            try:
                amount = float(value)
            except (TypeError, ValueError):
                return "", f"valor invalido para tempo relativo: {value!r}"
            if amount <= 0:
                return "", "o tempo precisa ser positivo"
            delta = timedelta(seconds=amount) if unit == "s" else timedelta(minutes=amount)
            return _iso(now + delta), None

    # Absolute "HH:MM" (optionally with a date "YYYY-MM-DD").
    clock = str(at or "").strip().lower().replace("h", ":")
    if clock:
        try:
            parts = [p for p in clock.split(":")[:2]]
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 0
        except (ValueError, TypeError, IndexError):
            return "", f"horario invalido: {at!r} (use HH:MM)"
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return "", f"horario fora do intervalo: {at!r}"
        if str(date or "").strip():
            try:
                day = datetime.strptime(date.strip(), "%Y-%m-%d")
            except ValueError:
                return "", f"data invalida: {date!r} (use YYYY-MM-DD)"
            due = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due <= now:  # already passed today -> tomorrow
                due += timedelta(days=1)
        return _iso(due), None

    return "", "informe 'at' (HH:MM), 'in_minutes' ou 'in_seconds'"


class ReminderScheduler:
    """Persisted, in-process reminder runner with a single background thread."""

    def __init__(self, memory: MemoryStore, *, check_interval: int = CHECK_INTERVAL_SECONDS) -> None:
        self.memory = memory
        self.check_interval = max(5, int(check_interval))
        self._speaker: Callable[[str], Awaitable[bool]] | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_speaker(self, speaker: Callable[[str], Awaitable[bool]] | None) -> None:
        self._speaker = speaker

    # --- lifecycle ------------------------------------------------------- #
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hana-reminders", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # --- storage --------------------------------------------------------- #
    def _load(self) -> list[dict[str, Any]]:
        data = self.memory.get_setting(REMINDERS_SETTING, [])
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def _save(self, reminders: list[dict[str, Any]]) -> None:
        self.memory.set_setting(REMINDERS_SETTING, reminders)

    # --- public API ------------------------------------------------------ #
    def create(self, *, text: str, at: str = "", in_minutes: Any = None, in_seconds: Any = None, date: str = "", repeat: str = "none") -> dict[str, Any]:
        clean_text = str(text or "").strip()
        if not clean_text:
            return {"ok": False, "error": "reminder_text_empty"}
        due_iso, error = compute_due(at=at, in_minutes=in_minutes, in_seconds=in_seconds, date=date)
        if error:
            return {"ok": False, "error": error}
        repeat_norm = str(repeat or "none").strip().lower()
        if repeat_norm not in VALID_REPEATS:
            repeat_norm = "none"
        reminder = {
            "id": uuid.uuid4().hex[:12],
            "text": clean_text[:500],
            "due_at": due_iso,
            "repeat": repeat_norm,
            "status": "active",
            "created_at": _iso(_now()),
        }
        with self._lock:
            reminders = self._load()
            reminders.append(reminder)
            self._save(reminders)
        return {"ok": True, "reminder": reminder}

    def list(self, *, include_done: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            reminders = self._load()
        if include_done:
            return reminders
        return [item for item in reminders if item.get("status") == "active"]

    def cancel(self, reminder_id: str) -> dict[str, Any]:
        rid = str(reminder_id or "").strip()
        with self._lock:
            reminders = self._load()
            for item in reminders:
                if item.get("id") == rid and item.get("status") == "active":
                    item["status"] = "cancelled"
                    self._save(reminders)
                    return {"ok": True, "id": rid}
        return {"ok": False, "error": "reminder_not_found", "id": rid}

    # --- background loop ------------------------------------------------- #
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check_due()
            except Exception:
                pass  # never let the loop die
            self._stop.wait(self.check_interval)

    def _check_due(self) -> None:
        now = _now()
        fired: list[dict[str, Any]] = []
        with self._lock:
            reminders = self._load()
            changed = False
            for item in reminders:
                if item.get("status") != "active":
                    continue
                try:
                    due = datetime.fromisoformat(str(item.get("due_at")))
                except ValueError:
                    item["status"] = "error"
                    changed = True
                    continue
                if due <= now:
                    fired.append(dict(item))
                    if str(item.get("repeat")) == "daily":
                        # Fast-forward past missed days (PC off) so it fires once,
                        # not once per missed day.
                        next_due = due + timedelta(days=1)
                        while next_due <= now:
                            next_due += timedelta(days=1)
                        item["due_at"] = _iso(next_due)
                    else:
                        item["status"] = "done"
                    changed = True
            if changed:
                self._save(reminders)
        for item in fired:
            self._fire(item)

    def _fire(self, reminder: dict[str, Any]) -> None:
        text = str(reminder.get("text") or "Lembrete")
        notice = f"Lembrete: {text}"
        self._log_notification(reminder, notice)
        self._speak(notice)

    def _log_notification(self, reminder: dict[str, Any], notice: str) -> None:
        # Panel-visible record + Terminal Agent event.
        try:
            log = self.memory.get_setting(FIRED_LOG_SETTING, [])
            log = log if isinstance(log, list) else []
            log.append({"id": reminder.get("id"), "text": reminder.get("text"), "firedAt": _iso(_now())})
            self.memory.set_setting(FIRED_LOG_SETTING, log[-MAX_FIRED_LOG:])
        except Exception:
            pass
        try:
            from hana_agent_oss.api.services.terminal_agent import append_terminal_event

            append_terminal_event(
                self.memory,
                {
                    "kind": "tool_result",
                    "source": "reminder",
                    "displayText": notice,
                    "speechText": "",
                    "status": "success",
                    "toolName": "reminder.fire",
                    "metadata": {"tts": False, "reminderId": reminder.get("id")},
                },
            )
        except Exception:
            pass

    def _speak(self, text: str) -> None:
        if self._speaker is None:
            return

        def runner() -> None:
            try:
                asyncio.run(self._speaker(text))
            except Exception:
                return

        threading.Thread(target=runner, name="hana-reminder-speech", daemon=True).start()


_SCHEDULER: ReminderScheduler | None = None


def set_reminder_scheduler(scheduler: ReminderScheduler) -> None:
    global _SCHEDULER
    _SCHEDULER = scheduler


def get_reminder_scheduler() -> ReminderScheduler | None:
    return _SCHEDULER
