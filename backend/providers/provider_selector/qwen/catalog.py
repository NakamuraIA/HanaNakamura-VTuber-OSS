"""Alibaba Cloud Model Studio (Qwen/DashScope) — conexão com a API.

Regra de pastas (``docs/REGRA_PASTAS.md``): este arquivo só FALA com a API —
URL, chave, cabeçalho. Catálogo de modelo mora em ``llm_models``
(``backend/bd/llm.py``), lido via ``LlmModelRepository``. Migrado em
2026-08-04 (ver ``DECISOES_ARQUITETURA_CATALOGO.md``, "Critério de sucesso").
"""

from __future__ import annotations

import os

# A Virginia tem dominio fixo. Em Singapura o Model Studio usa o endpoint do
# workspace, guardado no ambiente para nunca deixar um workspace pessoal no codigo.
QWEN_BASE_URL = "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
QWEN_CHAT_COMPLETIONS_URL = f"{QWEN_BASE_URL}/chat/completions"
QWEN_API_KEY_ENV = "QWEN_API_KEY"
QWEN_SINGAPORE_API_KEY_ENV = "QWEN_SINGAPORE_API_KEY"
QWEN_SINGAPORE_BASE_URL_ENV = "QWEN_SINGAPORE_BASE_URL"
QWEN_REGIONS = {"virginia", "singapore"}


def normalize_qwen_region(value: object) -> str:
    """Return a supported Model Studio region, preserving Virginia by default."""
    region = str(value or "").strip().lower()
    return region if region in QWEN_REGIONS else "virginia"


def qwen_base_url(region: object = "virginia") -> str:
    """Resolve the OpenAI-compatible base URL without exposing credentials."""
    if normalize_qwen_region(region) == "singapore":
        return os.environ.get(QWEN_SINGAPORE_BASE_URL_ENV, "").strip().rstrip("/")
    return QWEN_BASE_URL


def qwen_chat_completions_url(region: object = "virginia") -> str:
    base_url = qwen_base_url(region)
    return f"{base_url}/chat/completions" if base_url else ""


def qwen_headers(*, include_auth: bool = True, region: object = "virginia") -> dict[str, str]:
    """Build Qwen/Model Studio API headers without exposing the key in logs."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if normalize_qwen_region(region) == "singapore":
        api_key = os.environ.get(QWEN_SINGAPORE_API_KEY_ENV)
    else:
        api_key = os.environ.get(QWEN_API_KEY_ENV) or os.environ.get("DASHSCOPE_API_KEY")
    if include_auth and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers
