from __future__ import annotations

import asyncio
import base64
import binascii
import codecs
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

from backend.api.services.unified_history import channel_style_hint
from backend.persona import build_provider_system_prompt
from backend.providers.contracts import ProviderRequest, ProviderResponse
from backend.providers.provider_selector.openrouter.catalog import (
    OPENROUTER_BASE_URL,
    get_openrouter_model,
    openrouter_headers,
)
# Image provider integration: image XML tool instructions for all LLM providers.
from backend.modules.vision.image_provider import normalize_image_provider
from backend.tools.mcp_provider_tools import extract_sources_from_mcp
from backend.providers.provider_selector.openai_compatible import OpenAICompatibleProvider
from backend.providers.provider_selector.openai_compatible.tools_builder import build_tool_schemas_and_runners


logger = logging.getLogger(__name__)

OPENROUTER_CHAT_COMPLETIONS_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_HTTP_TIMEOUT_SECONDS = 300
OPENROUTER_TOOL_ROUNDS = 20
SUPPORTED_TEXT_ATTACHMENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/xml",
}


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter LLM provider using the OpenAI-compatible Chat Completions API."""

    aliases = {"openrouter", "open_router"}
    provider_id = "openrouter"
    provider_label = "OpenRouter"
    api_key_env = "OPENROUTER_API_KEY"
    default_model = "openrouter/auto"
    chat_completions_url = OPENROUTER_CHAT_COMPLETIONS_URL
    http_timeout_seconds = OPENROUTER_HTTP_TIMEOUT_SECONDS
    tool_rounds = OPENROUTER_TOOL_ROUNDS
    supports_plugins = True
    provider_status_title = "OPENROUTER PROVIDER STATUS"

    # ========================================================================
    # Hooks — OpenRouter-specific overrides
    # ========================================================================

    def _capability_hint(self, model_info: dict[str, Any] | None) -> str:
        """OpenRouter capability hint injected into the system prompt."""
        capabilities = self._capabilities_payload(model_info)
        return (
            f"\n\n[{self.provider_status_title}]\n"
            f"You are running through {self.provider_label}, not direct Gemini API.\n"
            "Do not use Gemini Google Search, Gemini Code Execution, Gemini URL Context, or Gemini server-side tools.\n"
            "Only use actual tool calls provided in this request. Never write pseudo calls such as terminal_run(...) as visible text.\n"
            f"Current model capabilities: vision={capabilities['supports_image']}, files={capabilities['supports_pdf']}, tools={capabilities['supports_function_calling']}.\n"
            "When user sends large text (e.g. news, articles) to 'read' or process directly: just acknowledge internally and respond based on content if relevant. Do NOT output image prompts, XML tags, or unrelated generations. Process as normal conversation input."
        )

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Read OpenRouter model metadata from the dynamic catalog."""
        return get_openrouter_model(model_id)

    def _headers(self) -> dict[str, str]:
        """Build OpenRouter request headers without exposing credentials."""
        return openrouter_headers(include_auth=True)

    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Só as chaves realmente lidas: hint de visão/PDF/tools no prompt."""
        return {
            "supports_image": bool(model_info and model_info.get("supportsVision")),
            "supports_pdf": bool(model_info and model_info.get("supportsDocuments")),
            "supports_function_calling": bool(model_info and model_info.get("supportsTools")),
        }

    @staticmethod
    def _provider_routing_payload(routing: dict[str, Any] | None) -> dict[str, Any]:
        """Convert Hana routing config into OpenRouter's request-level provider object."""
        if not isinstance(routing, dict) or not routing:
            return {}
        preferred = str(routing.get("preferredEndpoint") or "").strip().lower()
        allow_fallbacks = bool(routing.get("allowFallbacks", True))
        require_parameters = bool(routing.get("requireParameters", False))
        data_collection = "deny" if routing.get("dataCollection") == "deny" else "allow"
        zdr = bool(routing.get("zdr", False))
        # Preserve OpenRouter's original automatic routing path unless the user
        # explicitly changes at least one routing preference.
        if not preferred and allow_fallbacks and not require_parameters and data_collection == "allow" and not zdr:
            return {}
        payload: dict[str, Any] = {
            "allow_fallbacks": allow_fallbacks,
            "require_parameters": require_parameters,
            "data_collection": data_collection,
            "zdr": zdr,
        }
        if preferred:
            payload["order"] = [preferred]
        return payload

    def _build_payload_base(
        self,
        *,
        model: str,
        temperature: float,
        model_info: dict[str, Any] | None,
        stream: bool,
        tools: list[dict[str, Any]],
        plugins: list[dict[str, Any]] | None = None,
        provider_routing: dict[str, Any] | None = None,
        channel: str = "",
        thinking: bool = True,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        """Build the payload and inject OpenRouter-specific plugins + routing."""
        payload = super()._build_payload_base(
            model=model,
            temperature=temperature,
            model_info=model_info,
            stream=stream,
            tools=tools,
            plugins=plugins,
            provider_routing=provider_routing,
            channel=channel,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )
        routing = self._provider_routing_payload(provider_routing)
        if routing:
            payload["provider"] = routing
        if plugins and self.supports_plugins:
            payload["plugins"] = plugins
        return payload
