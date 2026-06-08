from __future__ import annotations

import asyncio
import logging
import os
import time
from base64 import b64encode
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from hana_agent_oss.api.services.catalog import DEFAULT_CONNECTIONS
from hana_agent_oss.api.services.catalog import DEFAULT_LLM_CONFIG
from hana_agent_oss.api.services.catalog import DEFAULT_VOICE_CONFIG
from hana_agent_oss.api.services.chat import run_text_turn
from hana_agent_oss.api.services.terminal_agent import append_terminal_event
from hana_agent_oss.modules.voice.audio_control import request_global_stop
from hana_agent_oss.modules.voice.runtime import VoiceRuntime, voice_config_with_connections
from hana_agent_oss.modules.voice.speech_state import set_speaking
from hana_agent_oss.modules.voice.stt_whisper import GroqWhisperSTTProvider, STTConfigurationError
from hana_agent_oss.modules.voice.tts_edge import EdgeTTSProvider, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_gemini import DEFAULT_GEMINI_TTS_MODEL, DEFAULT_GEMINI_TTS_VOICE, GeminiTTSProvider
from hana_agent_oss.modules.voice.tts_google_cloud import (
    DEFAULT_GOOGLE_CLOUD_TTS_VOICE,
    GoogleCloudTTSProvider,
)
from hana_agent_oss.modules.voice.tts_cartesia import CartesiaTTSProvider, DEFAULT_CARTESIA_MODEL
from hana_agent_oss.modules.voice.tts_azure import AzureTTSProvider
from hana_agent_oss.modules.voice.tts_minimax import MinimaxTTSProvider
from hana_agent_oss.modules.voice.tts_elevenlabs import (
    DEFAULT_ELEVENLABS_MODEL,
    DEFAULT_ELEVENLABS_VOICE,
    ElevenlabsTTSProvider,
)
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["Voice"])

DEFAULT_AUDIO_FILENAME = "audio.wav"
MAX_AUDIO_UPLOAD_BYTES = int(os.environ.get("HANA_STT_MAX_UPLOAD_MB", "25")) * 1024 * 1024
LLM_PROVIDER_ALIASES = {
    "google_platform": "gemini_api",
    "google_cloud": "gemini_api",
    "google": "gemini_api",
    "google_ai_studio": "gemini_api",
    "gemini": "gemini_api",
    "open_router": "openrouter",
    "openrouters": "openrouter",
    "openrouter": "openrouter",
    "groq_cloud": "groq",
    "groqcloud": "groq",
    "glock": "groq",
    "groq": "groq",
}


@dataclass(frozen=True)
class AudioUpload:
    audio: bytes
    filename: str
    content_type: str
    fields: dict[str, str]


def build_groq_whisper_provider() -> GroqWhisperSTTProvider:
    return GroqWhisperSTTProvider()


def build_edge_tts_provider(*, voice: str, speed: Any, pitch: Any) -> EdgeTTSProvider:
    return EdgeTTSProvider(voice=voice, speed=speed, pitch=pitch)


def build_gemini_tts_provider(*, model: str, voice: str, language: str, style_prompt: str = "") -> GeminiTTSProvider:
    """Build Gemini TTS from persisted AI Studio voice settings."""
    return GeminiTTSProvider(model=model, voice=voice, language=language, style_prompt=style_prompt)


def build_google_cloud_tts_provider(*, voice: str, language: str, speed: Any, pitch: Any, streaming: bool = False) -> GoogleCloudTTSProvider:
    """Build Google Cloud TTS from dedicated Cloud Text-to-Speech settings."""
    return GoogleCloudTTSProvider(
        voice=voice,
        language=language,
        speaking_rate=_float_or_default(speed, 1.0),
        pitch=_float_or_default(pitch, 0.0),
        streaming=streaming,
    )


def build_cartesia_tts_provider(*, voice: str, model: str = "", speed: Any = 1.0) -> CartesiaTTSProvider:
    """Build Cartesia TTS (low latency, cheap, multiple pt-BR female voices via ID)."""
    return CartesiaTTSProvider(
        voice=str(voice or "").strip(),
        model=str(model or DEFAULT_CARTESIA_MODEL).strip() or DEFAULT_CARTESIA_MODEL,
        speed=_float_or_default(speed, 1.0),
    )


def build_azure_tts_provider(*, voice: str, language: str = "pt-BR", speed: Any = 1.0, pitch: Any = 0.0) -> AzureTTSProvider:
    """Build Azure Neural TTS (strong native pt-BR female voices like Francisca/Thalita)."""
    return AzureTTSProvider(
        voice=str(voice or "pt-BR-FranciscaNeural").strip(),
        language=str(language or "pt-BR").strip(),
        speed=_float_or_default(speed, 1.0),
        pitch=_float_or_default(pitch, 0.0),
    )


def build_elevenlabs_tts_provider(
    *,
    voice: str = "",
    model: str = "",
    language: str = "pt",
    speed: Any = 1.0,
    stability: Any = 0.5,
    similarity: Any = 0.75,
    style: Any = 0.0,
    speaker_boost: bool = True,
) -> ElevenlabsTTSProvider:
    """Build Elevenlabs TTS (high quality, realistic, multilingual)."""
    return ElevenlabsTTSProvider(
        voice=str(voice or DEFAULT_ELEVENLABS_VOICE).strip(),
        model=str(model or DEFAULT_ELEVENLABS_MODEL).strip(),
        language=str(language or "pt").strip(),
        speed=_float_or_default(speed, 1.0),
        stability=_float_or_default(stability, 0.5),
        similarity_boost=_float_or_default(similarity, 0.75),
        style=_float_or_default(style, 0.0),
        speaker_boost=bool(speaker_boost),
    )


def build_minimax_tts_provider(*, voice: str, model: str = "", speed: Any = 1.0) -> MinimaxTTSProvider:
    """Build Minimax T2A TTS (good pt-BR support, many female voices, turbo for low latency)."""
    return MinimaxTTSProvider(
        voice=str(voice or "Portuguese_ConfidentWoman").strip(),
        model=str(model or "speech-2.8-turbo").strip(),
        speed=_float_or_default(speed, 1.0),
        volume=1.0,
        pitch=0,
        language_boost="Portuguese",
    )


def _float_or_default(value: Any, default: float) -> float:
    """Normalize loose frontend numeric values before provider construction."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _runtime(request: Request) -> VoiceRuntime:
    runtime = getattr(request.app.state, "voice_runtime", None)
    if runtime is None or getattr(runtime, "memory", None) is not request.app.state.memory:
        runtime = VoiceRuntime(memory=request.app.state.memory, core=request.app.state.core)
        request.app.state.voice_runtime = runtime
    return runtime


def _connections_config(request: Request) -> dict[str, Any]:
    """Return persisted Connections as the authority for voice runtime state."""
    config = request.app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
    if not isinstance(config, dict):
        config = {}
    merged = dict(DEFAULT_CONNECTIONS)
    merged.update(config)
    return merged


def _sync_runtime_from_persisted_config(request: Request, *, start_requested: bool = False) -> dict[str, Any]:
    """Apply persisted voice settings without trusting runtime endpoint payload toggles."""
    runtime = _runtime(request)
    connections = _connections_config(request)
    config = voice_config_with_connections(request.app.state.memory)
    runtime.configure_hotkeys(connections)
    if start_requested and bool(config.get("sttEnabled")):
        return runtime.start(config)
    status = runtime.apply_config(config)
    if not bool(config.get("sttEnabled")) and bool(status.get("running")):
        return runtime.stop(reason="connections_stt_off")
    return status


def _field_bool(fields: dict[str, str], name: str, default: bool = False) -> bool:
    value = str(fields.get(name, default)).strip().lower()
    return value in {"1", "true", "yes", "on", "sim"}


def _normalize_llm_provider(provider: str | None) -> str:
    value = str(provider or "").strip().lower()
    return LLM_PROVIDER_ALIASES.get(value, value or "agent_core")


def _voice_llm_payload(request: Request, fields: dict[str, str], text: str) -> dict[str, Any]:
    """Build the text-turn payload from the main Cerebro & Voz LLM config."""
    config = request.app.state.memory.get_setting("llm_config", dict(DEFAULT_LLM_CONFIG))
    if not isinstance(config, dict):
        config = dict(DEFAULT_LLM_CONFIG)
    agent_settings = request.app.state.memory.get_setting("agent_settings", {"safety_mode": "safe"})
    if not isinstance(agent_settings, dict):
        agent_settings = {"safety_mode": "safe"}

    provider = _normalize_llm_provider(fields.get("llmProvider") or fields.get("llm_provider") or config.get("llmProvider"))
    return {
        "text": text,
        "provider": provider,
        "model": fields.get("llmModel") or fields.get("llm_model") or config.get("llmModel") or "structured-planner",
        "temperature": config.get("llmTemperature", 0.7),
        "native_search_mode": "off" if provider != "gemini_api" else (fields.get("nativeSearchMode") or fields.get("native_search_mode") or "auto"),
        "safety_mode": fields.get("safetyMode") or fields.get("safety_mode") or agent_settings.get("safety_mode") or "safe",
        "channel": "terminal_agent",
        "history": [],
        "openrouter_routing": (
            config.get("openrouterRoutingByModel", {}).get(str(fields.get("llmModel") or fields.get("llm_model") or config.get("llmModel") or ""), {})
            if provider == "openrouter" and isinstance(config.get("openrouterRoutingByModel"), dict)
            else {}
        ),
    }


async def _run_voice_text_response(request: Request, fields: dict[str, str], text: str) -> dict[str, Any]:
    append_terminal_event(
        request.app.state.memory,
        {
            "kind": "assistant_thought",
            "source": "agent_core",
            "displayText": "Mensagem recebida. Gerando resposta em texto.",
            "status": "planning",
            "metadata": {"tts": False},
        },
    )
    assistant_payload = await run_text_turn(
        _voice_llm_payload(request, fields, text),
        core=request.app.state.core,
        memory=request.app.state.memory,
    )
    meta = assistant_payload.get("meta", {})
    if isinstance(meta, dict) and "grounding" in meta:
        grounding = meta["grounding"]
        queries = grounding.get("queries", [])
        sources = grounding.get("sources", [])
        if queries or sources:
            lines = ["🔍 GOOGLE NATIVE SEARCH GROUNDING"]
            if queries:
                lines.append(f"Queries: {', '.join(f'\"{q}\"' for q in queries)}")
            if sources:
                lines.append("\nFontes indexadas pelo Gemini:")
                for s in sources:
                    title = s.get("title") or "Fonte"
                    uri = s.get("uri")
                    if uri:
                        lines.append(f"• {title}\n  {uri}")
            
            append_terminal_event(
                request.app.state.memory,
                {
                    "kind": "tool_result",
                    "source": "google_search",
                    "displayText": "\n".join(lines),
                    "speechText": "",
                    "status": "success",
                    "toolName": "google_search",
                    "metadata": {"tts": False, "grounding": grounding},
                },
            )

    if isinstance(meta, dict) and meta.get("media") and not meta.get("imageActions"):
        append_terminal_event(
            request.app.state.memory,
            {
                "kind": "tool_result",
                "source": "image_generation",
                "displayText": "Imagem gerada e anexada ao chat.",
                "speechText": "",
                "status": assistant_payload["status"].get("stage", "done"),
                "toolName": assistant_payload["status"].get("tool_name") or "image.generate",
                "metadata": {"tts": False, "media": meta.get("media")},
            },
        )

    append_terminal_event(
        request.app.state.memory,
        {
            "kind": "assistant_text",
            "source": "hana",
            "displayText": assistant_payload["text"],
            "speechText": "",
            "status": assistant_payload["status"].get("stage", "done"),
            "metadata": {
                "provider": assistant_payload["meta"].get("provider"),
                "model": assistant_payload["meta"].get("model"),
                "tts": False,
            },
        },
    )
    return assistant_payload


def _voice_config(request: Request) -> dict[str, Any]:
    config = request.app.state.memory.get_setting("voice_config", dict(DEFAULT_VOICE_CONFIG))
    if not isinstance(config, dict):
        config = dict(DEFAULT_VOICE_CONFIG)
    merged = dict(DEFAULT_VOICE_CONFIG)
    merged.update(config)
    return merged
def _clean_filename(filename: str | None) -> str:
    value = str(filename or DEFAULT_AUDIO_FILENAME).replace("\\", "/").split("/")[-1].strip()
    return value or DEFAULT_AUDIO_FILENAME


def _decode_form_value(payload: bytes, charset: str | None = None) -> str:
    return payload.decode(charset or "utf-8", errors="replace").strip()


def _parse_multipart_upload(content_type: str, body: bytes) -> AudioUpload:
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    fields: dict[str, str] = {}
    audio: bytes | None = None
    filename = DEFAULT_AUDIO_FILENAME
    audio_content_type = "application/octet-stream"

    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue

        name = str(part.get_param("name", header="content-disposition") or "").strip()
        part_filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if part_filename or name in {"file", "audio", "upload"}:
            audio = payload
            filename = _clean_filename(part_filename or name or DEFAULT_AUDIO_FILENAME)
            audio_content_type = str(part.get_content_type() or "application/octet-stream")
            continue

        if name:
            fields[name] = _decode_form_value(payload, part.get_content_charset())

    if audio is None:
        raise HTTPException(status_code=400, detail="Audio upload field not found.")

    return AudioUpload(audio=audio, filename=filename, content_type=audio_content_type, fields=fields)


async def read_audio_upload(request: Request) -> AudioUpload:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_AUDIO_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Audio upload too large.")
        except ValueError:
            pass

    body = await request.body()
    if len(body) > MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio upload too large.")
    if not body:
        raise HTTPException(status_code=400, detail="Audio upload is empty.")

    content_type = request.headers.get("content-type", "application/octet-stream")
    if content_type.lower().startswith("multipart/form-data"):
        return _parse_multipart_upload(content_type, body)

    filename = _clean_filename(request.headers.get("x-filename") or request.query_params.get("filename"))
    return AudioUpload(audio=body, filename=filename, content_type=content_type, fields={})


@router.post("/stt/transcribe")
async def transcribe_audio(
    request: Request,
    provider: str = Query("groq_whisper"),
    model: str | None = Query(None),
    language: str | None = Query(None),
    prompt: str | None = Query(None),
    respond: bool = Query(False),
) -> dict[str, Any]:
    upload = await read_audio_upload(request)
    provider_id = str(upload.fields.get("provider") or provider or "groq_whisper").strip().lower()
    if provider_id not in {"groq", "groq_whisper"}:
        raise HTTPException(status_code=400, detail="Only the groq_whisper STT provider is available.")

    selected_model = upload.fields.get("model") or model
    selected_language = upload.fields.get("language") or language
    selected_prompt = upload.fields.get("prompt") or prompt
    should_respond = _field_bool(upload.fields, "respond", respond)
    started_at = time.perf_counter()

    try:
        result = await asyncio.to_thread(
            build_groq_whisper_provider().transcribe_bytes,
            upload.audio,
            filename=upload.filename,
            model=selected_model,
            language=selected_language,
            prompt=selected_prompt,
        )
    except STTConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[STT] Groq Whisper transcription failed.")
        raise HTTPException(status_code=502, detail=f"Groq Whisper transcription failed: {exc}") from exc

    assistant_payload: dict[str, Any] | None = None
    if result.text:
        append_terminal_event(
            request.app.state.memory,
            {
                "kind": "user_text",
                "source": "stt",
                "displayText": result.text,
                "status": "transcribed",
                "metadata": {
                    "provider": result.provider,
                    "model": result.model,
                    "language": result.language,
                },
            },
        )
        if should_respond:
            assistant_payload = await _run_voice_text_response(request, upload.fields, result.text)
    else:
        append_terminal_event(
            request.app.state.memory,
            {
                "kind": "system",
                "source": "stt",
                "displayText": f"Audio recebido sem transcricao util: {upload.filename} ({len(upload.audio)} bytes)",
                "status": "filtered" if result.filtered else "empty",
                "metadata": {
                    "provider": result.provider,
                    "model": result.model,
                    "language": result.language,
                    "contentType": upload.content_type,
                    "filtered": result.filtered,
                },
            },
        )

    return {
        "ok": True,
        "provider": result.provider,
        "model": result.model,
        "language": result.language,
        "text": result.text,
        "rawText": result.raw_text,
        "filtered": result.filtered,
        "filename": upload.filename,
        "contentType": upload.content_type,
        "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
        "responded": bool(assistant_payload),
        "assistantText": assistant_payload["text"] if assistant_payload else "",
        "assistant": assistant_payload or None,
    }


@router.post("/text/respond")
async def respond_to_voice_text(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required.")

    append_terminal_event(
        request.app.state.memory,
        {
            "kind": "user_text",
            "source": "operator",
            "displayText": text,
            "speechText": "",
            "status": "manual",
            "metadata": {"tts": False},
        },
    )
    fields = {key: str(value) for key, value in payload.items() if value is not None}
    assistant_payload = await _run_voice_text_response(request, fields, text)
    connections = request.app.state.memory.get_setting("connections_config", {})
    if bool(connections.get("tts")) and assistant_payload.get("text"):
        runtime = _runtime(request)
        await runtime.speak_text(str(assistant_payload["text"]))
    return {
        "ok": True,
        "text": text,
        "assistantText": assistant_payload["text"],
        "responded": True,
        "assistant": assistant_payload,
    }


@router.post("/tts/synthesize")
async def synthesize_voice_tts(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    config = _voice_config(request)
    provider_id = str(payload.get("provider") or config.get("ttsProvider") or "edge").strip().lower()
    if provider_id not in {"edge", "gemini_tts", "google_cloud_tts", "google", "cartesia", "azure", "minimax", "elevenlabs"}:
        raise HTTPException(status_code=400, detail=f"Unsupported TTS provider: {provider_id}.")
    if provider_id == "google":
        provider_id = "google_cloud_tts"

    text = sanitize_tts_text(
        str(
            payload.get("speechText")
            or payload.get("speech_text")
            or payload.get("ttsText")
            or payload.get("tts_text")
            or payload.get("text")
            or ""
        )
    )
    if not text:
        raise HTTPException(status_code=400, detail="TTS text is empty.")

    voice = str(payload.get("voice") or config.get("ttsVoice") or "").strip()
    language = str(payload.get("language") or config.get("ttsLanguage") or "pt-BR").strip()

    # Provider-aware default for model (important for cartesia which does not accept Gemini model names)
    if provider_id == "cartesia":
        default_model = DEFAULT_CARTESIA_MODEL
    elif provider_id == "gemini_tts":
        default_model = DEFAULT_GEMINI_TTS_MODEL
    elif provider_id == "minimax":
        default_model = "speech-2.8-turbo"
    elif provider_id == "elevenlabs":
        default_model = DEFAULT_ELEVENLABS_MODEL
    else:
        default_model = ""
    model = str(payload.get("model") or config.get("ttsModel") or default_model).strip()
    style_prompt = str(payload.get("prompt") or payload.get("stylePrompt") or config.get("ttsPrompt") or "").strip()
    speed = payload.get("speed", config.get("ttsSpeed", 1.0))
    pitch = payload.get("pitch", config.get("ttsPitch", 0.0))
    streaming = bool(payload.get("streaming", config.get("ttsStreaming", False)))
    started_at = time.perf_counter()

    try:
        if provider_id == "gemini_tts":
            result = await build_gemini_tts_provider(
                model=model or DEFAULT_GEMINI_TTS_MODEL,
                voice=voice or DEFAULT_GEMINI_TTS_VOICE,
                language=language or "pt-BR",
                style_prompt=style_prompt,
            ).synthesize(text)
        elif provider_id == "google_cloud_tts":
            result = await build_google_cloud_tts_provider(
                voice=voice or DEFAULT_GOOGLE_CLOUD_TTS_VOICE,
                language=language or "pt-BR",
                speed=speed,
                pitch=pitch,
                streaming=streaming,
            ).synthesize(text)
        elif provider_id == "cartesia":
            result = await build_cartesia_tts_provider(
                voice=voice,
                model=model,
                language=language,
                speed=speed,
            ).synthesize(text)
        elif provider_id == "azure":
            result = await build_azure_tts_provider(
                voice=voice,
                language=language,
                speed=speed,
                pitch=pitch,
            ).synthesize(text)
        elif provider_id == "minimax":
            result = await build_minimax_tts_provider(
                voice=voice,
                model=model,
                speed=speed,
            ).synthesize(text)
        elif provider_id == "elevenlabs":
            result = await build_elevenlabs_tts_provider(
                voice=voice,
                model=model,
                speed=speed,
                stability=payload.get("stability", config.get("ttsStability", 0.5)),
                similarity=payload.get("similarity", config.get("ttsSimilarity", 0.75)),
                style=payload.get("style", config.get("ttsStyle", 0.0)),
                speaker_boost=payload.get("speakerBoost", config.get("ttsSpeakerBoost", True)),
            ).synthesize(text)
        else:
            result = await build_edge_tts_provider(voice=voice, speed=speed, pitch=pitch).synthesize(text)
    except TTSConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[TTS] Synthesis failed.")
        raise HTTPException(status_code=502, detail=f"{provider_id} synthesis failed: {exc}") from exc

    append_terminal_event(
        request.app.state.memory,
        {
            "kind": "assistant_speech",
            "source": "tts",
            "displayText": f"TTS {result.provider} gerou audio: {result.voice}",
            "speechText": "",
            "status": "ready",
            "metadata": {
                "provider": result.provider,
                "model": model if provider_id == "gemini_tts" else "",
                "voice": result.voice,
                "rate": result.rate,
                "pitch": result.pitch,
                "bytes": len(result.audio),
                "streaming": streaming,
                "tts": False,
            },
        },
    )

    return {
        "ok": True,
        "provider": result.provider,
        "voice": result.voice,
        "rate": result.rate,
        "pitch": result.pitch,
        "volume": result.volume,
        "text": result.text,
        "mimeType": result.mime_type,
        "audioBase64": b64encode(result.audio).decode("ascii"),
        "durationMs": round((time.perf_counter() - started_at) * 1000, 2),
    }


@router.post("/tts/speak")
async def speak_voice_tts(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    text = sanitize_tts_text(
        str(
            payload.get("speechText")
            or payload.get("speech_text")
            or payload.get("ttsText")
            or payload.get("tts_text")
            or payload.get("text")
            or ""
        )
    )
    if not text:
        raise HTTPException(status_code=400, detail="TTS text is empty.")

    connections = request.app.state.memory.get_setting("connections_config", {})
    if not bool(connections.get("tts")):
        raise HTTPException(status_code=409, detail="TTS is disabled in Conexoes.")

    runtime = _runtime(request)
    runtime.apply_config(voice_config_with_connections(request.app.state.memory))
    spoken = await runtime.speak_text(text)
    if not spoken:
        raise HTTPException(status_code=409, detail="TTS did not produce playable audio.")
    return {"ok": spoken, "spoken": spoken, "text": text}


@router.post("/tts/stop")
async def stop_voice_tts(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    reason = str((payload or {}).get("reason") or "voice_tts_stop")
    request_global_stop(reason)
    _runtime(request).interrupt(reason=reason, append_event=False)
    set_speaking(False)
    append_terminal_event(
        request.app.state.memory,
        {
            "kind": "speaking",
            "source": "tts",
            "displayText": "TTS stop requested.",
            "speechText": "",
            "status": "stopped",
            "metadata": {"tts": False, "reason": reason},
        },
    )
    return {"status": "ok", "stopped": True, "reason": reason}


@router.post("/runtime/start")
async def start_voice_runtime(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    status = _sync_runtime_from_persisted_config(request, start_requested=True)
    return {
        "ok": True,
        "started": bool(status.get("running")) and bool(status.get("config", {}).get("sttEnabled")),
        "runtime": status,
    }


@router.post("/runtime/configure")
async def configure_voice_runtime(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    status = _sync_runtime_from_persisted_config(request, start_requested=False)
    return {"ok": True, "runtime": status}


@router.post("/runtime/stop")
async def stop_voice_runtime(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    reason = str((payload or {}).get("reason") or "user_request")
    status = _runtime(request).stop(reason=reason)
    return {"ok": True, "runtime": status}


@router.get("/runtime/status")
async def voice_runtime_status(request: Request) -> dict[str, Any]:
    return {"ok": True, "runtime": _runtime(request).status()}


@router.post("/runtime/interrupt")
async def interrupt_voice_runtime(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    reason = str((payload or {}).get("reason") or "user_request")
    status = _runtime(request).interrupt(reason=reason)
    return {"ok": True, "runtime": status}
