"""Maritaca AI (Sabia) model catalog.

Maritaca expoe um endpoint OpenAI-compativel, entao o provider reusa o
codigo OpenAI-compatible do OpenRouter. So um punhado de modelos existe,
entao o catalogo e estatico (sem fetch dinamico) -- robusto e offline-friendly.

ATENCAO: a Maritaca cobra em REAIS (R$), nao em dolares. O restante do
catalogo (OpenRouter/Qwen/DeepSeek) guarda preco por token assumindo USD
para o formatador "$/M" do Control Panel -- os valores aqui sao o mesmo
formato (por token), mas representam R$, entao o rotulo com "$" no painel
fica tecnicamente errado (mostra o numero certo, moeda errada).
"""

from __future__ import annotations

import os
from typing import Any

MARITACA_BASE_URL = "https://chat.maritaca.ai/api"
MARITACA_CHAT_COMPLETIONS_URL = f"{MARITACA_BASE_URL}/chat/completions"
MARITACA_API_KEY_ENV = "MARITACA_API_KEY"


MARITACA_STATIC_MODELS: list[dict[str, Any]] = [
    {
        "id": "sabia-4",
        "label": "Sabia 4",
        "provider": "maritaca",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice"],
        "maxInputTokens": 128_000,
        "maxOutputTokens": 32_000,
        # por token, em R$: in R$5/M, out R$20/M
        "pricing": {"prompt": "0.000005", "completion": "0.00002"},
        "description": "Generalista foco em portugues/BR, boa capacidade agentica (tools). Preco em R$.",
    },
    {
        "id": "sabia-4-thinking",
        "label": "Sabia 4 Thinking",
        "provider": "maritaca",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice"],
        "maxInputTokens": 128_000,
        "maxOutputTokens": 32_000,
        # por token, em R$: in R$5/M, out R$40/M
        "pricing": {"prompt": "0.000005", "completion": "0.00004"},
        "description": "Modelo de raciocinio dedicado (sempre pensa, sem toggle). Melhor p/ tarefas complexas. Preco em R$.",
    },
    {
        "id": "sabiazinho-4",
        "label": "Sabiazinho 4",
        "provider": "maritaca",
        "supportsVision": False,
        "supportsDocuments": False,
        "supportsTools": True,
        "supportsNativeSearch": False,
        "inputModalities": ["text"],
        "outputModalities": ["text"],
        "supportedParameters": ["tools", "tool_choice"],
        "maxInputTokens": 128_000,
        "maxOutputTokens": 32_000,
        # por token, em R$: in R$1/M, out R$4/M
        "pricing": {"prompt": "0.000001", "completion": "0.000004"},
        "description": "Rapido e barato, otimizado pra escala. Boa opcao padrao de baixo custo. Preco em R$.",
    },
]


def maritaca_headers(*, include_auth: bool = True) -> dict[str, str]:
    """Build Maritaca API headers without exposing the key in logs."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = os.environ.get(MARITACA_API_KEY_ENV)
    if include_auth and api_key:
        # Maritaca usa o esquema "Key", nao "Bearer" como as demais APIs OpenAI-compativeis.
        headers["Authorization"] = f"Key {api_key}"
    return headers


def get_maritaca_catalog(*, force_refresh: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    """Return Maritaca models (static) and an error string when the key is missing."""
    models = [dict(item) for item in MARITACA_STATIC_MODELS]
    if not os.environ.get(MARITACA_API_KEY_ENV):
        return models, f"missing_credentials:{MARITACA_API_KEY_ENV}"
    return models, None


def get_maritaca_model(model_id: str) -> dict[str, Any] | None:
    """Find a Maritaca model by id."""
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    return next((dict(item) for item in MARITACA_STATIC_MODELS if item.get("id") == wanted), None)
