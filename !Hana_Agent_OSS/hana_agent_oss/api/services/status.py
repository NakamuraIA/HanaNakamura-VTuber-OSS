from __future__ import annotations

import time
from typing import Any

from hana_agent_oss.api.services.catalog import DEFAULT_CHAT_CONFIG, DEFAULT_CONNECTIONS, DEFAULT_LLM_CONFIG, DEFAULT_VOICE_CONFIG
from hana_agent_oss.memory.store import MemoryStore


def health_payload(*, started_at: float, memory: MemoryStore) -> dict[str, Any]:
    return {
        "ok": True,
        "service": "hana-agent-oss",
        "backend": "agent_oss",
        "uptime_seconds": round(time.time() - started_at, 2),
        "memory_db": str(memory.db_path),
        "legacy_src_runtime": False,
    }


def logs_payload(memory: MemoryStore, *, limit: int = 100) -> dict[str, Any]:
    events = memory.recent_events(limit=limit)
    return {
        "logs": [
            {
                "timestamp": item.get("created_at"),
                "level": "INFO",
                "logger": "hana_agent_oss",
                "message": f"{item.get('role')}: {item.get('content')}",
            }
            for item in events
        ]
    }


def status_payload(memory: MemoryStore | None = None) -> dict[str, Any]:
    """Return dashboard status without mixing Gemini LLM keys with Cloud TTS."""
    llm_config: dict[str, Any] = dict(DEFAULT_LLM_CONFIG)
    chat_config: dict[str, Any] = dict(DEFAULT_CHAT_CONFIG)
    voice_config: dict[str, Any] = dict(DEFAULT_VOICE_CONFIG)
    connections: dict[str, Any] = dict(DEFAULT_CONNECTIONS)
    if memory is not None:
        stored_llm = memory.get_setting("llm_config", dict(DEFAULT_LLM_CONFIG))
        stored_chat = memory.get_setting("chat_config", dict(DEFAULT_CHAT_CONFIG))
        stored_voice = memory.get_setting("voice_config", dict(DEFAULT_VOICE_CONFIG))
        stored_connections = memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
        if isinstance(stored_llm, dict):
            llm_config.update(stored_llm)
        if isinstance(stored_chat, dict):
            chat_config.update(stored_chat)
        if isinstance(stored_voice, dict):
            voice_config.update(stored_voice)
        if isinstance(stored_connections, dict):
            connections.update(stored_connections)

    try:
        import psutil
        import os

        ram = psutil.virtual_memory()
        ram_total = ram.total / (1024**3)
        ram_used = (ram.total - ram.available) / (1024**3)
        cpu = psutil.cpu_percent(interval=None)
        ram_percent = ram.percent
        
        # Check credentials
        has_google = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_CLOUD_PROJECT"))
        has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY"))
        has_cloud_tts = bool(os.environ.get("GOOGLE_CLOUD_TTS_API_KEY"))
        has_groq = bool(os.environ.get("GROQ_API_KEY"))
        has_discord = bool(os.environ.get("DISCORD_TOKEN"))
    except Exception:
        cpu = 0
        ram_percent = 0
        ram_used = 0
        ram_total = 0
        has_google = False
        has_openrouter = False
        has_cloud_tts = False
        has_groq = False
        has_discord = False

    configured_llm_provider = str(chat_config.get("provider") or llm_config.get("llmProvider") or "").strip().lower()
    if configured_llm_provider in {"open_router", "openrouters"}:
        configured_llm_provider = "openrouter"
    if configured_llm_provider in {"groq_cloud", "groqcloud", "glock"}:
        configured_llm_provider = "groq"

    # Smart default: prefer non-Gemini providers if their keys are present.
    if not configured_llm_provider:
        if has_openrouter:
            configured_llm_provider = "openrouter"
        elif has_groq:
            configured_llm_provider = "groq"
        elif has_google:
            configured_llm_provider = "gemini_api"
        else:
            configured_llm_provider = "agent_core"

    default_model_by_provider = {
        "openrouter": "openrouter/auto",
        "groq": "llama-3.3-70b-versatile",
    }
    configured_llm_model = str(chat_config.get("model") or llm_config.get("llmModel") or "").strip() or default_model_by_provider.get(configured_llm_provider, "structured-planner")
    configured_tts_provider = str(voice_config.get("ttsProvider") or llm_config.get("ttsProvider") or "").strip()
    tts_provider = configured_tts_provider or ("google_cloud_tts" if has_cloud_tts else "edge")
    if configured_llm_provider == "openrouter":
        llm_online = has_openrouter
    elif configured_llm_provider == "groq":
        llm_online = has_groq
    else:
        llm_online = has_google

    return {
        "cpu": cpu,
        "ramPercent": ram_percent,
        "ramUsedStr": f"{ram_used:.1f}",
        "ramTotalStr": f"{ram_total:.1f}",
        "llmProvider": configured_llm_provider,
        "llmModel": configured_llm_model,
        "ttsProvider": tts_provider,
        "modules": {
            "llm": llm_online,
            "tts": True,
            "stt": has_groq,
            "visao": llm_online,
            "vtube_studio": False,
            "discord": bool(connections.get("discord")) and has_discord,
            "omni": bool(connections.get("omni")),
        },
    }


def emotions_payload() -> dict[str, Any]:
    return {
        "mood": 0,
        "current_emotion": "neutral",
        "turno": 0,
        "last_thought": "",
        "history": [],
        "updated_at": time.time(),
    }
