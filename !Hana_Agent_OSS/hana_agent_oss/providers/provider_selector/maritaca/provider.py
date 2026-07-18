from __future__ import annotations

from typing import Any

from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider
from hana_agent_oss.providers.provider_selector.maritaca.catalog import (
    MARITACA_API_KEY_ENV,
    MARITACA_CHAT_COMPLETIONS_URL,
    get_maritaca_model,
    maritaca_headers,
)


class MaritacaProvider(OpenRouterProvider):
    """Maritaca AI (Sabia) via seu endpoint OpenAI-compativel.

    Reusa todo o caminho OpenAI-compativel do OpenRouter (generate,
    generate_stream, tool loop) -- so o endpoint, a chave e o catalogo
    diferem. Streaming e function calling funcionam de fabrica.
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

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Read Maritaca model metadata from the static catalog."""
        return get_maritaca_model(model_id)

    def _headers(self) -> dict[str, str]:
        """Build Maritaca request headers without exposing credentials."""
        return maritaca_headers(include_auth=True)

    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Expose Maritaca model capabilities using the selector capability keys."""
        return {
            "multimodal_input": False,
            "supports_image": False,
            "supports_audio": False,
            "supports_video": False,
            "supports_pdf": False,
            "supports_native_web_search": False,
            "supports_streaming": True,
            "supports_structured_output": False,
            "supports_function_calling": bool(model_info and model_info.get("supportsTools")),
            "supports_code_execution": False,
            "supports_image_generation": False,
            "supports_video_generation": False,
            "supports_tts": False,
            "supports_live_voice": False,
            "supports_memory_embeddings": False,
            "supports_rag": False,
        }
