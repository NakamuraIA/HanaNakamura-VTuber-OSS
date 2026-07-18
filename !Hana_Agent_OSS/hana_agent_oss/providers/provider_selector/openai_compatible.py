"""OpenAI-compatible Chat Completions provider base class.

Shared by OpenRouter, Groq, DeepSeek, Qwen and any future OpenAI-compatible
providers. Subclasses only need to supply the endpoint, headers, model catalog
and capability payload — streaming, tool loops, attachments and system prompts
are all handled here.
"""

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

from hana_agent_oss.api.services.unified_history import channel_style_hint
from hana_agent_oss.persona import build_provider_system_prompt
from hana_agent_oss.providers.contracts import ProviderRequest, ProviderResponse
from hana_agent_oss.tools.mcp_provider_tools import extract_sources_from_mcp
# build_tool_schemas_and_runners is imported lazily inside _tool_schemas_and_runners
# to avoid a circular import (openai_compatible → openrouter.tools_builder →
# openrouter.__init__ → openrouter.provider → openai_compatible).


logger = logging.getLogger(__name__)

SUPPORTED_TEXT_ATTACHMENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/xml",
}


class OpenAICompatibleProvider:
    """Base for providers that speak the OpenAI Chat Completions API."""

    # -------- subclass overrides --------
    aliases: set[str] = set()
    provider_id: str = ""
    provider_label: str = ""
    api_key_env: str = ""
    default_model: str = ""
    chat_completions_url: str = ""
    http_timeout_seconds: int = 300
    tool_rounds: int = 20
    supports_plugins: bool = False
    provider_status_title: str = ""

    # ========================================================================
    # Public API
    # ========================================================================

    async def generate_stream(self, request: ProviderRequest) -> AsyncGenerator[str, None]:
        """Stream tokens from the provider as an async generator of text chunks."""
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            yield "[ERRO: missing_credentials]"
            return

        model = (request.model or "").strip() or self.default_model
        model_info = self._custom_model_info(request.memory, model) or self._catalog_model(model)
        supports_tools = bool(model_info and model_info.get("supportsTools"))

        try:
            messages, plugins = self._build_messages(request, model_info=model_info)
        except ValueError as exc:
            yield f"[ERRO: {exc}]"
            return
        except Exception as exc:
            yield f"[ERRO: {self.provider_id}_attachment_error:{exc}]"
            return

        tools, runners = self._tool_schemas_and_runners(request, supports_tools=supports_tools)
        system_prompt = self._system_prompt(
            request,
            model_info=model_info,
            tools_enabled=bool(tools),
            tools_supported=supports_tools,
        )
        messages.insert(0, {"role": "system", "content": system_prompt})

        channel = str(getattr(request, "channel", "") or "")
        payload_base = self._build_payload_base(
            model=model,
            temperature=request.temperature,
            model_info=model_info,
            stream=True,
            tools=tools,
            plugins=plugins,
            provider_routing=request.openrouter_routing,
            channel=channel,
            thinking=bool(getattr(request, "thinking", True)),
            reasoning_effort=getattr(request, "reasoning_effort", None),
        )
        payload_base["messages"] = messages

        body = json.dumps(payload_base).encode("utf-8")
        req = urllib.request.Request(
            self.chat_completions_url,
            data=body,
            headers=self._headers(),
            method="POST",
        )

        # Run blocking HTTP in thread to avoid freezing the async event loop
        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=self.http_timeout_seconds),
            )
            buffer = ""
            tool_call_detected = False
            done = False
            # Decodificador incremental: guarda bytes de um caractere multibyte (ex.: "ã",
            # 2 bytes) que ficou partido entre dois chunks, em vez de virar "�".
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while not done:
                chunk = await loop.run_in_executor(None, response.read, 4096)
                if not chunk:
                    buffer += decoder.decode(b"", final=True)
                    break
                decoded = decoder.decode(chunk)
                buffer += decoded
                lines = buffer.split("\n")
                buffer = lines.pop() if not buffer.endswith("\n") else ""

                for line in lines:
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line == "data: [DONE]":
                        done = True
                        break
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices") or []
                    if not choices or not isinstance(choices, list):
                        continue
                    delta = choices[0].get("delta", {}) or {}

                    # Reasoning tokens — forward to caller when requested
                    reasoning = delta.get("reasoning_content") or ""
                    if reasoning and request.on_reasoning is not None:
                        await request.on_reasoning(reasoning)

                    # Real tool-call detection: streams tool calls in
                    # delta.tool_calls (not delta.content). When one appears, stop
                    # streaming partial text and delegate to the tool loop,
                    # which executes the tool rounds and returns the final answer.
                    if tools and runners and delta.get("tool_calls"):
                        tool_call_detected = True
                        done = True
                        break

                    content = delta.get("content") or ""
                    if content:
                        yield content

            # A tool call was requested mid-stream: run the full agentic loop.
            if tool_call_detected:
                try:
                    response.close()
                except Exception:
                    pass
                # Cérebro econômico: cheap model streams the chat; the moment a real
                # tool call happens, escalate the tool rounds to the configured agent
                # model (better at tool-calling). The agent can even live on a different
                # provider than the chat (e.g. chat on OpenRouter, tools on Groq).
                # Pure-chat turns stay on the cheap model/provider.
                agent_provider, agent_model = self._agent_target(request.memory)
                tool_provider = self
                tool_model = agent_model or model
                if agent_provider and agent_provider != self.provider_id:
                    candidate = self._provider_for(agent_provider)
                    # Only switch when the target provider exists AND its credentials
                    # are present; otherwise fall back to the main provider/model so a
                    # missing key never breaks the whole turn.
                    if candidate is not None and os.environ.get(candidate.api_key_env):
                        tool_provider = candidate
                        tool_model = agent_model or candidate.default_model
                    else:
                        tool_model = model
                if request.on_activity is not None:
                    detail = "Executando pesquisas e ações antes da resposta final."
                    switched_provider = tool_provider is not self
                    if switched_provider:
                        detail = f"Usando o agente ({tool_provider.provider_label}: {tool_model}) para as ferramentas."
                    elif agent_model and agent_model != model:
                        detail = f"Usando o modelo de agente ({agent_model}) para as ferramentas."
                    await request.on_activity({
                        "event": "tools_started",
                        "label": "Hana está usando ferramentas",
                        "detail": detail,
                    })
                # Ponte thread -> event loop: o loop de tools roda em executor (sync),
                # mas os tokens/eventos precisam chegar AO VIVO no websocket. Tokens
                # entram numa fila consumida aqui (yield real); reasoning e eventos
                # por-tool vão direto pros callbacks async do request.
                token_queue: asyncio.Queue[str | None] = asyncio.Queue()

                def _on_delta(token: str) -> None:
                    loop.call_soon_threadsafe(token_queue.put_nowait, token)

                def _on_reasoning(token: str) -> None:
                    if request.on_reasoning is not None:
                        asyncio.run_coroutine_threadsafe(request.on_reasoning(token), loop)

                def _on_tool_event(event: dict) -> None:
                    if request.on_tool_activity is not None:
                        asyncio.run_coroutine_threadsafe(request.on_tool_activity(event), loop)

                future = loop.run_in_executor(
                    None,
                    lambda: tool_provider._run_completion_loop(
                        model=tool_model,
                        messages=messages,
                        temperature=request.temperature,
                        plugins=plugins,
                        tools=tools,
                        tool_runners=runners,
                        memory=request.memory,
                        tool_runs=request.tool_runs,
                        provider_routing=request.openrouter_routing,
                        channel=channel,
                        # Loop de ferramentas = MODELO DE AGENTE: usa o "pensar" proprio
                        # dele (config da secao Modelo de Agente), nao o do chat.
                        thinking=getattr(request, "agent_thinking", getattr(request, "thinking", True)),
                        reasoning_effort=getattr(request, "agent_reasoning_effort", None),
                        on_delta=_on_delta,
                        on_reasoning=_on_reasoning,
                        on_tool_event=_on_tool_event,
                    ),
                )
                future.add_done_callback(lambda _f: token_queue.put_nowait(None))
                streamed_any = False
                while True:
                    token = await token_queue.get()
                    if token is None:
                        break
                    streamed_any = True
                    yield token
                full_response = await future  # já resolvido; propaga exceção se houve
                if request.on_activity is not None:
                    tool_count = len(request.tool_runs)
                    await request.on_activity({
                        "event": "tools_finished",
                        "label": f"{tool_count} chamada{'s' if tool_count != 1 else ''} concluída{'s' if tool_count != 1 else ''}",
                        "detail": "Preparando a resposta final.",
                    })
                # Resposta que NÃO passou pelo stream (ex.: fallback forçado após o
                # limite de rodadas vem de uma chamada non-streaming): entrega inteira.
                if not (isinstance(full_response, dict) and full_response.get("_streamed")):
                    fallback_text = self._response_text(full_response)
                    if fallback_text:
                        yield fallback_text
                elif not streamed_any:
                    final_text = self._response_text(full_response)
                    if final_text:
                        yield final_text
                return
        except urllib.error.HTTPError as exc:
            # Surface the real provider error body (it explains WHY: e.g. "no
            # endpoints support tool use", bad schema). The generic "HTTP 400" alone
            # is useless for debugging tool-call failures.
            try:
                detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            except Exception:
                detail = ""
            yield f"[ERRO: {self.provider_id}_http_{exc.code}:{detail[:600] or exc.reason}]"
        except Exception as exc:
            yield f"[ERRO: {exc}]"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            return ProviderResponse(ok=False, error=f"missing_credentials:{self.api_key_env}")

        model = (request.model or "").strip() or self.default_model
        # Prefer custom model overrides (from UI) over catalog for supports etc.
        model_info = self._custom_model_info(request.memory, model) or self._catalog_model(model)
        supports_tools = bool(model_info and model_info.get("supportsTools"))

        try:
            messages, plugins = self._build_messages(request, model_info=model_info)
        except ValueError as exc:
            return ProviderResponse(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(ok=False, error=f"{self.provider_id}_attachment_error:{exc}")

        tools, runners = self._tool_schemas_and_runners(request, supports_tools=supports_tools)
        system_prompt = self._system_prompt(
            request,
            model_info=model_info,
            tools_enabled=bool(tools),
            tools_supported=supports_tools,
        )
        messages.insert(0, {"role": "system", "content": system_prompt})

        meta: dict[str, Any] = {
            "provider": self.provider_id,
            "nativeSearch": False,
            "model": model,
            "attachments": self._attachment_meta(request.attachments),
            "capabilities": self._capabilities_payload(model_info),
        }

        import time as _time
        _started = _time.perf_counter()
        try:
            response_data = self._run_completion_loop(
                model=model,
                messages=messages,
                temperature=request.temperature,
                plugins=plugins,
                tools=tools,
                tool_runners=runners,
                memory=request.memory,
                tool_runs=request.tool_runs,
                provider_routing=request.openrouter_routing,
                channel=getattr(request, "channel", ""),
                thinking=getattr(request, "thinking", True),
                reasoning_effort=getattr(request, "reasoning_effort", None),
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            return ProviderResponse(ok=False, error=f"{self.provider_id}_http_{exc.code}:{detail[:1000]}", meta=meta)
        except TimeoutError:
            return ProviderResponse(ok=False, error=f"{self.provider_id}_timeout", meta=meta)
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(ok=False, error=f"{self.provider_id}_provider_error:{exc}", meta=meta)

        text = self._response_text(response_data)
        elapsed = max(0.001, _time.perf_counter() - _started)
        usage = response_data.get("usage") if isinstance(response_data, dict) else None
        completion_tokens = 0
        if isinstance(usage, dict):
            meta["usage"] = usage
            if "total_tokens" in usage:
                meta["tokens"] = usage.get("total_tokens")
            completion_tokens = int(usage.get("completion_tokens") or 0)

        # Visibility: which upstream actually served this turn (so a silent fallback
        # is never invisible again) + the real generation speed in tok/s.
        served = response_data.get("provider") if isinstance(response_data, dict) else None
        if served:
            meta["servedProvider"] = str(served)
        if completion_tokens:
            meta["speedTokensPerSec"] = round(completion_tokens / elapsed, 1)
        # Reasoning models bill their hidden chain-of-thought as completion tokens. When
        # the model "thinks" thousands of tokens to say one line, THAT is the real voice
        # latency — not the network/provider. Surface it so a slow turn is self-explaining.
        reasoning_tokens = 0
        if isinstance(usage, dict):
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict):
                reasoning_tokens = int(details.get("reasoning_tokens") or 0)
        if reasoning_tokens:
            meta["reasoningTokens"] = reasoning_tokens
        self._append_terminal_event(
            request.memory,
            kind="provider_telemetry",
            source=self.provider_id,
            status="info",
            tool_name="provider.telemetry",
            display_text=(
                f"⚡ {model} · {served or 'auto'}"
                + (f" · {meta['speedTokensPerSec']} tok/s" if completion_tokens else "")
                + (f" · 🧠 {reasoning_tokens} pensados" if reasoning_tokens else "")
                + f" · {elapsed:.1f}s"
            ),
            metadata={
                "servedProvider": served,
                "speedTokensPerSec": meta.get("speedTokensPerSec"),
                "reasoningTokens": reasoning_tokens or None,
                "elapsedSec": round(elapsed, 2),
            },
        )

        return ProviderResponse(
            ok=bool(text),
            text=text,
            error=None if text else "empty_provider_response",
            meta=meta,
        )

    # ========================================================================
    # Hooks — subclasses override these
    # ========================================================================

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
    ) -> None:
        """Throttle/disable model "thinking" per the user's toggle and channel.

        Base implementation is a no-op. Subclasses (e.g. OpenRouter) override
        with provider-specific reasoning knobs.
        """

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
        """Expose provider-specific model capabilities as a dict."""
        raise NotImplementedError

    def _attachment_parts(self, attachments: list[dict[str, Any]], *, model_info: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Convert local attachments into content parts and plugins.

        Base implementation handles images, PDFs and text. Providers that
        need different behaviour (e.g. Groq which rejects PDFs) override this.
        """
        parts: list[dict[str, Any]] = []
        plugins: list[dict[str, Any]] = []
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
                    # Skip image attachments for models without vision support.
                    # This prevents errors when visao is enabled but model (e.g. DeepSeek text) can't handle images.
                    # The text message will proceed without the screen image.
                    continue
                parts.append({"type": "image_url", "image_url": {"url": self._data_url(mime_type, raw)}})
                continue

            if mime_type == "application/pdf":
                parts.append(
                    {
                        "type": "file",
                        "file": {
                            "filename": filename,
                            "file_data": self._data_url(mime_type, raw),
                        },
                    }
                )
                plugins.append({"id": "file-parser", "pdf": {"engine": "cloudflare-ai"}})
                continue

            if mime_type in SUPPORTED_TEXT_ATTACHMENT_TYPES or mime_type.startswith("text/"):
                text = raw.decode("utf-8", errors="replace")
                parts.append({"type": "text", "text": f"\n\n[Attachment: {filename}]\n{text[:200000]}"})
                continue

            # Unsupported attachment type (e.g. an auto-recovered audio/mpeg on a
            # text-only model): skip it gracefully instead of breaking the whole
            # turn. The text message still goes through.
            continue

        return parts, plugins

    # ========================================================================
    # Generic helpers — shared by all OpenAI-compatible providers
    # ========================================================================

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
        # Inject image XML action manual if an image provider is active (same instructions as Gemini).
        image_provider_active = self._is_image_provider_active(request.memory)
        image_instruction = self._image_tool_instruction() if image_provider_active else (
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
        """Read custom model capabilities from memory (Control Center overrides)."""
        if memory is None:
            return None
        try:
            custom_models = memory.get_setting("custom_models", []) or []
        except Exception:
            logger.debug("Falha ao ler custom_models da memória", exc_info=True)
            return None
        if not isinstance(custom_models, list):
            return None
        for item in custom_models:
            if not isinstance(item, dict):
                continue
            if item.get("provider") == self.provider_id and item.get("id") == model_id:
                return item
        return None

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

    def _tool_schemas_and_runners(self, request: ProviderRequest, *, supports_tools: bool) -> tuple[list[dict[str, Any]], dict[str, Callable[[dict[str, Any]], dict[str, Any]]]]:
        """Monta as ferramentas (schemas + runners). Lógica em tools_builder."""
        # Lazy import to avoid circular import (openai_compatible →
        # openrouter.tools_builder → openrouter.__init__ → openrouter.provider →
        # openai_compatible).
        from hana_agent_oss.providers.provider_selector.openrouter.tools_builder import build_tool_schemas_and_runners

        return build_tool_schemas_and_runners(self, request, supports_tools=supports_tools)

    def _local_tool_instruction(self, *, enabled: bool, supported: bool) -> str:
        """Explain local tool availability for the model."""
        if not supported:
            return (
                "\n\n[LOCAL TOOL STATUS]\n"
                f"This {self.provider_label} model is not cataloged as supporting tool calls in this turn.\n"
                "Do not write mcp_discover(...), mcp_invoke(...), terminal_run(...), pseudo-code, or function-call syntax as visible text.\n"
                f"If Operador asks for MCP, Tavily, or local PC actions, explain that the selected {self.provider_label} model does not expose tools; she can select a tools-capable model.\n"
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
            "Before destructive/irreversible actions (delete, format, admin, credentials/.env), investigate first, show what you will do, and confirm with Operador.\n"
            "Do not use local tools for normal chat, STT, TTS, or image generation; use MCP web tools only for explicit external research/current-facts needs.\n"
            "If a tool returns ok=false, quote the returned error exactly and do not invent a different cause.\n"
        )

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one non-streaming Chat Completions request to the provider."""
        # Strip internal-only hints (prefixed with '_', e.g. _channel) so they never
        # reach the provider API as unknown fields.
        payload = {k: v for k, v in payload.items() if not str(k).startswith("_")}
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.chat_completions_url,
            data=body,
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.http_timeout_seconds) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        if not raw_body:
            return {}
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            # Include raw body snippet for debugging (e.g. HTML error page or empty)
            snippet = raw_body[:500].replace("\n", "\\n")
            raise ValueError(f"invalid_json_response: {exc}. raw_body_starts_with: {snippet!r}") from exc

    def _run_completion_loop(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        plugins: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_runners: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
        memory: Any = None,
        tool_runs: list[dict[str, Any]] | None = None,
        provider_routing: dict[str, Any] | None = None,
        channel: str = "",
        thinking: bool = True,
        reasoning_effort: str | None = None,
        on_delta: Callable[[str], Any] | None = None,
        on_reasoning: Callable[[str], Any] | None = None,
        on_tool_event: Callable[[dict], Any] | None = None,
        on_activity: Callable[[dict], Any] | None = None,
    ) -> dict[str, Any]:
        """Run a bounded tool-call loop and return the final response.

        When ``tool_runs`` is provided, every executed tool call records a compact
        run entry ({tool, ok, summary, query, sources}) so the chat can render a
        tool-activity card. This is the single capture point for all tools
        (MCP/Tavily, local hands).

        When streaming callbacks (on_delta / on_reasoning / on_tool_event /
        on_activity) are provided, each iteration uses ``stream: True`` SSE so the
        caller receives live tokens and per-tool events. When no callbacks are
        given the legacy non-streaming path is preseved unchanged.
        """
        model_info = self._custom_model_info(memory, model) or self._catalog_model(model)

        use_streaming = (
            on_delta is not None
            or on_reasoning is not None
            or on_tool_event is not None
            or on_activity is not None
        )

        # ------------------------------------------------------------------
        # STREAMING path — SSE per round with live callbacks
        # ------------------------------------------------------------------
        if use_streaming:
            payload_base = self._build_payload_base(
                model=model,
                temperature=temperature,
                model_info=model_info,
                stream=True,
                tools=tools or [],
                plugins=plugins,
                provider_routing=provider_routing,
                channel=channel,
                thinking=bool(thinking),
                reasoning_effort=reasoning_effort,
            )

            rounds_limit = self._tool_rounds_limit(memory)  # 0 = unlimited
            round_index = 0
            while True:
                payload = dict(payload_base)
                payload["messages"] = messages
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    self.chat_completions_url,
                    data=body,
                    headers=self._headers(),
                    method="POST",
                )

                content_parts: list[str] = []
                reasoning_parts: list[str] = []
                tool_call_acc: dict[int, dict[str, Any]] = {}

                try:
                    response = urllib.request.urlopen(req, timeout=self.http_timeout_seconds)
                except urllib.error.HTTPError as exc:
                    try:
                        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                    except Exception:
                        detail = ""
                    error_text = f"[ERRO: {self.provider_id}_http_{exc.code}:{detail[:600] or exc.reason}]"
                    if on_delta is not None:
                        on_delta(error_text)
                    return {"choices": [{"message": {"role": "assistant", "content": error_text}}], "_streamed": on_delta is not None}

                buffer = ""
                done = False
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while not done:
                    chunk = response.read(4096)
                    if not chunk:
                        buffer += decoder.decode(b"", final=True)
                        break
                    decoded = decoder.decode(chunk)
                    buffer += decoded
                    lines = buffer.split("\n")
                    buffer = lines.pop() if not buffer.endswith("\n") else ""

                    for line in lines:
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line == "data: [DONE]":
                            done = True
                            break
                        if not line.startswith("data: "):
                            continue
                        try:
                            data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        choices = data.get("choices") or []
                        if not choices or not isinstance(choices, list):
                            continue
                        delta = choices[0].get("delta", {}) or {}

                        # Reasoning tokens
                        reasoning = delta.get("reasoning_content") or ""
                        if reasoning:
                            reasoning_parts.append(reasoning)
                            if on_reasoning is not None:
                                on_reasoning(reasoning)

                        # Content tokens
                        content = delta.get("content") or ""
                        if content:
                            content_parts.append(content)
                            if on_delta is not None:
                                on_delta(content)

                        # Tool-call deltas (accumulate across chunks)
                        delta_tool_calls = delta.get("tool_calls")
                        if delta_tool_calls:
                            for tc in delta_tool_calls:
                                idx = tc.get("index", 0)
                                if idx not in tool_call_acc:
                                    tool_call_acc[idx] = {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                if tc.get("id"):
                                    tool_call_acc[idx]["id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    tool_call_acc[idx]["function"]["name"] += fn["name"]
                                if fn.get("arguments"):
                                    tool_call_acc[idx]["function"]["arguments"] += fn["arguments"]

                try:
                    response.close()
                except Exception:
                    pass

                completed_tool_calls = [tool_call_acc[idx] for idx in sorted(tool_call_acc.keys())]

                if not completed_tool_calls:
                    # Stream ended — no tools requested, return accumulated text.
                    # "_streamed" avisa o generate_stream que esse texto JÁ subiu
                    # token a token pelo on_delta (não re-entregar inteiro).
                    full_text = "".join(content_parts)
                    return {
                        "choices": [{"message": {"role": "assistant", "content": full_text}}],
                        "_streamed": on_delta is not None,
                    }

                if rounds_limit and round_index >= rounds_limit:
                    # Round budget exhausted with tool calls still pending.
                    break

                # Build assistant message from accumulated stream
                assistant_content = "".join(content_parts) or None
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                        "tool_calls": completed_tool_calls,
                    }
                )

                # Execute each tool with per-tool events
                for tool_call in completed_tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                    name = str(function.get("name") or "").strip().replace(".", "_")
                    runner = (tool_runners or {}).get(name)
                    args = self._tool_arguments(function.get("arguments"))

                    # --- Per-tool: antes da execução ---
                    args_preview = json.dumps(args, ensure_ascii=False)
                    if len(args_preview) > 120:
                        args_preview = args_preview[:120] + "..."

                    if on_tool_event is not None:
                        on_tool_event({"kind": "tool_call", "tool": name, "args": args})

                    self._append_terminal_event(
                        memory,
                        kind="tool_call",
                        source=self.provider_id,
                        status="running",
                        tool_name=name,
                        display_text=f"Chamando: {name}({args_preview})",
                        metadata={"tts": False, "args": args},
                    )

                    # Execute
                    if "_args_json_error" in args:
                        result = {"ok": False, "error": f"tool_arguments_invalid_json:{args['_args_json_error']}"}
                    elif runner is None:
                        result = {"ok": False, "error": f"{self.provider_id}_tool_not_registered:{name}"}
                    else:
                        result = runner(args)

                    if tool_runs is not None:
                        tool_runs.append(self._tool_run_record(name, args, result))

                    # --- Per-tool: depois da execução ---
                    result_preview = self._result_preview(result) if result else ""
                    if on_tool_event is not None:
                        on_tool_event({"kind": "tool_result", "tool": name, "result": result})

                    self._append_terminal_event(
                        memory,
                        kind="tool_result",
                        source=self.provider_id,
                        status="success" if result.get("ok") else "failed",
                        tool_name=name,
                        display_text=f"{'OK' if result.get('ok') else 'ERRO'}: {name} — {result_preview}",
                        metadata={"tts": False, "result": result},
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(tool_call.get("id") or name),
                            "name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )

                round_index += 1

            # --- Round limit exhausted (streaming path) ---
            self._append_terminal_event(
                memory,
                kind="tool_result",
                source=self.provider_id,
                status="failed",
                tool_name=f"{self.provider_id}.tools",
                display_text=f"{self.provider_label} atingiu o limite de rodadas de tools ({rounds_limit}).",
                metadata={"toolRounds": rounds_limit},
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "[SISTEMA] Limite de rodadas de ferramentas atingido neste turno; suas últimas chamadas NÃO foram executadas. "
                        "Responda agora SEM ferramentas, com honestidade: diga exatamente o que você JÁ fez de verdade, o que FALTOU fazer, "
                        "e peça para a Operador mandar 'continua' para você terminar no próximo turno. "
                        "É PROIBIDO afirmar que terminou ou prometer que 'vai fazer agora'."
                    ),
                }
            )
            final_payload = dict(payload_base)
            final_payload["messages"] = messages
            final_payload["tool_choice"] = "none"
            final_payload["stream"] = False  # force non-streaming for the final forced answer
            try:
                return self._post_chat_completion(final_payload)
            except Exception:
                return {"choices": [{"message": {"role": "assistant", "content": ""}}]}

        # ------------------------------------------------------------------
        # NON-STREAMING path — legacy behaviour, kept identical
        # ------------------------------------------------------------------
        payload_base = self._build_payload_base(
            model=model,
            temperature=temperature,
            model_info=model_info,
            stream=False,
            tools=tools or [],
            plugins=plugins,
            provider_routing=provider_routing,
            channel=channel,
            thinking=bool(thinking),
            reasoning_effort=reasoning_effort,
        )

        last_response: dict[str, Any] = {}
        rounds_limit = self._tool_rounds_limit(memory)  # 0 = unlimited
        round_index = 0
        while True:
            payload = dict(payload_base)
            payload["messages"] = messages
            last_response = self._post_chat_completion(payload)
            message = self._response_message(last_response)
            tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
            if not tool_calls:
                return last_response
            if rounds_limit and round_index >= rounds_limit:
                # Round budget exhausted with tool calls still pending. Do NOT silently
                # drop them (the model would have already promised work it can't do).
                # Tell the model and force one final honest text answer without tools.
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                name = str(function.get("name") or "").strip().replace(".", "_")  # normalize mc.follow -> mc_follow for robustness
                runner = (tool_runners or {}).get(name)
                args = self._tool_arguments(function.get("arguments"))
                if "_args_json_error" in args:
                    result = {"ok": False, "error": f"tool_arguments_invalid_json:{args['_args_json_error']}"}
                elif runner is None:
                    result = {"ok": False, "error": f"{self.provider_id}_tool_not_registered:{name}"}
                else:
                    result = runner(args)
                if tool_runs is not None:
                    tool_runs.append(self._tool_run_record(name, args, result))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call.get("id") or name),
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            round_index += 1

        self._append_terminal_event(
            memory,
            kind="tool_result",
            source=self.provider_id,
            status="failed",
            tool_name=f"{self.provider_id}.tools",
            display_text=f"{self.provider_label} atingiu o limite de rodadas de tools ({rounds_limit}).",
            metadata={"toolRounds": rounds_limit},
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "[SISTEMA] Limite de rodadas de ferramentas atingido neste turno; suas últimas chamadas NÃO foram executadas. "
                    "Responda agora SEM ferramentas, com honestidade: diga exatamente o que você JÁ fez de verdade, o que FALTOU fazer, "
                    "e peça para a Operador mandar 'continua' para você terminar no próximo turno. "
                    "É PROIBIDO afirmar que terminou ou prometer que 'vai fazer agora'."
                ),
            }
        )
        final_payload = dict(payload_base)
        final_payload["messages"] = messages
        final_payload["tool_choice"] = "none"
        try:
            return self._post_chat_completion(final_payload)
        except Exception:
            return last_response

    # ========================================================================
    # Image provider helpers
    # ========================================================================

    @staticmethod
    def _is_image_provider_active(memory: Any) -> bool:
        """Check if any image generation provider is configured and active."""
        if memory is None:
            return False
        try:
            provider = memory.get_setting("image_provider", None)
            if provider:
                return True
            # Default: gemini_api is always available if GOOGLE_API_KEY is set.
            import os
            return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
        except Exception:
            logger.debug("Falha ao checar provider de imagem ativo", exc_info=True)
            return False

    @classmethod
    def _image_tool_instruction(cls) -> str:
        """Build the XML image action guide injected into system prompts (shared with Gemini)."""
        try:
            from hana_agent_oss.providers.provider_selector.gemini_api.provider import GeminiApiProvider
            return GeminiApiProvider._image_tool_instruction()
        except Exception:
            # Fallback: minimal image instruction if Gemini provider is unavailable.
            return (
                "\n\n[IMAGE XML ACTION MANUAL]\n"
                "Image generation does not use function calling. To request image work, write one silent XML tag at the end of your answer.\n"
                "For generic images, use exactly: <gerar_imagem>English prompt for the image</gerar_imagem>.\n"
                "For generic edits, use exactly: <editar_imagem>English edit instruction</editar_imagem>.\n"
                "For known characters, use exactly <gerar_imagem_personagem>{valid JSON}</gerar_imagem_personagem>.\n"
                "For character edits, use exactly <editar_imagem_personagem>{valid JSON}</editar_imagem_personagem>.\n"
                "Your visible sentence should say that you are starting/preparing the image, not that it is already ready.\n"
            )

    # ========================================================================
    # Attachment helpers
    # ========================================================================

    @staticmethod
    def _decode_attachment(item: dict[str, Any]) -> bytes:
        """Read an attachment from disk or decode frontend base64/data URL payloads."""
        if item.get("path"):
            return Path(str(item.get("path"))).read_bytes()
        value = str(item.get("data") or "")
        if "," in value and value.lower().startswith("data:"):
            value = value.split(",", 1)[1]
        try:
            return base64.b64decode(value, validate=False)
        except binascii.Error as exc:
            raise ValueError("invalid_base64_attachment") from exc

    @staticmethod
    def _data_url(mime_type: str, raw: bytes) -> str:
        """Build a data URL accepted by multimodal content parts."""
        return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"

    @staticmethod
    def _attachment_meta(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": str(item.get("name") or "attachment"),
                "type": str(item.get("type") or "application/octet-stream"),
                "size": int(item.get("size") or 0),
            }
            for item in attachments
            if isinstance(item, dict)
        ]

    # ========================================================================
    # Tool helpers
    # ========================================================================

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        """Parse optional numeric tool arguments without letting bad model output crash the provider."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _tool_rounds_limit(self, memory: Any) -> int:
        """Tool-round budget for one turn, configurable via llm_config.agentToolRounds.

        0 means unlimited (the agent works until the model stops calling tools).
        Falls back to the class default. Configurable because a hard low cap makes the
        agent silently die mid-task; Operador tunes this from the panel.
        """
        try:
            cfg = memory.get_setting("llm_config", {}) or {}
            raw = cfg.get("agentToolRounds")
            if raw is not None:
                rounds = int(raw)
                if rounds <= 0:
                    return 0  # unlimited
                return min(500, rounds)
        except Exception:
            logger.debug("Falha ao ler agentToolRounds; usando o padrão", exc_info=True)
        return self.tool_rounds

    @staticmethod
    def _tool_arguments(value: Any) -> dict[str, Any]:
        """Accept tool arguments as either a JSON string or an already-decoded object.

        JSON inválido NÃO vira {} silencioso: loga e devolve um marcador que o loop
        transforma em erro estruturado pro modelo (senão a tool roda "vazia" e o bug
        do modelo fica invisível).
        """
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value or "{}")
            except json.JSONDecodeError as exc:
                logger.warning("Tool call com JSON de argumentos inválido: %s — raw=%r", exc, value[:300])
                return {"_args_json_error": f"{exc}"}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _result_preview(result: dict[str, Any]) -> str:
        """Short human-readable preview of a tool result for terminal events."""
        if not isinstance(result, dict):
            return str(result)[:80]
        if result.get("ok") is True:
            text = "ok"
        else:
            text = str(
                result.get("error")
                or result.get("response")
                or result.get("message")
                or result.get("summary")
                or result.get("result")
                or ""
            )
        if len(text) > 80:
            text = text[:80].rstrip() + "..."
        return text

    @staticmethod
    def _tool_run_record(name: str, args: dict[str, Any], result: Any) -> dict[str, Any]:
        """Build a compact, UI-friendly record of one tool execution for the chat card."""
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
        summary = ""
        if isinstance(result, dict):
            summary = str(
                result.get("error")
                or result.get("response")
                or result.get("message")
                or result.get("summary")
                or result.get("result")
                or ""
            )
        else:
            summary = str(result)
        if len(summary) > 400:
            summary = summary[:400].rstrip() + "..."
        query = ""
        if isinstance(args, dict):
            # mcp_invoke aninha os args reais em "arguments" ({tool, arguments:{query}});
            # sem olhar dentro, o card de pesquisa mostrava o NOME da tool como query.
            nested = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
            query = str(
                args.get("query")
                or args.get("q")
                or args.get("search")
                or nested.get("query")
                or nested.get("q")
                or nested.get("search")
                or args.get("task")
                or args.get("url")
                or ""
            )
        return {
            "tool": name,
            "ok": ok,
            "summary": summary,
            "query": query,
            "sources": extract_sources_from_mcp(result),
        }

    @classmethod
    def _sanitize_tool_schema(cls, value: Any) -> Any:
        """Remove provider-invalid empty enum values from nested tool schemas."""
        if isinstance(value, list):
            return [cls._sanitize_tool_schema(item) for item in value]
        if not isinstance(value, dict):
            return value

        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key == "enum" and isinstance(item, list):
                enum_values = [
                    cls._sanitize_tool_schema(option)
                    for option in item
                    if option is not None and not (isinstance(option, str) and not option.strip())
                ]
                if enum_values:
                    sanitized[key] = enum_values
                continue
            sanitized[key] = cls._sanitize_tool_schema(item)
        return sanitized

    # ========================================================================
    # Agent / provider routing
    # ========================================================================

    @staticmethod
    def _agent_target(memory: Any) -> tuple[str, str]:
        """Optional provider+model used only for tool-execution rounds (cérebro econômico).

        Returns ``(agent_provider, agent_model)``. Either may be empty: an empty
        provider means "stay on the main provider", an empty model means "use that
        provider's default model". This lets the chat run on a cheap model/provider
        and escalate the tool rounds to a stronger one (even a different provider,
        e.g. main on OpenRouter and agent on Groq).
        """
        if memory is None:
            return "", ""
        try:
            cfg = memory.get_setting("llm_config", {}) or {}
            return (
                str(cfg.get("agentProvider") or "").strip().lower(),
                str(cfg.get("agentModel") or "").strip(),
            )
        except Exception:
            return "", ""

    @staticmethod
    def _provider_for(provider_id: str) -> "OpenAICompatibleProvider | None":
        """Return an OpenAI-compatible provider instance for the agent tool loop.

        Only OpenAI-compatible providers (OpenRouter, Groq, DeepSeek) share
        ``_run_completion_loop`` and the message/tool schema built here, so those
        are the only valid agent targets. Anything else (e.g. gemini_api) returns
        None → caller keeps the main provider.
        """
        pid = str(provider_id or "").strip().lower()
        if pid in ("openrouter", "open_router", "openrouters"):
            from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider
            return OpenRouterProvider()
        if pid in ("groq", "groqcloud", "groq_cloud", "glock"):
            from hana_agent_oss.providers.provider_selector.groq.provider import GroqProvider
            return GroqProvider()
        if pid in ("deepseek", "deepseek_official", "deep_seek"):
            from hana_agent_oss.providers.provider_selector.deepseek.provider import DeepSeekProvider
            return DeepSeekProvider()
        return None

    # ========================================================================
    # Terminal Agent events
    # ========================================================================

    @staticmethod
    def _append_terminal_event(memory: Any, *, kind: str, source: str, status: str, tool_name: str, display_text: str, metadata: dict[str, Any]) -> None:
        """Mirror provider local tool calls into Terminal Agent events."""
        if memory is None:
            return
        try:
            from hana_agent_oss.api.services.terminal_agent import append_terminal_event

            append_terminal_event(
                memory,
                {
                    "kind": kind,
                    "source": source,
                    "displayText": display_text,
                    "speechText": "",
                    "status": status,
                    "toolName": tool_name,
                    "metadata": {"tts": False, **metadata},
                },
            )
        except Exception:
            return

    # ========================================================================
    # Response helpers
    # ========================================================================

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
