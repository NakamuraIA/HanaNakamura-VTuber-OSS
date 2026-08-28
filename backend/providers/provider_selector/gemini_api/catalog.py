"""Gemini (Google AI Studio) — conexão com a API.

Regra de pastas (``docs/REGRA_PASTAS.md``): este arquivo só FALA com a API —
URL, chave, cabeçalho. Catálogo de modelo mora em ``llm_models``
(``backend/bd/llm.py``), lido via ``LlmModelRepository``. Migrado em
2026-08-04 (ver ``DECISOES_ARQUITETURA_CATALOGO.md``, "Critério de sucesso").
"""

from __future__ import annotations

import os

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_API_KEY_ENV = "GOOGLE_API_KEY"
GEMINI_FALLBACK_KEY_ENV = "GEMINI_API_KEY"


def gemini_headers(*, include_auth: bool = True) -> dict[str, str]:
    """Build Gemini API headers without exposing the key in logs."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = os.environ.get(GEMINI_API_KEY_ENV) or os.environ.get(GEMINI_FALLBACK_KEY_ENV)
    if include_auth and api_key:
        headers["x-goog-api-key"] = api_key
    return headers