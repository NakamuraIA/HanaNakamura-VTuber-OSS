from __future__ import annotations

import logging
from typing import Any

from backend.catalog.repository import LlmModelRepository
from backend.providers.provider_selector.openai_compatible import OpenAICompatibleProvider
from backend.providers.provider_selector.qwen.catalog import (
    QWEN_API_KEY_ENV,
    QWEN_CHAT_COMPLETIONS_URL,
    QWEN_SINGAPORE_API_KEY_ENV,
    normalize_qwen_region,
    qwen_chat_completions_url,
    qwen_headers,
)

logger = logging.getLogger(__name__)


class QwenProvider(OpenAICompatibleProvider):
    """Alibaba Cloud Model Studio (Qwen) via its OpenAI-compatible API.

    Reuses the whole OpenAI-compatible path (generate, generate_stream,
    tool loop) — only the endpoint, key and catalog differ. So token streaming and
    function calling work out of the box.
    """

    aliases = {"qwen", "alibaba", "dashscope", "model_studio", "modelstudio"}
    provider_id = "qwen"
    provider_label = "Qwen"
    api_key_env = QWEN_API_KEY_ENV
    default_model = "qwen-plus"
    chat_completions_url = QWEN_CHAT_COMPLETIONS_URL
    http_timeout_seconds = 120
    tool_rounds = 20
    supports_plugins = False
    provider_status_title = "QWEN PROVIDER STATUS"

    def __init__(self, model_repository: LlmModelRepository | None = None) -> None:
        """Recebe o catálogo; durante a migração usa o repositório padrão da Hana."""
        self.model_repository = model_repository or LlmModelRepository()

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Lê o modelo do catálogo (SQLite). Sem catálogo legado: migrado 2026-08-04."""
        try:
            return self.model_repository.get_model(self.provider_id, model_id)
        except Exception:
            logger.warning(
                "[Qwen] catálogo indisponível para '%s'.", model_id, exc_info=True,
            )
            return None

    def _headers(self) -> dict[str, str]:
        """Build Qwen request headers without exposing credentials."""
        return qwen_headers(include_auth=True)

    @staticmethod
    def _selected_region(memory: Any | None) -> str:
        try:
            config = memory.get_setting("llm_config", {}) if memory is not None else {}
        except Exception:
            config = {}
        return normalize_qwen_region(config.get("qwenRegion") if isinstance(config, dict) else None)

    def _request_url(self, memory: Any | None = None) -> str:
        region = self._selected_region(memory)
        return qwen_chat_completions_url(region)

    def _request_headers(self, memory: Any | None = None) -> dict[str, str]:
        return qwen_headers(include_auth=True, region=self._selected_region(memory))

    def _api_key(self, memory: Any | None = None) -> str | None:
        import os
        if self._selected_region(memory) == "singapore":
            return os.environ.get(QWEN_SINGAPORE_API_KEY_ENV)
        return os.environ.get(QWEN_API_KEY_ENV) or os.environ.get("DASHSCOPE_API_KEY")

    def _credentials_available(self, memory: Any | None = None) -> bool:
        """Use the key selected by the persisted Qwen region."""
        if self._selected_region(memory) == "singapore":
            return bool(self._api_key(memory)) and bool(self._request_url(memory))
        return bool(self._api_key(memory))

    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Só as chaves realmente lidas: hint de visão/PDF/tools no prompt.

        Antes ``supports_image`` era fixo ``False`` por provider, o que
        mentia sobre o qwen3.6-flash e o qwen3.7-flash (aceitam vídeo/imagem).
        Agora vem do catálogo.
        """
        info = model_info if isinstance(model_info, dict) else {}
        input_modalities = info.get("inputModalities") or []
        return {
            "supports_image": bool(info.get("supportsVision") or "image" in input_modalities),
            "supports_pdf": bool(info.get("supportsDocuments") or "pdf" in input_modalities),
            "supports_function_calling": bool(info.get("supportsTools")),
        }
