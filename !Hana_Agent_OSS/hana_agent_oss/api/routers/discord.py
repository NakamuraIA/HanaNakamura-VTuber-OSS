from __future__ import annotations

import asyncio
import logging
import time
from base64 import b64encode
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from hana_agent_oss.api.routers.config import normalize_connections_config
from hana_agent_oss.api.routers.voice import read_audio_upload
from hana_agent_oss.api.services.catalog import DEFAULT_CHAT_CONFIG, DEFAULT_CONNECTIONS, DEFAULT_LLM_CONFIG, DEFAULT_VOICE_CONFIG
from hana_agent_oss.api.services.chat import run_text_turn
from hana_agent_oss.api.services.terminal_agent import append_terminal_event
from hana_agent_oss.api.services.unified_history import build_unified_history
from hana_agent_oss.modules.voice.stt_whisper import GroqWhisperSTTProvider, STTConfigurationError
from hana_agent_oss.modules.voice.tts_edge import EdgeTTSProvider, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_gemini import DEFAULT_GEMINI_TTS_MODEL, DEFAULT_GEMINI_TTS_VOICE, GeminiTTSProvider
from hana_agent_oss.modules.voice.tts_google_cloud import DEFAULT_GOOGLE_CLOUD_TTS_VOICE, GoogleCloudTTSProvider
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discord", tags=["Discord"])


def _connections(request: Request) -> dict[str, Any]:
    """Return persisted Discord feature toggles with defaults for older configs."""
    stored = request.app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
    return normalize_connections_config(stored if isinstance(stored, dict) else {})


def _voice_config(request: Request) -> dict[str, Any]:
    """Return the Terminal Agent voice config reused by Discord TTS output."""
    stored = request.app.state.memory.get_setting("voice_config", dict(DEFAULT_VOICE_CONFIG))
    config = dict(DEFAULT_VOICE_CONFIG)
    if isinstance(stored, dict):
        config.update(stored)
    return config


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
    # Use unified history (now includes discord channel) so conversation in long voice calls
    # does not lose context between turns. The style hint for "discord" enforces short group-call speech.
    discord_history = build_unified_history(request.app.state.memory, channel="discord")

    result = await run_text_turn(
        {
            "text": prompt_text,
            "provider": fields["provider"],
            "model": fields["model"],
            "temperature": fields["temperature"],
            "native_search_mode": fields["native_search_mode"],
            "safety_mode": fields["safety_mode"],
            "channel": "discord",
            "history": discord_history,
        },
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


async def _synthesize_discord_tts(request: Request, text: str) -> dict[str, Any] | None:
    """Synthesize audio bytes for Discord playback without touching local speakers."""
    clean_text = sanitize_tts_text(text)
    if not clean_text:
        return None
    config = _voice_config(request)
    provider_id = str(config.get("ttsProvider") or "edge").strip().lower()
    if provider_id == "google":
        provider_id = "google_cloud_tts"
    voice = str(config.get("ttsVoice") or "").strip()
    model = str(config.get("ttsModel") or DEFAULT_GEMINI_TTS_MODEL).strip()
    language = str(config.get("ttsLanguage") or "pt-BR").strip()
    speed = config.get("ttsSpeed", 1.0)
    pitch = config.get("ttsPitch", 0.0)
    style_prompt = str(config.get("ttsPrompt") or "").strip()
    started_at = time.perf_counter()
    try:
        if provider_id == "gemini_tts":
            result = await GeminiTTSProvider(
                model=model or DEFAULT_GEMINI_TTS_MODEL,
                voice=voice or DEFAULT_GEMINI_TTS_VOICE,
                language=language,
                style_prompt=style_prompt,
            ).synthesize(clean_text)
        elif provider_id == "google_cloud_tts":
            result = await GoogleCloudTTSProvider(
                voice=voice or DEFAULT_GOOGLE_CLOUD_TTS_VOICE,
                language=language,
                speaking_rate=float(speed or 1.0),
                pitch=float(pitch or 0.0),
                streaming=False,
            ).synthesize(clean_text)
        else:
            result = await EdgeTTSProvider(voice=voice, speed=speed, pitch=pitch).synthesize(clean_text)
    except TTSConfigurationError:
        raise
    except Exception as exc:
        logger.exception("[Discord] TTS synthesis failed.")
        raise TTSConfigurationError(f"Discord TTS failed: {exc}") from exc
    return {
        "provider": result.provider,
        "voice": result.voice,
        "mimeType": result.mime_type,
        "audioBase64": b64encode(result.audio).decode("ascii"),
        "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
    }


async def _maybe_tts(request: Request, text: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Generate Discord playback audio only when Discord speech is enabled."""
    connections = _connections(request)
    if not (connections.get("discord") and connections.get("discordSpeak")):
        return None
    try:
        audio = await _synthesize_discord_tts(request, text)
    except TTSConfigurationError as exc:
        append_terminal_event(
            request.app.state.memory,
            {
                "kind": "error",
                "source": "discord_tts",
                "displayText": str(exc),
                "speechText": "",
                "status": "failed",
                "metadata": {"tts": False, **metadata},
            },
        )
        return None
    if audio:
        append_terminal_event(
            request.app.state.memory,
            {
                "kind": "assistant_speech",
                "source": "discord_tts",
                "displayText": f"TTS Discord pronto: {audio['provider']} / {audio['voice']}",
                "speechText": "",
                "status": "ready",
                "metadata": {"tts": False, **metadata, "bytesBase64": len(audio["audioBase64"])},
            },
        )
    return audio


@router.get("/config")
async def discord_config(request: Request) -> dict[str, Any]:
    return {"ok": True, "connections": _connections(request)}


@router.post("/message")
async def discord_message(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or payload.get("message") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Discord message text is required.")
    metadata = {
        "userId": payload.get("userId") or payload.get("user_id"),
        "displayName": payload.get("displayName") or payload.get("display_name") or payload.get("username"),
        "guildId": payload.get("guildId") or payload.get("guild_id"),
        "textChannelId": payload.get("textChannelId") or payload.get("text_channel_id"),
        "voiceChannelId": payload.get("voiceChannelId") or payload.get("voice_channel_id"),
    }
    assistant = await _run_discord_turn(request, text=text, metadata=metadata, payload=payload)
    audio = await _maybe_tts(request, str(assistant.get("text") or ""), metadata)
    return {"ok": bool(assistant.get("ok")), "text": assistant.get("text") or "", "assistant": assistant, "audio": audio}


@router.post("/audio")
async def discord_audio(request: Request) -> dict[str, Any]:
    connections = _connections(request)
    if not connections.get("discord"):
        raise HTTPException(status_code=409, detail="Discord integration is disabled.")
    if not connections.get("discordListen"):
        raise HTTPException(status_code=409, detail="Discord listening is disabled.")

    upload = await read_audio_upload(request)
    metadata = {
        "userId": upload.fields.get("userId") or upload.fields.get("user_id"),
        "displayName": upload.fields.get("displayName") or upload.fields.get("display_name") or upload.fields.get("username"),
        "guildId": upload.fields.get("guildId") or upload.fields.get("guild_id"),
        "textChannelId": upload.fields.get("textChannelId") or upload.fields.get("text_channel_id"),
        "voiceChannelId": upload.fields.get("voiceChannelId") or upload.fields.get("voice_channel_id"),
    }
    started_at = time.perf_counter()
    try:
        transcription = await asyncio.to_thread(
            GroqWhisperSTTProvider().transcribe_bytes,
            upload.audio,
            filename=upload.filename or "discord.wav",
            model=upload.fields.get("model") or None,
            language=upload.fields.get("language") or "pt",
        )
    except STTConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[Discord] STT failed.")
        raise HTTPException(status_code=502, detail=f"Discord STT failed: {exc}") from exc

    if not transcription.text:
        append_terminal_event(
            request.app.state.memory,
            {
                "kind": "system",
                "source": "discord_stt",
                "displayText": "Audio do Discord recebido sem transcricao util.",
                "speechText": "",
                "status": "empty",
                "metadata": {"tts": False, **metadata, "filtered": transcription.filtered},
            },
        )
        return {
            "ok": True,
            "transcribed": False,
            "text": "",
            "audio": None,
            "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
        }

    assistant = await _run_discord_turn(request, text=transcription.text, metadata=metadata, payload=upload.fields)
    audio = await _maybe_tts(request, str(assistant.get("text") or ""), metadata)
    return {
        "ok": bool(assistant.get("ok")),
        "transcribed": True,
        "text": transcription.text,
        "assistantText": assistant.get("text") or "",
        "assistant": assistant,
        "audio": audio,
        "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
    }
