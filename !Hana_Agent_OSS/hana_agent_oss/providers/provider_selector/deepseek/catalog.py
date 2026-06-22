"""DeepSeek (official, api.deepseek.com) model catalog.

DeepSeek's API is OpenAI-compatible, so the provider reuses the OpenRouter
OpenAI-compatible code path. Only a couple of models exist, so the catalog is
static (no dynamic fetch needed) — robust and offline-friendly.

Pricing is stored PER TOKEN (same unit OpenRouter uses) so the Control Panel's
"× 1M" formatter renders it correctly as $/M.
"""

from __future__ import annotations

import os
from typing import Any

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_CHAT_COMPLETIONS_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"


# Modelos atuais (api-docs.deepseek.com). deepseek-chat/deepseek-reasoner sao
# legados (deprecam 2026/07/24) e apontam pro v4-flash; usamos os nomes atuais.
DEEPSEEK_STATIC_MODELS: list[dict[str, Any]] = [
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "provider": "deepseek",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice", "response_format"],
        "maxInputTokens": 1_000_000,
        "maxOutputTokens": 384_000,
        # per-token (cache-miss): $0.14/M in, $0.28/M out
        "pricing": {"prompt": "0.00000014", "completion": "0.00000028"},
        "description": "DeepSeek-V4-Flash, OpenAI-compatible, 1M de contexto, com function calling e JSON.",
    },
    {
        "id": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "provider": "deepseek",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice", "response_format"],
        "maxInputTokens": 1_000_000,
        "maxOutputTokens": 384_000,
        # per-token (cache-miss): $0.435/M in, $0.87/M out
        "pricing": {"prompt": "0.000000435", "completion": "0.00000087"},
        "description": "DeepSeek-V4-Pro, mais forte que o Flash, 1M de contexto, function calling e JSON.",
    },
]


def deepseek_headers(*, include_auth: bool = True) -> dict[str, str]:
    """Build DeepSeek API headers without exposing the key in logs."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = os.environ.get(DEEPSEEK_API_KEY_ENV)
    if include_auth and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def get_deepseek_catalog(*, force_refresh: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    """Return DeepSeek models (static) and an error string when the key is missing."""
    models = [dict(item) for item in DEEPSEEK_STATIC_MODELS]
    if not os.environ.get(DEEPSEEK_API_KEY_ENV):
        return models, f"missing_credentials:{DEEPSEEK_API_KEY_ENV}"
    return models, None


def get_deepseek_model(model_id: str) -> dict[str, Any] | None:
    """Find a DeepSeek model by id."""
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    return next((dict(item) for item in DEEPSEEK_STATIC_MODELS if item.get("id") == wanted), None)
