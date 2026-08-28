from __future__ import annotations

import logging
import os
from typing import Any

from backend.catalog.repository import LlmModelRepository
from backend.providers.provider_selector.groq.catalog import (
    GROQ_CHAT_COMPLETIONS_URL,
    groq_headers,
)
from backend.providers.provider_selector.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class GroqProvider(OpenAICompatibleProvider):
    """Groq LLM provider using Groq's OpenAI-compatible Chat Completions API."""

    aliases = {"groq", "groqcloud", "groq_cloud", "glock"}
    provider_id = "groq"
    provider_label = "Groq"
    api_key_env = "GROQ_API_KEY"
    default_model = "llama-3.3-70b-versatile"
    chat_completions_url = GROQ_CHAT_COMPLETIONS_URL
    http_timeout_seconds = 120
    tool_rounds = 20
    supports_plugins = False
    provider_status_title = "GROQ PROVIDER STATUS"

    def __init__(self, model_repository: LlmModelRepository | None = None) -> None:
        """Recebe o catálogo; durante a migração usa o repositório padrão da Hana."""
        self.model_repository = model_repository or LlmModelRepository()

    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Só as chaves realmente lidas: hint de visão/PDF/tools no prompt."""
        return {
            "supports_image": bool(model_info and model_info.get("supportsVision")),
            "supports_pdf": False,
            "supports_function_calling": bool(model_info and model_info.get("supportsTools")),
        }

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Lê o modelo do catálogo (SQLite). Sem catálogo legado: migrado 2026-08-04."""
        try:
            return self.model_repository.get_model(self.provider_id, model_id)
        except Exception:
            logger.warning(
                "[Groq] catálogo indisponível para '%s'.", model_id, exc_info=True,
            )
            return None

    def _headers(self) -> dict[str, str]:
        """Build Groq request headers without exposing credentials."""
        return groq_headers(include_auth=True)

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Prefer the official Groq SDK if available (more reliable headers, error handling, avoids Cloudflare UA blocks).
        Falls back to the raw HTTP implementation from parent if the 'groq' package is not installed.
        """
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing_credentials:{self.api_key_env}")

        try:
            from groq import Groq
        except ImportError:
            # Fallback to urllib (parent logic)
            return super()._post_chat_completion(payload)

        client = Groq(api_key=api_key)

        # O payload já vem montado pela BASE (mesmas regras de todos os providers):
        # model/messages/temperature/tools + os knobs de reasoning que o
        # _apply_thinking_control (unificado, na base) decidiu. Aqui a gente só
        # REPASSA — não recalcula nada específico de Groq (senão vira duas fontes de
        # verdade divergentes). O SDK é usado só pra evitar bloqueio de UA da
        # Cloudflare; a lógica de pensar é a mesma do streaming.
        create_kwargs = {
            "model": payload.get("model"),
            "messages": payload.get("messages"),
            "temperature": payload.get("temperature"),
            "stream": False,
        }
        if payload.get("tools"):
            create_kwargs["tools"] = payload.get("tools")
            create_kwargs["tool_choice"] = payload.get("tool_choice", "auto")
        # Knobs de reasoning já decididos pela base (reasoning_format="parsed" separa
        # o raciocínio num campo próprio; reasoning_effort controla a profundidade).
        for knob in ("reasoning_format", "reasoning_effort"):
            if payload.get(knob) is not None:
                create_kwargs[knob] = payload[knob]

        # Remove None values
        create_kwargs = {k: v for k, v in create_kwargs.items() if v is not None}

        try:
            response = client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            # Some reasoning families reject reasoning_effort="none" (only qwen3/gpt-oss
            # accept it). Never let an optimization break a turn: drop it and retry once
            # before surfacing the error.
            if "reasoning_effort" in create_kwargs:
                create_kwargs.pop("reasoning_effort", None)
                try:
                    response = client.chat.completions.create(**create_kwargs)
                except Exception as exc2:
                    raise RuntimeError(f"groq_sdk_error:{exc2}") from exc2
            else:
                raise RuntimeError(f"groq_sdk_error:{exc}") from exc
        # Convert to dict for compatibility with the rest of the code that expects dict
        if hasattr(response, "model_dump"):
            return response.model_dump()
        elif hasattr(response, "to_dict"):
            return response.to_dict()
        else:
            return dict(response)

    def _attachment_parts(self, attachments: list[dict[str, Any]], *, model_info: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Convert image/text attachments into Groq-compatible content parts."""
        parts: list[dict[str, Any]] = []
        known_no_vision = bool(model_info) and not bool(model_info.get("supportsVision"))

        for item in attachments:
            if not isinstance(item, dict):
                continue
            mime_type = str(item.get("type") or "application/octet-stream").strip().lower()
            filename = str(item.get("name") or "attachment").strip() or "attachment"
            raw = self._decode_attachment(item)
            if not raw:
                raise ValueError("empty_attachment")

            if mime_type.startswith("image/"):
                if known_no_vision:
                    continue
                parts.append({"type": "image_url", "image_url": {"url": self._data_url(mime_type, raw)}})
                continue

            if mime_type.startswith("text/") or mime_type in {"text/plain", "text/markdown", "text/csv", "application/json", "application/xml"}:
                text = raw.decode("utf-8", errors="replace")
                parts.append({"type": "text", "text": f"\n\n[Attachment: {filename}]\n{text[:200000]}"})
                continue

            raise ValueError(f"groq_attachment_type_not_supported:{mime_type}")

        return parts, []

    def _system_prompt(
        self,
        request,
        *,
        model_info: dict[str, Any] | None,
        tools_enabled: bool,
        tools_supported: bool,
    ) -> str:
        """Add Groq-specific native-system guidance on top of the shared prompt."""
        text = super()._system_prompt(
            request,
            model_info=model_info,
            tools_enabled=tools_enabled,
            tools_supported=tools_supported,
        )
        if not (model_info and model_info.get("supportsNativeSearch")):
            return text
        return (
            text
            + "\n\n[GROQ COMPOUND SYSTEM]\n"
            "The selected Groq model is a Compound system with Groq-managed server-side tools such as web search, code execution, website visit, browser automation, and Wolfram Alpha.\n"
            "Use those native capabilities naturally when the user's task needs current information or computation, but do not claim Tavily/MCP/local tool usage unless an actual local tool call is available in this request.\n"
            "When native web results are used, summarize briefly and include source links returned by the model whenever available.\n"
        )
