from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

# Raiz onde `backend` é importável (.../!Hana_Agent_OSS), para que o
# subprocess resolva `-m backend.discord_bot` independente do cwd do backend.
_AGENT_ROOT = Path(__file__).resolve().parents[2]


class DiscordBotManager:
    """Owns the lifecycle of the Discord bot subprocess from inside the backend.

    The bot is a separate process (``python -m backend.discord_bot``) that
    talks back to the local backend over HTTP. This manager just starts it when the
    Connections ``discord`` toggle turns on (and a token exists) and stops it when
    the toggle turns off, so the user never has to open a second terminal.

    Idempotent: ``start`` is a no-op when already running and ``stop`` a no-op when
    already stopped, so callers can safely ``apply`` on every connections change.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @staticmethod
    def token_present() -> bool:
        """True when DISCORD_TOKEN is set; without it the bot cannot log in."""
        return bool(str(os.environ.get("DISCORD_TOKEN") or "").strip())

    def is_running(self) -> bool:
        """Whether the bot subprocess is alive right now."""
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def apply(self, *, enabled: bool) -> dict:
        """Start or stop the bot to match the desired ``discord`` toggle state."""
        return self.start() if enabled else self.stop()

    @staticmethod
    def _kill_orphan_bot_processes() -> None:
        """Kill stray ``python -m backend.discord_bot`` processes from a past run.

        ``CREATE_NEW_PROCESS_GROUP`` (below) deliberately isolates the bot from
        Ctrl+C, but that also means it survives an UNGRACEFUL parent death —
        e.g. ``uvicorn --reload`` hard-restarting the worker on Windows without
        running the FastAPI lifespan shutdown that calls ``stop()``. Each such
        reload leaves one more Discord gateway connection alive, and every one
        of them answers every message: what looks like "Hana respondeu 3x" is
        actually 3+ separate bot processes racing to reply to the same event.
        Run before every spawn so at most one bot is ever connected.
        """
        own_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "ppid", "cmdline"]):
            try:
                cmdline = proc.info["cmdline"] or []
                if proc.info["pid"] == own_pid:
                    continue
                if not any("backend.discord_bot" in part for part in cmdline):
                    continue
                if Path(proc.cwd()).resolve() != _AGENT_ROOT:
                    continue
                proc.terminate()
                logger.warning("Bot do Discord orfao encontrado e encerrado (pid=%s).", proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def start(self) -> dict:
        """Spawn the bot subprocess. No-op when already running."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return {"ok": True, "running": True, "started": False}
            if not self.token_present():
                return {"ok": False, "running": False, "error": "missing_token"}
            self._kill_orphan_bot_processes()
            # CREATE_NEW_PROCESS_GROUP on Windows isolates the child from our Ctrl+C so
            # stopping the backend with Ctrl+C does not race the bot's own shutdown.
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
            try:
                self._proc = subprocess.Popen(
                    [sys.executable, "-m", "backend.discord_bot"],
                    cwd=str(_AGENT_ROOT),
                    creationflags=creationflags,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Falha ao iniciar o bot do Discord.")
                self._proc = None
                return {"ok": False, "running": False, "error": str(exc)}
            logger.info("Bot do Discord iniciado (pid=%s).", self._proc.pid)
            return {"ok": True, "running": True, "started": True}

    def stop(self) -> dict:
        """Terminate the bot subprocess. No-op when not running."""
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None or proc.poll() is not None:
            return {"ok": True, "running": False, "stopped": False}
        try:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=4)
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao parar o bot do Discord.")
        logger.info("Bot do Discord parado.")
        return {"ok": True, "running": False, "stopped": True}

    def status(self) -> dict:
        """Small status payload for the API/frontend."""
        return {"running": self.is_running(), "tokenPresent": self.token_present()}
