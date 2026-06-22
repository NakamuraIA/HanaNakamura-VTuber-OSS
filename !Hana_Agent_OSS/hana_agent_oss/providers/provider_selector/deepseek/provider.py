from __future__ import annotations

from typing import Any

from hana_agent_oss.providers.provider_selector.deepseek.catalog import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_CHAT_COMPLETIONS_URL,
    deepseek_headers,
    get_deepseek_model,
)
from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider


class DeepSeekProvider(OpenRouterProvider):
    """DeepSeek (official, api.deepseek.com) via its OpenAI-compatible API.

    Reuses the whole OpenRouter OpenAI-compatible path (generate, generate_stream,
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

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Read DeepSeek model metadata from the static catalog."""
        return get_deepseek_model(model_id)

    def _headers(self) -> dict[str, str]:
        """Build DeepSeek request headers without exposing credentials."""
        return deepseek_headers(include_auth=True)

    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Expose DeepSeek model capabilities using the selector capability keys."""
        supported_parameters = model_info.get("supportedParameters") if isinstance(model_info, dict) else []
        return {
            "multimodal_input": False,
            "supports_image": False,
            "supports_audio": False,
            "supports_video": False,
            "supports_pdf": False,
            "supports_native_web_search": False,
            "supports_streaming": True,
            "supports_structured_output": bool(model_info and "response_format" in supported_parameters),
            "supports_function_calling": bool(model_info and model_info.get("supportsTools")),
            "supports_code_execution": False,
            "supports_image_generation": False,
            "supports_video_generation": False,
            "supports_tts": False,
            "supports_live_voice": False,
            "supports_memory_embeddings": False,
            "supports_rag": False,
        }
