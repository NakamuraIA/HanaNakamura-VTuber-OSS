"""Groq — conexão com a API.

Regra de pastas (``docs/REGRA_PASTAS.md``): este arquivo só FALA com a API —
URL, chave, cabeçalho. Catálogo de modelo mora em ``llm_models``
(``backend/bd/llm.py``), lido via ``LlmModelRepository``. Migrado em
2026-08-04 (ver ``DECISOES_ARQUITETURA_CATALOGO.md``, "Critério de sucesso").
"""

from __future__ import annotations

import os

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_CHAT_COMPLETIONS_URL = f"{GROQ_BASE_URL}/chat/completions"
GROQ_API_KEY_ENV = "GROQ_API_KEY"


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
