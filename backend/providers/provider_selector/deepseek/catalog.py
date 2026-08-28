"""DeepSeek (official, api.deepseek.com) — conexão com a API.

Regra de pastas (``docs/REGRA_PASTAS.md``): este arquivo só FALA com a API —
URL, chave, cabeçalho. Catálogo de modelo mora em ``llm_models``
(``backend/bd/llm.py``), lido via ``LlmModelRepository``. Migrado em
2026-08-04 (ver ``DECISOES_ARQUITETURA_CATALOGO.md``, "Critério de sucesso").
"""

from __future__ import annotations

import os

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_CHAT_COMPLETIONS_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"


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
