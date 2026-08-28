"""Maritaca AI (Sabia) — conexão com a API.

Regra de pastas (``docs/REGRA_PASTAS.md``): este arquivo só FALA com a API —
URL, chave, cabeçalho. Catálogo de modelo mora em ``llm_models``
(``backend/bd/llm.py``), lido via ``LlmModelRepository``. Migrado em
2026-08-04 (ver ``DECISOES_ARQUITETURA_CATALOGO.md``, "Critério de sucesso").

ATENCAO: a Maritaca cobra em REAIS (R$), nao em dolares. O preco guardado no
banco esta no mesmo formato por token dos demais providers, mas representa
R$, entao o rotulo com "$" no painel fica tecnicamente errado (numero certo,
moeda errada).
"""

from __future__ import annotations

import os

MARITACA_BASE_URL = "https://chat.maritaca.ai/api"
MARITACA_CHAT_COMPLETIONS_URL = f"{MARITACA_BASE_URL}/chat/completions"
MARITACA_API_KEY_ENV = "MARITACA_API_KEY"


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
