from __future__ import annotations

from typing import Any

from hana_agent_oss.providers.provider_selector.openai_compatible import OpenAICompatibleProvider
from hana_agent_oss.providers.provider_selector.qwen.catalog import (
    QWEN_API_KEY_ENV,
    QWEN_CHAT_COMPLETIONS_URL,
    get_qwen_model,
    qwen_headers,
)


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

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Read Qwen model metadata from the static catalog."""
        return get_qwen_model(model_id)

    def _headers(self) -> dict[str, str]:
        """Build Qwen request headers without exposing credentials."""
        return qwen_headers(include_auth=True)

    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Expose Qwen model capabilities using the selector capability keys."""
        supported_parameters = model_info.get("supportedParameters") if isinstance(model_info, dict) else []
        supports_vision = bool(model_info and model_info.get("supportsVision"))
        return {
            "multimodal_input": supports_vision,
            "supports_image": supports_vision,
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
