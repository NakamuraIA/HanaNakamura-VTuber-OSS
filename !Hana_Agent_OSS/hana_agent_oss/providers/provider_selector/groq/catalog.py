from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_CHAT_COMPLETIONS_URL = f"{GROQ_BASE_URL}/chat/completions"
GROQ_MODELS_URL = f"{GROQ_BASE_URL}/models"
GROQ_CATALOG_CACHE_SECONDS = 300

_MODEL_CACHE: dict[str, Any] = {"loaded_at": 0.0, "models": [], "error": None}


GROQ_STATIC_MODELS: list[dict[str, Any]] = [
    {
        "id": "llama-3.3-70b-versatile",
        "label": "Llama 3.3 70B",
        "provider": "groq",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": False,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": [],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 32_768,
        "pricing": {"prompt": "0.00000059", "completion": "0.00000079"},
        "description": "Groq production multilingual text model.",
    },
    {
        "id": "llama-3.1-8b-instant",
        "label": "Llama 3.1 8B Instant",
        "provider": "groq",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": False,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": [],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 131_072,
        "pricing": {"prompt": "0.00000005", "completion": "0.00000008"},
        "description": "Low-cost Groq text model.",
    },
    {
        "id": "openai/gpt-oss-120b",
        "label": "GPT OSS 120B",
        "provider": "groq",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice"],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 65_536,
        "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
        "description": "Groq reasoning/text model with function calling support.",
    },
    {
        "id": "openai/gpt-oss-20b",
        "label": "GPT OSS 20B",
        "provider": "groq",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice"],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 65_536,
        "pricing": {"prompt": "0.000000075", "completion": "0.0000003"},
        "description": "Fast Groq reasoning/text model with function calling support.",
    },
    {
        "id": "qwen/qwen3-32b",
        "label": "Qwen3 32B",
        "provider": "groq",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice"],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 40_960,
        "pricing": {"prompt": "0.00000029", "completion": "0.00000059"},
        "description": "Preview Groq text/reasoning model.",
    },
    {
        "id": "qwen/qwen3.6-27b",
        "label": "Qwen3.6 27B (visão)",
        "provider": "groq",
        "supportsVision": True,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text", "image"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice"],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 32_768,
        "description": "Groq Qwen3.6 27B: reasoning + visão (texto e imagem) com function calling.",
    },
    {
        "id": "meta-llama/llama-4-scout-17b-16e-instruct",
        "label": "Llama 4 Scout 17B 16E",
        "provider": "groq",
        "supportsVision": True,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text", "image"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice"],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 8_192,
        "pricing": {"prompt": "0.00000011", "completion": "0.00000034"},
        "description": "Groq preview vision model for text and image input.",
    },
    {
        "id": "groq/compound",
        "label": "Compound",
        "provider": "groq",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": False,
        "supportsNativeSearch": True,
        "supportsCodeExecution": True,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": [],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 8_192,
        "description": "Groq compound system with server-side web search and code execution.",
    },
    {
        "id": "groq/compound-mini",
        "label": "Compound Mini",
        "provider": "groq",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": False,
        "supportsNativeSearch": True,
        "supportsCodeExecution": True,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": [],
        "maxInputTokens": 131_072,
        "maxOutputTokens": 8_192,
        "description": "Lower-latency Groq compound system with one server-side tool call.",
    },
]


def groq_headers(*, include_auth: bool = True) -> dict[str, str]:
    """Build Groq API headers without exposing the API key in logs.

    Groq sits behind Cloudflare and aggressively blocks default Python urllib user-agents
    with "browser_signature_banned" (Error 1010). We mimic a legitimate OpenAI-compatible client.
    """
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
        "User-Agent": "OpenAI/Python 1.54.0",  # matches the official openai library UA to avoid Cloudflare 1010 browser_signature_banned
        "X-Groq-Client": "hana-agent-oss",
    }
    api_key = os.environ.get("GROQ_API_KEY")
    if include_auth and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _number_or_none(value: Any) -> int | None:
    """Convert Groq catalog token fields into positive integers."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _overlay_for(model_id: str) -> dict[str, Any]:
    """Return static capability hints for models whose API metadata is sparse."""
    return next((dict(item) for item in GROQ_STATIC_MODELS if item.get("id") == model_id), {})


def _merge_model(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge dynamic model metadata with curated Groq capability hints."""
    merged = {**base, **{key: value for key, value in overlay.items() if value not in (None, "", [])}}
    merged["provider"] = "groq"
    return merged


def map_groq_model(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one Groq model record into the Control Center catalog shape."""
    model_id = str(raw.get("id") or "").strip()
    overlay = _overlay_for(model_id)
    model = {
        "id": model_id,
        "label": str(raw.get("owned_by") or model_id),
        "provider": "groq",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": False,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": [],
        "maxInputTokens": _number_or_none(raw.get("context_window") or raw.get("context_length")),
        "maxOutputTokens": _number_or_none(raw.get("max_completion_tokens")),
        "description": "",
    }
    if model_id and model_id not in {"whisper-large-v3", "whisper-large-v3-turbo"}:
        return _merge_model(model, overlay)
    return {}


def _request_models(timeout_seconds: float = 8.0) -> list[dict[str, Any]]:
    """Fetch Groq models through the documented OpenAI-compatible models endpoint.
    Prefers the official groq SDK if installed for better compatibility (avoids UA blocks).
    Falls back to raw HTTP only if SDK not available.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("missing_credentials:GROQ_API_KEY")

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        models_response = client.models.list()
        return [m.model_dump() if hasattr(m, "model_dump") else dict(m) for m in getattr(models_response, "data", [])]
    except ImportError:
        # Fallback to raw urllib (with improved headers to avoid Cloudflare blocks)
        request = urllib.request.Request(
            GROQ_MODELS_URL,
            headers=groq_headers(include_auth=True),
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        body = json.loads(raw_body) if raw_body else {}
        data = body.get("data")
        if not isinstance(data, list):
            raise ValueError("groq_models_missing_data")
        return [item for item in data if isinstance(item, dict)]
    except Exception as exc:
        # SDK available but failed (e.g. auth) - re-raise so caller handles
        raise


def _static_catalog() -> list[dict[str, Any]]:
    """Return curated Groq LLM/system models while excluding STT/TTS-only entries."""
    return [dict(item) for item in GROQ_STATIC_MODELS]


def get_groq_catalog(*, force_refresh: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    """Return Groq models with static fallbacks and short dynamic cache."""
    now = time.monotonic()
    if not force_refresh and now - float(_MODEL_CACHE.get("loaded_at") or 0) < GROQ_CATALOG_CACHE_SECONDS:
        return list(_MODEL_CACHE.get("models") or []), _MODEL_CACHE.get("error")

    static_models = _static_catalog()
    if not os.environ.get("GROQ_API_KEY"):
        error = "missing_credentials:GROQ_API_KEY"
        _MODEL_CACHE.update({"loaded_at": now, "models": static_models, "error": error})
        return list(static_models), error

    try:
        mapped_models = []
        for item in _request_models():
            mapped = map_groq_model(item)
            if mapped.get("id") and "text" in mapped.get("outputModalities", []):
                # Always merge static overlay if available (dynamic catalog from Groq often lacks supportsTools etc for special models like gpt-oss-*)
                overlay = _overlay_for(mapped.get("id"))
                if overlay:
                    mapped = _merge_model(mapped, overlay)
                mapped_models.append(mapped)
        known_ids = {item.get("id") for item in mapped_models}
        mapped_models.extend(item for item in static_models if item.get("id") not in known_ids)
        _MODEL_CACHE.update({"loaded_at": now, "models": mapped_models, "error": None})
        return list(mapped_models), None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        error = f"groq_models_http_{exc.code}:{detail[:500]}"
    except Exception as exc:  # noqa: BLE001
        error = f"groq_models_error:{exc}"

    _MODEL_CACHE.update({"loaded_at": now, "models": static_models, "error": error})
    return list(static_models), error


def get_groq_model(model_id: str) -> dict[str, Any] | None:
    """Find a model in the cached/dynamic Groq catalog."""
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    models, _ = get_groq_catalog()
    return next((item for item in models if item.get("id") == wanted), None)
