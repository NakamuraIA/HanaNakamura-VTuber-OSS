"""Responsabilidade extraída do provider OpenAI-compatible."""

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
from backend.tools.mcp_provider_tools import extract_sources_from_mcp
# build_tool_schemas_and_runners is imported lazily inside _tool_schemas_and_runners.


logger = logging.getLogger(__name__)

SUPPORTED_TEXT_ATTACHMENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/xml",
}




class MessageSupport:
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
        """Build the payload dict for a Chat Completions request.

        Subclasses override this to inject provider-specific fields (plugins,
        provider routing, etc.) before the request is sent.
        """
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "stream": stream,
        }
        max_tokens = self._max_tokens_for_model(model_info)
        if max_tokens:
            payload["max_tokens"] = max_tokens
        self._apply_thinking_control(
            payload,
            model=model,
            model_info=model_info,
            channel=channel,
            thinking_enabled=bool(thinking),
            reasoning_effort=reasoning_effort,
            stream=bool(stream),
        )
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload


    def _apply_thinking_control(
        self,
        payload_base: dict[str, Any],
        *,
        model: str,
        model_info: dict[str, Any] | None = None,
        channel: str,
        thinking_enabled: bool,
        reasoning_effort: str | None = None,
        stream: bool = True,
    ) -> None:
        """Liga/desliga o "pensar" do modelo conforme o toggle e o canal.

        UM lugar só, na BASE, pra TODOS os providers — cada API expõe um knob
        diferente pra mesma ideia (ver docs/PROVIDERS.md). Antes isso morava no
        OpenRouterProvider e só ele/Maritaca herdavam; DeepSeek/Qwen/Groq caíam
        num no-op e o toggle de pensar não fazia nada neles. Sintaxe de cada knob
        confirmada com as docs oficiais em 2026-07-21.
        """
        model_id = str(model or "").lower()
        channel = channel.strip().lower()
        low_latency = channel in {"voice", "terminal_agent"}

        if self.provider_id == "openrouter":
            # OpenRouter agrega vários upstreams; só modelos com "reasoning" nos
            # supportedParameters aceitam o knob unificado — mandar pros outros = 400.
            supported = model_info.get("supportedParameters") if isinstance(model_info, dict) else None
            if not supported or "reasoning" not in supported:
                return
            explicit = str(reasoning_effort or "").strip().lower()
            if explicit in self.OPENROUTER_REASONING_LEVELS:
                payload_base["reasoning"] = {"effort": explicit}
                return
            if not thinking_enabled:
                payload_base["reasoning"] = {"effort": "none"}
            elif low_latency:
                payload_base["reasoning"] = {"effort": "low"}

        elif self.provider_id == "groq":
            is_reasoning = any(tag in model_id for tag in ("qwen3", "qwen/qwen3", "gpt-oss", "deepseek-r1", "-r1"))
            if not is_reasoning:
                return
            # Separa o raciocínio num campo próprio (delta.reasoning no stream) em
            # vez de despejar <think> dentro do content (que a TTS acabava lendo).
            payload_base["reasoning_format"] = "parsed"
            if "qwen3" in model_id:
                # No Groq, Qwen aceita apenas default (ligado) ou none (desligado).
                payload_base["reasoning_effort"] = "default" if thinking_enabled else "none"
            elif not thinking_enabled:
                payload_base["reasoning_effort"] = "none"
            elif low_latency:
                payload_base["reasoning_effort"] = "low"

        elif self.provider_id == "qwen":
            # Só qwen3.x é hybrid-thinking confirmado; aliases genéricos
            # (qwen-plus/turbo/max) podem apontar pra snapshots que rejeitam o param.
            if not model_id.startswith("qwen3."):
                return
            # CRÍTICO: qwen3.x só pensa em streaming. Non-stream + thinking = 400.
            if not stream:
                payload_base["enable_thinking"] = False
                return
            if not thinking_enabled:
                payload_base["enable_thinking"] = False
            elif low_latency:
                payload_base["enable_thinking"] = True
                payload_base["thinking_budget"] = 300
            else:
                payload_base["enable_thinking"] = True

        elif self.provider_id == "deepseek":
            # DeepSeek pensa por padrão (enabled). Só precisa de knob pra DESLIGAR.
            explicit = str(reasoning_effort or "").strip().lower()
            if explicit == "off" or not thinking_enabled:
                payload_base["thinking"] = {"type": "disabled"}
                return
            if explicit in {"high", "max"}:
                payload_base["reasoning_effort"] = explicit


    def _capability_hint(self, model_info: dict[str, Any] | None) -> str:
        """Provider-specific capability hint appended to the system prompt.

        Subclasses override this to tell the model which capabilities are
        available through this provider.
        """
        return ""


    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Read model metadata from the provider-specific catalog."""
        raise NotImplementedError


    def _headers(self) -> dict[str, str]:
        """Build request headers (with auth) for this provider."""
        raise NotImplementedError


    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Only the capability keys actually read by a prompt hint somewhere."""
        raise NotImplementedError


    def _system_prompt(
        self,
        request: ProviderRequest,
        *,
        model_info: dict[str, Any] | None,
        tools_enabled: bool,
        tools_supported: bool,
    ) -> str:
        """Build provider-specific system prompt via hooks."""
        base = build_provider_system_prompt(self.provider_id)
        style = channel_style_hint(request.channel, call_mode=getattr(request, "call_mode", False))
        capability_hint = self._capability_hint(model_info)

        # Add screen vision behavior hint if screen capture is present in attachments (for call + watching screen use case)
        has_screen = any(
            isinstance(item, dict) and str(item.get("name") or "").startswith("screen_capture")
            for item in (request.attachments or [])
        )
        if has_screen:
            capabilities = self._capabilities_payload(model_info)
            if capabilities.get("supports_image"):
                vision_hint = (
                    "\n\n[INSTRUÇÃO DE VISÃO - REAÇÕES NATURAIS À TELA]\n"
                    "Você tem acesso à tela atual do usuário via anexo de imagem (screen_capture).\n"
                    "Aja de forma natural e integrada: faça comentários, piadas leves, reações sarcásticas ou curiosas sobre o que está acontecendo na tela (jogo, desktop, vídeo, etc).\n"
                    "NÃO faça narração chata tipo 'Estou vendo um navegador aberto...'. Em vez disso, reaja como se estivesse assistindo junto na call.\n"
                    "Mantenha respostas curtas e faláveis. Use o contexto da conversa recente + o que vê na tela."
                )
                capability_hint += vision_hint
        # Inject image instruction: native tools if available, XML fallback otherwise.
        image_provider_active = self._is_image_provider_active(request.memory)
        image_instruction = self._image_tool_instruction_for_request(request) if image_provider_active else (
            "\n\n[IMAGE XML STATUS]\n"
            "No image generation provider is active. Do not use XML image tags.\n"
        )

        return (
            base
            + capability_hint
            + image_instruction
            + self._local_tool_instruction(enabled=tools_enabled, supported=tools_supported)
            + style
        )


    def _custom_model_info(self, memory: Any, model_id: str) -> dict[str, Any] | None:
        """Lê capacidades de um modelo manual na fonte única do catálogo."""
        try:
            from backend.catalog.repository import LlmModelRepository

            model = LlmModelRepository().get_model(self.provider_id, model_id)
        except Exception:
            logger.debug("Falha ao ler modelo manual do catálogo", exc_info=True)
            return None
        return model if model and model.get("custom") else None


    @staticmethod
    def _max_tokens_for_model(model_info: dict[str, Any] | None) -> int | None:
        """Explicit output cap so "thinking" models don't silently truncate answers.

        Some models (e.g. Qwen3.5/3.7 with reasoning enabled) spend part of the
        output budget on hidden reasoning tokens before the visible answer. Without
        an explicit max_tokens, the API's own default can be modest and cut the
        answer mid-sentence once reasoning + content exceed it. Cap generously
        using the catalog's maxOutputTokens (bounded to avoid absurd requests).
        """
        raw = model_info.get("maxOutputTokens") if isinstance(model_info, dict) else None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return min(value, 8192)


    def _build_messages(self, request: ProviderRequest, *, model_info: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build messages for the Chat Completions API and attach files only to the latest user turn."""
        attachment_parts, plugins = self._attachment_parts(request.attachments, model_info=model_info)
        messages: list[dict[str, Any]] = []
        recent_messages = request.messages[-20:]

        for index, msg in enumerate(recent_messages):
            raw_role = str(msg.get("role") or "user").strip().lower()
            if raw_role == "system":
                role = "system"
            elif raw_role in {"assistant", "model", "hana"}:
                role = "assistant"
            else:
                role = "user"
            text = str(msg.get("content") or "").strip()
            is_latest_user = role == "user" and index == len(recent_messages) - 1

            if is_latest_user and attachment_parts:
                content: list[dict[str, Any]] = []
                if text:
                    content.append({"type": "text", "text": text})
                content.extend(attachment_parts)
                if not text:
                    content.insert(0, {"type": "text", "text": "Analise os anexos enviados."})
                messages.append({"role": "user", "content": content})
                continue

            if text:
                messages.append({"role": role, "content": text})

        if not messages and attachment_parts:
            messages.append({"role": "user", "content": [{"type": "text", "text": "Analise os anexos enviados."}, *attachment_parts]})

        # Native web search via the plugins field (works only when supports_plugins is True).
        if self.supports_plugins and str(request.native_search_mode or "off").lower() in {"auto", "force"}:
            plugins.append({"id": "web", "max_results": 5})

        return messages, plugins


    def _local_tool_instruction(self, *, enabled: bool, supported: bool) -> str:
        """Explain local tool availability for the model."""
        if not supported:
            return (
                "\n\n[LOCAL TOOL STATUS]\n"
                f"This {self.provider_label} model is not cataloged as supporting tool calls in this turn.\n"
                "Do not write mcp_discover(...), mcp_invoke(...), terminal_run(...), pseudo-code, or function-call syntax as visible text.\n"
                f"If Nakamura asks for MCP, Tavily, or local PC actions, explain that the selected {self.provider_label} model does not expose tools; she can select a tools-capable model.\n"
            )
        if not enabled:
            return (
                "\n\n[LOCAL TOOL STATUS]\n"
                f"The selected {self.provider_label} model supports tools, but no Hana local tools are enabled/configured for this turn.\n"
                "Do not write mcp_discover(...), mcp_invoke(...), terminal_run(...) as visible text, and do not claim a tool was called.\n"
            )
        return (
            "\n\n[LOCAL TOOL MANUAL]\n"
            "Use actual tool calls, never visible pseudo-call text.\n"
            "Use mcp_discover and mcp_invoke for enabled MCP servers such as Tavily web research; respect backend allowlists and real tool errors.\n"
            "Use terminal_run / terminal_inspect_dir for local PC actions: run commands/scripts, find files, inspect folders. They run in-process and return the real output.\n"
            "To CREATE or EDIT a file (HTML/CSS/JS/Python/text), ALWAYS use file_write with the full content as the argument — one call per file. "
            "NEVER write file content through terminal_run with PowerShell here-strings (@\"...\"@ / echo / Out-File): that corrupts the content "
            "(eats $variables and ${...}, turns backticks into escapes, mangles accents, and fails on big files). Use file_read to inspect and file_exists to check. "
            "Do not re-read the same file repeatedly — read once, act, then finish; do not loop.\n"
            "Before destructive/irreversible actions (delete, format, admin, credentials/.env), investigate first, show what you will do, and confirm with Nakamura.\n"
            "Do not use local tools for normal chat, STT, TTS, or image generation; use MCP web tools only for explicit external research/current-facts needs.\n"
            "If a tool returns ok=false, quote the returned error exactly and do not invent a different cause.\n"
        )


    @staticmethod
    def _reasoning_mandatory_error(detail: str) -> bool:
        """Erro de endpoint que NAO deixa desligar o reasoning (ex: Kimi K3).

        Com o toggle "Pensar" off a Hana manda reasoning.effort=none; modelos de
        reasoning obrigatorio devolvem 400 "Reasoning is mandatory". Nesse caso o
        certo e retirar o knob e retentar (o modelo pensa; melhor que quebrar o turno).
        """
        return "easoning is mandatory" in detail


    @staticmethod
    def _response_message(response_data: dict[str, Any]) -> dict[str, Any]:
        """Extract the first assistant message from the Chat Completions response."""
        choices = response_data.get("choices") if isinstance(response_data, dict) else None
        if not isinstance(choices, list) or not choices:
            return {}
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        return message


    @classmethod
    def _response_text(cls, response_data: dict[str, Any]) -> str:
        """Extract normalized text from chat/non-chat choices.

        Reasoning models (qwen3, gpt-oss) sometimes return the answer in a separate
        ``reasoning``/``reasoning_content`` field with ``content`` empty. Reading only
        ``content`` then yields "" -> the turn fails as 'empty_provider_response' even
        though the model DID answer (tokens were generated). We fall back to the
        reasoning field so a reasoning model never looks like a dead provider.
        """
        message = cls._response_message(response_data)
        text = ""
        content = message.get("content") if isinstance(message, dict) else ""
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts = [
                str(part.get("text") or "").strip()
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            text = "\n".join(part for part in parts if part).strip()
        if not text:
            choices = response_data.get("choices") if isinstance(response_data, dict) else None
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                text = str(choices[0].get("text") or "").strip()
        # NOTE: never fall back to message.reasoning here — for reasoning models that
        # field is raw chain-of-thought ("The user wants me to..."), which would leak
        # into the chat and TTS. Groq reasoning models use reasoning_format="parsed"
        # so the clean answer is already in `content`.
        return text

