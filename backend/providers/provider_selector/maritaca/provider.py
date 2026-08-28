from __future__ import annotations

import logging
from typing import Any

from backend.catalog.repository import LlmModelRepository
from backend.providers.provider_selector.openai_compatible import OpenAICompatibleProvider
from backend.providers.provider_selector.maritaca.catalog import (
    MARITACA_API_KEY_ENV,
    MARITACA_CHAT_COMPLETIONS_URL,
    maritaca_headers,
)

logger = logging.getLogger(__name__)


class MaritacaProvider(OpenAICompatibleProvider):
    """Maritaca AI (Sabia) via seu endpoint OpenAI-compativel.

    Herda direto da BASE OpenAI-compativel (nao do OpenRouter) -- Maritaca nao
    usa provider-routing nem plugins do OpenRouter. So o endpoint, a chave e o
    catalogo diferem; streaming, tool loop e o controle de pensar (base) vem de
    graca. Sabia-4 nao e modelo de reasoning, entao nenhum knob de pensar e
    enviado.
    """

    aliases = {"maritaca", "sabia", "sabiá"}
    provider_id = "maritaca"
    provider_label = "Maritaca AI (Sabia)"
    api_key_env = MARITACA_API_KEY_ENV
    default_model = "sabia-4"
    chat_completions_url = MARITACA_CHAT_COMPLETIONS_URL
    http_timeout_seconds = 120
    tool_rounds = 20
    supports_plugins = False
    provider_status_title = "MARITACA PROVIDER STATUS"

    def __init__(self, model_repository: LlmModelRepository | None = None) -> None:
        """Recebe o catálogo; durante a migração usa o repositório padrão da Hana."""
        self.model_repository = model_repository or LlmModelRepository()

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Lê o modelo do catálogo (SQLite). Sem catálogo legado: migrado 2026-08-04."""
        try:
            return self.model_repository.get_model(self.provider_id, model_id)
        except Exception:
            logger.warning(
                "[Maritaca] catálogo indisponível para '%s'.", model_id, exc_info=True,
            )
            return None

    def _headers(self) -> dict[str, str]:
        """Build Maritaca request headers without exposing credentials."""
        return maritaca_headers(include_auth=True)

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
