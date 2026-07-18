from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"
OPENROUTER_CATALOG_CACHE_SECONDS = 300
OPENROUTER_ENDPOINT_CACHE_SECONDS = 300

# OpenRouter's endpoints API returns short internal codenames for some providers
# (e.g. "WandB") instead of the display name shown on openrouter.ai. Prettify the
# ones that would otherwise be hard to recognize/search for in the picker.
OPENROUTER_PROVIDER_DISPLAY_NAMES = {
    "wandb": "Weights & Biases",
}

_MODEL_CACHE: dict[str, Any] = {"loaded_at": 0.0, "models": [], "error": None}
_ENDPOINT_CACHE: dict[str, dict[str, Any]] = {}


def openrouter_headers(*, include_auth: bool = True) -> dict[str, str]:
    """Build OpenRouter headers without leaking credentials into logs."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if include_auth and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    site_url = os.environ.get("OPENROUTER_SITE_URL")
    app_name = os.environ.get("OPENROUTER_APP_NAME") or "Hana Agent OSS"
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-OpenRouter-Title"] = app_name
    return headers


def _string_list(value: Any) -> list[str]:
    """Normalize OpenRouter array fields into lowercase strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower() for item in value if str(item).strip()]


def _number_or_none(value: Any) -> int | None:
    """Convert catalog token limits without failing on null or non-numeric fields."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _price_is_zero(value: Any) -> bool:
    """Return true when OpenRouter pricing field is numeric zero."""
    try:
        return float(str(value)) == 0.0
    except (TypeError, ValueError):
        return False


def map_openrouter_model(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one OpenRouter model record into the Control Center catalog shape."""
    architecture = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
    top_provider = raw.get("top_provider") if isinstance(raw.get("top_provider"), dict) else {}
    pricing = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}
    input_modalities = _string_list(architecture.get("input_modalities"))
    output_modalities = _string_list(architecture.get("output_modalities"))
    supported_parameters = _string_list(raw.get("supported_parameters"))
    model_id = str(raw.get("id") or "").strip()
    prompt_price = pricing.get("prompt")
    completion_price = pricing.get("completion")
    is_free = model_id.endswith(":free") or (
        _price_is_zero(prompt_price) and _price_is_zero(completion_price)
    )

    return {
        "id": model_id,
        "label": str(raw.get("name") or model_id),
        "provider": "openrouter",
        "supportsVision": "image" in input_modalities,
        "supportsDocuments": "file" in input_modalities,
        "supportsTools": "tools" in supported_parameters or "tool_choice" in supported_parameters,
        "supportsNativeSearch": False,
        "inputModalities": input_modalities or ["text"],
        "outputModalities": output_modalities or ["text"],
        "supportedParameters": supported_parameters,
        "maxInputTokens": _number_or_none(raw.get("context_length") or top_provider.get("context_length")),
        "maxOutputTokens": _number_or_none(top_provider.get("max_completion_tokens")),
        "pricing": pricing,
        "free": is_free,
        "description": str(raw.get("description") or ""),
    }


def _request_models(timeout_seconds: float = 8.0) -> list[dict[str, Any]]:
    """Fetch OpenRouter models (both text and image) through the documented Models API."""
    headers = openrouter_headers(include_auth=True)
    
    # 1. Fetch text models (default)
    text_data = []
    try:
        request_text = urllib.request.Request(
            OPENROUTER_MODELS_URL,
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(request_text, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        body = json.loads(raw_body) if raw_body else {}
        text_data = body.get("data") or []
    except Exception as exc:
        logger.warning("[OPENROUTER CATALOG] Failed to fetch text models: %s", exc)

    # 2. Fetch image models specifically
    image_data = []
    try:
        request_image = urllib.request.Request(
            f"{OPENROUTER_MODELS_URL}?output_modalities=image",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(request_image, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        body = json.loads(raw_body) if raw_body else {}
        image_data = body.get("data") or []
    except Exception as exc:
        logger.warning("[OPENROUTER CATALOG] Failed to fetch image models: %s", exc)

    if not isinstance(text_data, list) and not isinstance(image_data, list):
        raise ValueError("openrouter_models_missing_data")

    # Merge and deduplicate by model ID
    merged: dict[str, dict[str, Any]] = {}
    if isinstance(text_data, list):
        for item in text_data:
            if isinstance(item, dict) and item.get("id"):
                merged[item["id"]] = item

    if isinstance(image_data, list):
        for item in image_data:
            if isinstance(item, dict) and item.get("id"):
                merged[item["id"]] = item

    if not merged:
        raise ValueError("openrouter_models_empty_catalog")

    return list(merged.values())


def get_openrouter_catalog(*, force_refresh: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    """Return mapped OpenRouter models with a short in-process cache."""
    now = time.monotonic()
    if not force_refresh and now - float(_MODEL_CACHE.get("loaded_at") or 0) < OPENROUTER_CATALOG_CACHE_SECONDS:
        return list(_MODEL_CACHE.get("models") or []), _MODEL_CACHE.get("error")

    try:
        models = []
        for item in _request_models():
            mapped = map_openrouter_model(item)
            if mapped["id"] and ("text" in mapped.get("outputModalities", []) or "image" in mapped.get("outputModalities", [])):
                models.append(mapped)
        _MODEL_CACHE.update({"loaded_at": now, "models": models, "error": None})
        return list(models), None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        error = f"openrouter_models_http_{exc.code}:{detail[:500]}"
    except Exception as exc:  # noqa: BLE001
        error = f"openrouter_models_error:{exc}"

    _MODEL_CACHE.update({"loaded_at": now, "models": [], "error": error})
    return [], error


def get_openrouter_model(model_id: str) -> dict[str, Any] | None:
    """Find a model in the cached/dynamic OpenRouter catalog."""
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    models, _ = get_openrouter_catalog()
    return next((item for item in models if item.get("id") == wanted), None)


def _map_openrouter_endpoint(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one OpenRouter model endpoint into the Control Center contract."""
    pricing = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}
    raw_provider_name = str(raw.get("provider_name") or raw.get("name") or "").strip()
    provider_name = OPENROUTER_PROVIDER_DISPLAY_NAMES.get(raw_provider_name.lower(), raw_provider_name)
    return {
        "name": str(raw.get("name") or "").strip() or provider_name,
        "slug": str(raw.get("tag") or raw.get("provider_name") or "").strip().lower(),
        "providerName": provider_name,
        "status": str(raw.get("status") or "unknown").strip().lower(),
        "pricing": pricing,
        "contextLength": _number_or_none(raw.get("context_length")),
        "maxPromptTokens": _number_or_none(raw.get("max_prompt_tokens")),
        "maxCompletionTokens": _number_or_none(raw.get("max_completion_tokens")),
        "quantization": str(raw.get("quantization") or "").strip(),
        "supportedParameters": _string_list(raw.get("supported_parameters")),
        "uptimeLast30m": raw.get("uptime_last_30m"),
        "latencyLast30m": raw.get("latency_last_30m"),
        "throughputLast30m": raw.get("throughput_last_30m"),
    }


def get_openrouter_endpoints(model_id: str, *, force_refresh: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch and cache the provider endpoints available for one OpenRouter model."""
    wanted = str(model_id or "").strip().strip("/")
    if "/" not in wanted:
        return [], "openrouter_endpoint_invalid_model"
    now = time.monotonic()
    cached = _ENDPOINT_CACHE.get(wanted)
    if cached and not force_refresh and now - float(cached.get("loaded_at") or 0) < OPENROUTER_ENDPOINT_CACHE_SECONDS:
        return list(cached.get("endpoints") or []), cached.get("error")

    try:
        request = urllib.request.Request(
            f"{OPENROUTER_MODELS_URL}/{wanted}/endpoints",
            headers=openrouter_headers(include_auth=True),
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=8.0) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        body = json.loads(raw_body) if raw_body else {}
        data = body.get("data") if isinstance(body, dict) else {}
        raw_endpoints = data.get("endpoints") if isinstance(data, dict) else []
        endpoints = [_map_openrouter_endpoint(item) for item in raw_endpoints if isinstance(item, dict)]
        endpoints = [item for item in endpoints if item["slug"]]
        _ENDPOINT_CACHE[wanted] = {"loaded_at": now, "endpoints": endpoints, "error": None}
        return endpoints, None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        error = f"openrouter_endpoints_http_{exc.code}:{detail[:500]}"
    except Exception as exc:  # noqa: BLE001
        error = f"openrouter_endpoints_error:{exc}"
    _ENDPOINT_CACHE[wanted] = {"loaded_at": now, "endpoints": [], "error": error}
    return [], error
