from __future__ import annotations

import argparse
import logging
import os
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def load_runtime_environment() -> None:
    """Load project-level secrets before optional backend-local overrides."""
    from hana_agent_oss.paths import PROJECT_ROOT, AGENT_ROOT
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(AGENT_ROOT / ".env", override=True)
    load_dotenv(override=True)


load_runtime_environment()

from hana_agent_oss.api.routers import (
    agent_jobs_router,
    chat_router,
    config_router,
    discord_router,
    image_router,
    memory_router,
    mcp_router,
    reminders_router,
    status_router,
    system_router,
    terminal_agent_router,
    voice_router,
)
from hana_agent_oss.api.services.catalog import DEFAULT_CONNECTIONS
from hana_agent_oss.api.services.agent_jobs import AgentJobManager, set_agent_job_manager
from hana_agent_oss.core.runtime import HanaAgentCore
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.reminders import ReminderScheduler, set_reminder_scheduler
from hana_agent_oss.modules.voice.runtime import VoiceRuntime, voice_config_with_connections

logger = logging.getLogger(__name__)


def hydrate_voice_runtime_state(app: FastAPI) -> None:
    """Apply persisted voice settings and hotkeys after the app state exists."""
    memory = app.state.memory
    runtime = app.state.voice_runtime
    connections = memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
    if not isinstance(connections, dict):
        connections = dict(DEFAULT_CONNECTIONS)
    runtime.configure_hotkeys(connections)
    config = voice_config_with_connections(memory)
    if bool(config.get("sttEnabled")):
        runtime.start(config)
        return
    runtime.apply_config(config)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan hook used for runtime hydration."""
    hydrate_voice_runtime_state(app)
    app.state.reminders.start()
    app.state.sleep_scheduler.start()
    # Sobe o bot do Discord automaticamente se o toggle já estava ligado (e há token).
    try:
        from hana_agent_oss.api.routers.config import normalize_connections_config
        from hana_agent_oss.api.services.catalog import DEFAULT_CONNECTIONS
        connections = normalize_connections_config(
            app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
        )
        if connections.get("discord"):
            app.state.discord_bot.start()
    except Exception:
        logger.exception("Falha ao iniciar o bot do Discord no startup.")
    yield
    app.state.discord_bot.stop()
    app.state.sleep_scheduler.stop()
    app.state.reminders.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Hana Agent OSS API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.core = HanaAgentCore()
    app.state.memory = MemoryStore()
    app.state.voice_runtime = VoiceRuntime(memory=app.state.memory, core=app.state.core)
    app.state.agent_jobs = AgentJobManager(memory=app.state.memory)
    app.state.agent_jobs.set_speaker(app.state.voice_runtime.speak_text)
    set_agent_job_manager(app.state.agent_jobs)
    app.state.reminders = ReminderScheduler(memory=app.state.memory)
    app.state.reminders.set_speaker(app.state.voice_runtime.speak_text)
    set_reminder_scheduler(app.state.reminders)
    from hana_agent_oss.memory.sleep import SleepScheduler
    app.state.sleep_scheduler = SleepScheduler(memory=app.state.memory)
    from hana_agent_oss.discord_bot.manager import DiscordBotManager
    app.state.discord_bot = DiscordBotManager()
    app.state.started_at = time.time()

    for router in (
        status_router,
        agent_jobs_router,
        chat_router,
        image_router,
        memory_router,
        mcp_router,
        reminders_router,
        config_router,
        discord_router,
        terminal_agent_router,
        voice_router,
        system_router,
    ):
        app.include_router(router)
    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Hana Agent OSS API.")
    parser.add_argument("--host", default=os.environ.get("HANA_BACKEND_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HANA_BACKEND_PORT", "8042")))
    parser.add_argument("--ws-max-size", type=int, default=int(os.environ.get("HANA_WS_MAX_SIZE", str(64 * 1024 * 1024))))
    args = parser.parse_args(argv)
    uvicorn.run(
        "hana_agent_oss.api.server:app",
        host=args.host,
        port=args.port,
        log_level="info",
        ws_max_size=args.ws_max_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
