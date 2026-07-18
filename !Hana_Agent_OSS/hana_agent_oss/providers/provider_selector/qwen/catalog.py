"""Alibaba Cloud Model Studio (Qwen/DashScope) model catalog.

Model Studio exposes an OpenAI-compatible endpoint, so the provider reuses the
OpenRouter OpenAI-compatible code path. Only a handful of chat models exist, so
the catalog is static (no dynamic fetch needed) — robust and offline-friendly.

Pricing is stored PER TOKEN (same unit OpenRouter uses) so the Control Panel's
"× 1M" formatter renders it correctly as $/M.
"""

from __future__ import annotations

import os
from typing import Any

# Regiao Virginia (US) e a unica com dominio fixo; as demais usam {WorkspaceId}.
QWEN_BASE_URL = "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
QWEN_CHAT_COMPLETIONS_URL = f"{QWEN_BASE_URL}/chat/completions"
QWEN_API_KEY_ENV = "QWEN_API_KEY"


QWEN_STATIC_MODELS: list[dict[str, Any]] = [
    # --- Aliases genericos (sempre apontam pro snapshot mais recente da linha) --- #
    {
        "id": "qwen-plus",
        "label": "Qwen Plus (alias mais recente)",
        "provider": "qwen",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice", "response_format"],
        "maxInputTokens": 1_000_000,
        "maxOutputTokens": 32_768,
        # per-token: $0.4/M in, $1.2/M out (tabela publica Model Studio)
        "pricing": {"prompt": "0.0000004", "completion": "0.0000012"},
        "description": "Alias que sempre aponta pro Qwen-Plus mais recente. Prefira qwen3.7-plus para pinar a versao.",
    },
    {
        "id": "qwen-turbo",
        "label": "Qwen Turbo (descontinuado)",
        "provider": "qwen",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice", "response_format"],
        "maxInputTokens": 1_000_000,
        "maxOutputTokens": 16_384,
        # per-token: $0.05/M in, $0.2/M out
        "pricing": {"prompt": "0.00000005", "completion": "0.0000002"},
        "description": "Qwen-Turbo nao recebe mais atualizacoes; a Alibaba recomenda migrar para qwen3.5-flash.",
    },
    {
        "id": "qwen-max",
        "label": "Qwen Max (alias mais recente)",
        "provider": "qwen",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice", "response_format"],
        "maxInputTokens": 262_144,
        "maxOutputTokens": 32_768,
        # per-token: $1.6/M in, $6.4/M out
        "pricing": {"prompt": "0.0000016", "completion": "0.0000064"},
        "description": "Alias que sempre aponta pro Qwen-Max mais recente. Prefira qwen3.7-max para pinar a versao.",
    },
    # --- Linha versionada (vigente, com suporte a visao) ------------------------ #
    {
        "id": "qwen3.5-flash",
        "label": "Qwen3.5 Flash (visao)",
        "provider": "qwen",
        "supportsVision": True,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text", "image"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice", "response_format"],
        "maxInputTokens": 1_000_000,
        "maxOutputTokens": 32_768,
        # per-token: $0.065/M in, $0.26/M out
        "pricing": {"prompt": "0.000000065", "completion": "0.00000026"},
        "description": "Substituto do Qwen-Turbo: rapido, barato, com visao (imagem) e function calling.",
    },
    {
        "id": "qwen3.7-plus",
        "label": "Qwen3.7 Plus (visao)",
        "provider": "qwen",
        "supportsVision": True,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text", "image"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice", "response_format"],
        "maxInputTokens": 1_000_000,
        "maxOutputTokens": 32_768,
        # per-token: $0.32/M in, $1.28/M out
        "pricing": {"prompt": "0.00000032", "completion": "0.00000128"},
        "description": "Generalista multimodal equilibrado: texto + imagem + video, 1M de contexto, function calling.",
    },
    {
        "id": "qwen3.7-max",
        "label": "Qwen3.7 Max",
        "provider": "qwen",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice", "response_format"],
        "maxInputTokens": 262_144,
        "maxOutputTokens": 32_768,
        # per-token: $1.25/M in, $3.75/M out
        "pricing": {"prompt": "0.00000125", "completion": "0.00000375"},
        "description": "O mais forte da linha comercial Qwen (texto). Sem visao nesta versao (so texto).",
    },
]


def qwen_headers(*, include_auth: bool = True) -> dict[str, str]:
    """Build Qwen/Model Studio API headers without exposing the key in logs."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = os.environ.get(QWEN_API_KEY_ENV) or os.environ.get("DASHSCOPE_API_KEY")
    if include_auth and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def get_qwen_catalog(*, force_refresh: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    """Return Qwen models (static) and an error string when the key is missing."""
    models = [dict(item) for item in QWEN_STATIC_MODELS]
    if not (os.environ.get(QWEN_API_KEY_ENV) or os.environ.get("DASHSCOPE_API_KEY")):
        return models, f"missing_credentials:{QWEN_API_KEY_ENV}"
    return models, None


def get_qwen_model(model_id: str) -> dict[str, Any] | None:
    """Find a Qwen model by id."""
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    return next((dict(item) for item in QWEN_STATIC_MODELS if item.get("id") == wanted), None)
