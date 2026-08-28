from __future__ import annotations

import logging
from typing import Any

from backend.catalog.repository import LlmModelRepository
from backend.providers.provider_selector.deepseek.catalog import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_CHAT_COMPLETIONS_URL,
    deepseek_headers,
)
from backend.providers.provider_selector.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek (official, api.deepseek.com) via its OpenAI-compatible API.

    Reuses the whole OpenAI-compatible path (generate, generate_stream,
    tool loop) — only the endpoint, key and catalog differ. So token streaming and
    function calling work out of the box.
    """

    aliases = {"deepseek", "deepseek_official", "deep_seek"}
    provider_id = "deepseek"
    provider_label = "DeepSeek"
    api_key_env = DEEPSEEK_API_KEY_ENV
    default_model = "deepseek-v4-flash"
    chat_completions_url = DEEPSEEK_CHAT_COMPLETIONS_URL
    http_timeout_seconds = 120
    tool_rounds = 20
    supports_plugins = False
    provider_status_title = "DEEPSEEK PROVIDER STATUS"

    def __init__(self, model_repository: LlmModelRepository | None = None) -> None:
        """Recebe o catálogo; durante a migração usa o repositório padrão da Hana."""
        self.model_repository = model_repository or LlmModelRepository()

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Lê o modelo do catálogo (SQLite). Sem catálogo legado: migrado 2026-08-04."""
        try:
            return self.model_repository.get_model(self.provider_id, model_id)
        except Exception:
            logger.warning(
                "[DeepSeek] catálogo indisponível para '%s'.", model_id, exc_info=True,
            )
            return None

    def _headers(self) -> dict[str, str]:
        """Build DeepSeek request headers without exposing credentials."""
        return deepseek_headers(include_auth=True)

    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Só as chaves realmente lidas: hint de visão/PDF/tools no prompt."""
        info = model_info if isinstance(model_info, dict) else {}
        input_modalities = info.get("inputModalities") or []
        return {
            "supports_image": bool(info.get("supportsVision") or "image" in input_modalities),
            "supports_pdf": bool(info.get("supportsDocuments") or "pdf" in input_modalities),
            "supports_function_calling": bool(info.get("supportsTools")),
        }
