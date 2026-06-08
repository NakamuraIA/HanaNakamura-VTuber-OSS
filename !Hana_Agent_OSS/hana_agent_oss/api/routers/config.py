from __future__ import annotations

import copy
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from hana_agent_oss.api.services.catalog import (
    DEFAULT_CHAT_CONFIG,
    DEFAULT_CONNECTIONS,
    DEFAULT_LLM_CONFIG,
    DEFAULT_VOICE_CONFIG,
    VOICE_PROVIDER_CATALOG,
    catalog_payload,
    delete_custom_model,
    upsert_custom_model,
)
from hana_agent_oss.modules.voice.devices import list_input_devices
from hana_agent_oss.modules.voice.runtime import VoiceRuntime, voice_config_with_connections
from hana_agent_oss.modules.vision.periodic_vision import (
    DEFAULT_VISION_QUALITY_PROFILE,
    normalize_vision_quality_profile,
)
from hana_agent_oss.tools.omni_tools import normalize_omni_base_url, omni_status
from hana_agent_oss.providers.provider_selector.openrouter.catalog import get_openrouter_endpoints

router = APIRouter(tags=["Configuration"])


PROVIDER_ALIASES = {
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


def normalize_provider(provider: Any) -> str:
    value = str(provider or "").strip().lower()
    return PROVIDER_ALIASES.get(value, value or "gemini_api")


def normalize_openrouter_routing_by_model(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize persisted per-model OpenRouter routing without accepting arbitrary fields."""
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for model_id, raw in value.items():
        model = str(model_id or "").strip()
        if not model or not isinstance(raw, dict):
            continue
        normalized[model] = {
            "preferredEndpoint": str(raw.get("preferredEndpoint") or "").strip().lower(),
            "allowFallbacks": bool(raw.get("allowFallbacks", True)),
            "requireParameters": bool(raw.get("requireParameters", False)),
            "dataCollection": "deny" if raw.get("dataCollection") == "deny" else "allow",
            "zdr": bool(raw.get("zdr", False)),
        }
    return normalized


def normalize_llm_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize the primary LLM and chat-owned TTS settings."""
    normalized = dict(DEFAULT_LLM_CONFIG)
    normalized.update(config)
    normalized["llmProvider"] = normalize_provider(normalized.get("llmProvider"))
    normalized["openrouterRoutingByModel"] = normalize_openrouter_routing_by_model(normalized.get("openrouterRoutingByModel"))
    normalized["ttsProvider"] = normalize_tts_provider(normalized.get("ttsProvider"))
    normalized["ttsLanguage"] = str(normalized.get("ttsLanguage") or DEFAULT_LLM_CONFIG["ttsLanguage"]).strip()
    normalized["ttsPrompt"] = str(normalized.get("ttsPrompt") or DEFAULT_LLM_CONFIG["ttsPrompt"]).strip()
    normalized["ttsStreaming"] = bool(normalized.get("ttsStreaming", False))
    try:
        normalized["ttsSpeed"] = float(normalized.get("ttsSpeed") or DEFAULT_LLM_CONFIG["ttsSpeed"])
    except (TypeError, ValueError):
        normalized["ttsSpeed"] = DEFAULT_LLM_CONFIG["ttsSpeed"]
    try:
        normalized["ttsPitch"] = float(normalized.get("ttsPitch") or DEFAULT_LLM_CONFIG["ttsPitch"])
    except (TypeError, ValueError):
        normalized["ttsPitch"] = DEFAULT_LLM_CONFIG["ttsPitch"]
    _normalize_tts_volume(normalized, DEFAULT_LLM_CONFIG)
    _normalize_elevenlabs_controls(normalized, DEFAULT_LLM_CONFIG)
    return normalized


def normalize_chat_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(DEFAULT_CHAT_CONFIG)
    normalized.update(config)
    normalized["provider"] = normalize_provider(normalized.get("provider"))
    normalized["openrouterRoutingByModel"] = normalize_openrouter_routing_by_model(normalized.get("openrouterRoutingByModel"))
    if normalized["provider"] != "gemini_api":
        normalized["nativeSearchMode"] = "off"
    return normalized


STT_PROVIDER_IDS = {"groq_whisper", "gemini_audio", "google", "openai", "local"}
TTS_PROVIDER_IDS = {"edge", "gemini_tts", "google_cloud_tts", "google", "azure", "cartesia", "minimax", "elevenlabs"}


def normalize_stt_provider(provider: Any) -> str:
    value = str(provider or "").strip().lower()
    aliases = {
        "groq": "groq_whisper",
        "whisper": "groq_whisper",
        "whisper_large_v3": "groq_whisper",
        "gemini": "gemini_audio",
        "google": "gemini_audio",
    }
    value = aliases.get(value, value)
    return value if value in STT_PROVIDER_IDS else "groq_whisper"


def normalize_tts_provider(provider: Any) -> str:
    value = str(provider or "").strip().lower()
    aliases = {
        "gemini": "gemini_tts",
        "gemini_api": "gemini_tts",
        "google_ai_studio": "gemini_tts",
        "google_cloud": "google_cloud_tts",
        "google_tts": "google_cloud_tts",
        "cloud_tts": "google_cloud_tts",
        "google": "google_cloud_tts",
        "cartesia_tts": "cartesia",
        "cartesia_sonic": "cartesia",
        "minimax_tts": "minimax",
        "minimax_t2a": "minimax",
        "elevenlabs_tts": "elevenlabs",
        "eleven_labs": "elevenlabs",
        "elevenlabs": "elevenlabs",
    }
    value = aliases.get(value, value)
    return value if value in TTS_PROVIDER_IDS else "edge"


def normalize_voice_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize Terminal Agent provider/device options without owning on/off state."""
    normalized = dict(DEFAULT_VOICE_CONFIG)
    normalized.update(config)
    normalized["sttProvider"] = normalize_stt_provider(normalized.get("sttProvider"))
    normalized["ttsProvider"] = normalize_tts_provider(normalized.get("ttsProvider"))
    normalized["speakTerminalEvents"] = bool(normalized.get("speakTerminalEvents", True))
    normalized["ttsStreaming"] = bool(normalized.get("ttsStreaming", False))
    normalized["ttsPrompt"] = str(normalized.get("ttsPrompt") or DEFAULT_VOICE_CONFIG.get("ttsPrompt") or "").strip()
    normalized["inputDeviceId"] = str(normalized.get("inputDeviceId") or "").strip()
    normalized["inputDeviceLabel"] = str(normalized.get("inputDeviceLabel") or "").strip()
    normalized["inputDeviceSource"] = str(normalized.get("inputDeviceSource") or "sounddevice").strip()
    try:
        normalized["ttsSpeed"] = float(normalized.get("ttsSpeed") or DEFAULT_VOICE_CONFIG["ttsSpeed"])
    except (TypeError, ValueError):
        normalized["ttsSpeed"] = DEFAULT_VOICE_CONFIG["ttsSpeed"]
    try:
        normalized["ttsPitch"] = float(normalized.get("ttsPitch") or DEFAULT_VOICE_CONFIG["ttsPitch"])
    except (TypeError, ValueError):
        normalized["ttsPitch"] = DEFAULT_VOICE_CONFIG["ttsPitch"]
    _normalize_tts_volume(normalized, DEFAULT_VOICE_CONFIG)
    _normalize_elevenlabs_controls(normalized, DEFAULT_VOICE_CONFIG)
    try:
        normalized["vadThreshold"] = float(normalized.get("vadThreshold") or DEFAULT_VOICE_CONFIG["vadThreshold"])
    except (TypeError, ValueError):
        normalized["vadThreshold"] = DEFAULT_VOICE_CONFIG["vadThreshold"]
    try:
        normalized["silenceTimeoutMs"] = int(normalized.get("silenceTimeoutMs") or DEFAULT_VOICE_CONFIG["silenceTimeoutMs"])
    except (TypeError, ValueError):
        normalized["silenceTimeoutMs"] = DEFAULT_VOICE_CONFIG["silenceTimeoutMs"]
    return normalized


def _normalize_tts_volume(config: dict[str, Any], defaults: dict[str, Any]) -> None:
    """Clamp local playback volume without changing provider synthesis payloads."""
    try:
        value = float(config.get("ttsVolume", defaults["ttsVolume"]))
    except (TypeError, ValueError):
        value = float(defaults["ttsVolume"])
    config["ttsVolume"] = max(0.0, min(1.0, value))


def _normalize_elevenlabs_controls(config: dict[str, Any], defaults: dict[str, Any]) -> None:
    """Clamp persisted ElevenLabs voice controls to the supported API ranges."""
    for key in ("ttsStability", "ttsSimilarity", "ttsStyle"):
        try:
            value = float(config.get(key, defaults[key]))
        except (TypeError, ValueError):
            value = float(defaults[key])
        config[key] = max(0.0, min(1.0, value))
    config["ttsSpeakerBoost"] = bool(config.get("ttsSpeakerBoost", defaults["ttsSpeakerBoost"]))



def normalize_connections_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize global feature toggles owned by the Connections tab."""
    normalized = dict(DEFAULT_CONNECTIONS)
    normalized.update(config)
    for key in ("tts", "stt", "vad", "ptt", "stopHotkey", "vts", "discord", "discordSpeak", "discordListen", "omni", "visao"):
        normalized[key] = bool(normalized.get(key))
    normalized["pttKey"] = str(normalized.get("pttKey") or DEFAULT_CONNECTIONS["pttKey"]).strip() or DEFAULT_CONNECTIONS["pttKey"]
    normalized["stopKey"] = str(normalized.get("stopKey") or DEFAULT_CONNECTIONS["stopKey"]).strip() or DEFAULT_CONNECTIONS["stopKey"]
    normalized["omniUrl"] = normalize_omni_base_url(normalized.get("omniUrl"))
    return normalized


def _default_media_output_path() -> str:
    try:
        return os.path.join(os.path.expanduser("~"), "Pictures", "Hana Artista")
    except Exception:
        return "C:\\Hana Artista"


DEFAULT_PORTABILITY_CONFIG = {
    "ffmpegPath": "ffmpeg",
    "mediaOutputPath": _default_media_output_path(),
    "activeMonitor": 1,
    "visionQualityProfile": DEFAULT_VISION_QUALITY_PROFILE,
}


def normalize_portability_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize PC environment settings."""
    normalized = dict(DEFAULT_PORTABILITY_CONFIG)
    normalized.update(config)
    normalized["ffmpegPath"] = str(normalized.get("ffmpegPath") or "ffmpeg").strip()
    media_path = str(normalized.get("mediaOutputPath") or "").strip()
    if not media_path or media_path in (".", "./", "data", "./data", "data/", "./data/"):
        media_path = _default_media_output_path()
    normalized["mediaOutputPath"] = media_path
    normalized["visionQualityProfile"] = normalize_vision_quality_profile(normalized.get("visionQualityProfile"))
    try:
        normalized["activeMonitor"] = int(normalized.get("activeMonitor", 1))
    except (TypeError, ValueError):
        normalized["activeMonitor"] = 1
    return normalized


def _runtime(request: Request) -> VoiceRuntime:
    runtime = getattr(request.app.state, "voice_runtime", None)
    if runtime is None or getattr(runtime, "memory", None) is not request.app.state.memory:
        runtime = VoiceRuntime(memory=request.app.state.memory, core=request.app.state.core)
        request.app.state.voice_runtime = runtime
    return runtime


def _sync_voice_runtime(request: Request, connections: dict[str, Any] | None = None) -> None:
    """Apply persisted voice/connections settings to the backend runtime immediately."""
    runtime = _runtime(request)
    config = voice_config_with_connections(request.app.state.memory)
    runtime.configure_hotkeys(connections or normalize_connections_config(request.app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))))
    if config.get("sttEnabled"):
        runtime.start(config)
    else:
        runtime.apply_config(config)
        if runtime.status().get("running"):
            runtime.stop(reason="connections_stt_off")


def voice_config_with_connection_state(request: Request, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return voice options plus read-only STT/TTS activation state from Connections."""
    voice_config = normalize_voice_config(config or request.app.state.memory.get_setting("voice_config", dict(DEFAULT_VOICE_CONFIG)))
    connections = normalize_connections_config(request.app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS)))
    return {
        **voice_config,
        "sttEnabled": connections["stt"],
        "ttsEnabled": connections["tts"],
        "connectionState": {
            "stt": connections["stt"],
            "tts": connections["tts"],
            "owner": "connections",
        },
    }


def resolve_chat_config(request: Request) -> dict[str, Any]:
    chat_config = request.app.state.memory.get_setting("chat_config", None)
    if isinstance(chat_config, dict):
        return normalize_chat_config(chat_config)
    llm_config = normalize_llm_config(request.app.state.memory.get_setting("llm_config", dict(DEFAULT_LLM_CONFIG)))
    return normalize_chat_config({
        "provider": llm_config.get("llmProvider"),
        "model": str(llm_config.get("llmModel") or DEFAULT_CHAT_CONFIG["model"]),
        "nativeSearchMode": DEFAULT_CHAT_CONFIG["nativeSearchMode"],
    })


@router.get("/api/config/llm")
async def get_llm_config(request: Request) -> dict[str, Any]:
    return normalize_llm_config(request.app.state.memory.get_setting("llm_config", dict(DEFAULT_LLM_CONFIG)))


@router.post("/api/config/llm")
async def update_llm_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    current = normalize_llm_config(request.app.state.memory.get_setting("llm_config", dict(DEFAULT_LLM_CONFIG)))
    current.update(payload)
    return request.app.state.memory.set_setting("llm_config", normalize_llm_config(current))


@router.get("/api/config/chat")
async def get_chat_config(request: Request) -> dict[str, Any]:
    return resolve_chat_config(request)


@router.post("/api/config/chat")
async def update_chat_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    current = resolve_chat_config(request)
    current.update(payload)
    return request.app.state.memory.set_setting("chat_config", normalize_chat_config(current))


@router.get("/api/config/voice")
async def get_voice_config(request: Request) -> dict[str, Any]:
    return voice_config_with_connection_state(request)


@router.post("/api/config/voice")
async def update_voice_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    current = normalize_voice_config(request.app.state.memory.get_setting("voice_config", dict(DEFAULT_VOICE_CONFIG)))
    payload = {key: value for key, value in payload.items() if key not in {"sttEnabled", "ttsEnabled", "connectionState"}}
    current.update(payload)
    saved = request.app.state.memory.set_setting("voice_config", normalize_voice_config(current))
    _runtime(request).apply_config(voice_config_with_connections(request.app.state.memory))
    return voice_config_with_connection_state(request, saved)


@router.get("/api/config/voice/input-devices")
async def get_voice_input_devices() -> dict[str, Any]:
    return list_input_devices()


@router.get("/api/config/voice/catalog")
async def get_voice_catalog() -> dict[str, Any]:
    catalog = copy.deepcopy(VOICE_PROVIDER_CATALOG)
    stt_providers = catalog.setdefault("sttProviders", [])
    if not any(item.get("id") == "groq_whisper" for item in stt_providers if isinstance(item, dict)):
        stt_providers.append(
            {
                "id": "groq_whisper",
                "label": "Groq Whisper",
                "status": "available",
                "requiresCredentials": True,
                "inputModalities": ["audio"],
                "outputModalities": ["text"],
                "defaultModel": "whisper-large-v3",
                "defaultLanguage": "pt",
            }
        )
    return catalog


@router.get("/api/config/conexoes")
async def get_connections(request: Request) -> dict[str, Any]:
    return normalize_connections_config(request.app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS)))


@router.post("/api/config/conexoes")
async def update_connections(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    current = normalize_connections_config(request.app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS)))
    current.update(payload)
    saved = request.app.state.memory.set_setting("connections_config", normalize_connections_config(current))
    _sync_voice_runtime(request, saved)
    return saved


@router.get("/api/config/omni/status")
async def get_omni_status(request: Request) -> dict[str, Any]:
    connections = normalize_connections_config(request.app.state.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS)))
    status = omni_status(str(connections.get("omniUrl") or ""))
    return {"enabled": bool(connections.get("omni")), **status}


@router.get("/api/config/portabilidade")
async def get_portability_config(request: Request) -> dict[str, Any]:
    return normalize_portability_config(request.app.state.memory.get_setting("portabilidade_config", dict(DEFAULT_PORTABILITY_CONFIG)))


@router.post("/api/config/portabilidade")
async def update_portability_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    current = normalize_portability_config(request.app.state.memory.get_setting("portabilidade_config", dict(DEFAULT_PORTABILITY_CONFIG)))
    current.update(payload)
    return request.app.state.memory.set_setting("portabilidade_config", normalize_portability_config(current))


@router.get("/api/config/visao/monitors")
async def get_vision_monitors() -> dict[str, Any]:
    monitors = []
    try:
        import mss
        with mss.mss() as sct:
            for idx, m in enumerate(sct.monitors):
                label = "Tela Combinada" if idx == 0 else f"Monitor {idx}"
                monitors.append({
                    "id": idx,
                    "label": f"{label} ({m['width']}x{m['height']})",
                    "width": m["width"],
                    "height": m["height"]
                })
    except Exception as e:
        monitors = [{"id": 1, "label": "Monitor 1 (1920x1080)", "width": 1920, "height": 1080}]
    return {"monitors": monitors}


@router.get("/api/agent/settings")
async def get_agent_settings(request: Request) -> dict[str, Any]:
    return request.app.state.memory.get_setting("agent_settings", {"safety_mode": "safe"})


@router.post("/api/agent/settings")
async def update_agent_settings(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    return request.app.state.memory.set_setting("agent_settings", {"safety_mode": str(payload.get("safety_mode") or "safe")})


# ---------------------------------------------------------------------------
# Image provider configuration
# ---------------------------------------------------------------------------

DEFAULT_IMAGE_CONFIG: dict[str, Any] = {
    "imageProvider": "gemini_api",
    "openrouterImageModel": "",
    "openrouterReasoning": "medium",
}

IMAGE_PROVIDER_ALIASES = {
    "gemini_api": "gemini_api",
    "gemini": "gemini_api",
    "google": "gemini_api",
    "google_ai_studio": "gemini_api",
    "openrouter": "openrouter",
    "open_router": "openrouter",
}


def normalize_image_provider(provider: Any) -> str:
    """Normalize image provider ID strings."""
    value = str(provider or "").strip().lower()
    return IMAGE_PROVIDER_ALIASES.get(value, value or "gemini_api")


def normalize_image_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize image generation settings."""
    normalized = dict(DEFAULT_IMAGE_CONFIG)
    normalized.update(config)
    normalized["imageProvider"] = normalize_image_provider(normalized.get("imageProvider"))
    normalized["openrouterImageModel"] = str(normalized.get("openrouterImageModel") or "").strip()
    normalized["openrouterReasoning"] = str(normalized.get("openrouterReasoning") or "medium").strip()
    return normalized


@router.get("/api/config/image")
async def get_image_config(request: Request) -> dict[str, Any]:
    """Return image generation provider configuration."""
    return normalize_image_config(request.app.state.memory.get_setting("image_config", dict(DEFAULT_IMAGE_CONFIG)))


@router.post("/api/config/image")
async def update_image_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Update image generation provider configuration."""
    current = normalize_image_config(request.app.state.memory.get_setting("image_config", dict(DEFAULT_IMAGE_CONFIG)))
    current.update(payload)
    saved = request.app.state.memory.set_setting("image_config", normalize_image_config(current))
    # Also persist the provider ID separately for ImageGenerationService to pick up.
    request.app.state.memory.set_setting("image_provider", saved.get("imageProvider", "gemini_api"))
    return saved



@router.get("/api/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    return catalog_payload(request.app.state.memory)


@router.get("/api/catalog/openrouter/endpoints")
async def openrouter_endpoints(model: str) -> dict[str, Any]:
    """Expose the endpoint catalog for one OpenRouter model."""
    endpoints, error = get_openrouter_endpoints(model)
    return {"model": model, "endpoints": endpoints, "error": error}


@router.post("/api/catalog/custom-models")
async def create_custom_model(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "model": upsert_custom_model(request.app.state.memory, payload)}


@router.delete("/api/catalog/custom-models")
async def remove_custom_model(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "deleted": delete_custom_model(request.app.state.memory, payload)}


@router.get("/api/permissions/pending")
async def pending_permissions() -> dict[str, Any]:
    return {"permissions": []}


@router.post("/api/permissions/{permission_id}/approve")
async def approve_permission(permission_id: str) -> dict[str, Any]:
    return {"status": "ok", "permission_id": permission_id}


@router.post("/api/permissions/{permission_id}/deny")
async def deny_permission(permission_id: str) -> dict[str, Any]:
    return {"status": "ok", "permission_id": permission_id}


@router.post("/api/permissions/cancel-all")
async def cancel_permissions() -> dict[str, Any]:
    return {"status": "ok"}
