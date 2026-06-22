from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

from hana_agent_oss.api.services.unified_history import channel_style_hint
from hana_agent_oss.persona import build_provider_system_prompt
from hana_agent_oss.providers.contracts import ProviderRequest, ProviderResponse
from hana_agent_oss.providers.provider_selector.openrouter.catalog import (
    OPENROUTER_BASE_URL,
    get_openrouter_model,
    openrouter_headers,
)
# Image provider integration: image XML tool instructions for all LLM providers.
from hana_agent_oss.modules.vision.image_provider import normalize_image_provider
from hana_agent_oss.tools.mcp_provider_tools import extract_sources_from_mcp, mcp_openai_runners, mcp_openai_schemas


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


class OpenRouterProvider:
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

    async def generate_stream(self, request: ProviderRequest) -> AsyncGenerator[str, None]:
        """Stream tokens from OpenRouter as an async generator of text chunks."""
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

        payload_base: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "stream": True,
        }
        provider_routing = self._provider_routing_payload(request.openrouter_routing)
        if provider_routing:
            payload_base["provider"] = provider_routing
        if plugins and self.supports_plugins:
            payload_base["plugins"] = plugins
        if tools:
            payload_base["tools"] = tools
            payload_base["tool_choice"] = "auto"

        # Groq "thinker": disable reasoning when the user turned it off OR on the
        # low-latency channels. Only for Groq (OpenRouter uses a different `reasoning`
        # mechanism and would reject reasoning_effort). Streaming posts to the real API,
        # so this is the actual field, not an internal hint.
        if self.provider_id == "groq":
            model_id = str(model or "").lower()
            is_reasoning = any(tag in model_id for tag in ("qwen3", "qwen/qwen3", "gpt-oss", "deepseek-r1", "-r1"))
            channel = str(getattr(request, "channel", "") or "").strip().lower()
            thinking_enabled = bool(getattr(request, "thinking", True))
            if is_reasoning:
                if not thinking_enabled:
                    payload_base["reasoning_effort"] = "none"
                elif channel in {"voice", "terminal_agent"}:
                    payload_base["reasoning_effort"] = "low"

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
            while not done:
                chunk = await loop.run_in_executor(None, response.read, 4096)
                if not chunk:
                    break
                decoded = chunk.decode("utf-8", errors="replace")
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

                    # Real tool-call detection: OpenRouter streams tool calls in
                    # delta.tool_calls (not delta.content). When one appears, stop
                    # streaming partial text and delegate to the non-streaming loop,
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
                full_response = await loop.run_in_executor(
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
                        channel=getattr(request, "channel", ""),
                        thinking=getattr(request, "thinking", True),
                    ),
                )
                final_text = self._response_text(full_response)
                if request.on_activity is not None:
                    tool_count = len(request.tool_runs)
                    await request.on_activity({
                        "event": "tools_finished",
                        "label": f"{tool_count} chamada{'s' if tool_count != 1 else ''} concluída{'s' if tool_count != 1 else ''}",
                        "detail": "Preparando a resposta final.",
                    })
                if final_text:
                    yield final_text
                return
        except urllib.error.HTTPError as exc:
            # Surface the real OpenRouter error body (it explains WHY: e.g. "no
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

    def _system_prompt(
        self,
        request: ProviderRequest,
        *,
        model_info: dict[str, Any] | None,
        tools_enabled: bool,
        tools_supported: bool,
    ) -> str:
        """Build provider-specific instructions without Gemini-only image XML rules."""
        base = build_provider_system_prompt(self.provider_id)
        style = channel_style_hint(request.channel, call_mode=getattr(request, "call_mode", False))
        capabilities = self._capabilities_payload(model_info)
        capability_hint = (
            f"\n\n[{self.provider_status_title}]\n"
            f"You are running through {self.provider_label}, not direct Gemini API.\n"
            "Do not use Gemini Google Search, Gemini Code Execution, Gemini URL Context, or Gemini server-side tools.\n"
            "Only use actual tool calls provided in this request. Never write pseudo calls such as terminal_run(...) as visible text.\n"
            f"Current model capabilities: vision={capabilities['supports_image']}, files={capabilities['supports_pdf']}, tools={capabilities['supports_function_calling']}.\n"
            "When user sends large text (e.g. news, articles) to 'read' or process directly: just acknowledge internally and respond based on content if relevant. Do NOT output image prompts, XML tags, or unrelated generations. Process as normal conversation input."
        )

        # Add screen vision behavior hint if screen capture is present in attachments (for call + watching screen use case)
        has_screen = any(
            isinstance(item, dict) and str(item.get("name") or "").startswith("screen_capture")
            for item in (request.attachments or [])
        )
        if has_screen and capabilities.get("supports_image"):
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

    @staticmethod
    def _capabilities_payload(model_info: dict[str, Any] | None) -> dict[str, Any]:
        """Expose OpenRouter model capabilities using the selector capability keys."""
        input_modalities = model_info.get("inputModalities") if isinstance(model_info, dict) else []
        return {
            "multimodal_input": bool(model_info and len(input_modalities) > 1),
            "supports_image": bool(model_info and model_info.get("supportsVision")),
            "supports_audio": False,
            "supports_video": False,
            "supports_pdf": bool(model_info and model_info.get("supportsDocuments")),
            "supports_native_web_search": False,
            "supports_streaming": True,
            "supports_structured_output": bool(model_info and "response_format" in model_info.get("supportedParameters", [])),
            "supports_function_calling": bool(model_info and model_info.get("supportsTools")),
            "supports_code_execution": False,
            "supports_image_generation": False,
            "supports_video_generation": False,
            "supports_tts": False,
            "supports_live_voice": False,
            "supports_memory_embeddings": False,
            "supports_rag": False,
        }

    def _catalog_model(self, model_id: str) -> dict[str, Any] | None:
        """Read provider model metadata from the dynamic catalog."""
        return get_openrouter_model(model_id)

    def _custom_model_info(self, memory: Any, model_id: str) -> dict[str, Any] | None:
        """Read OpenRouter custom model capabilities persisted by the Control Center."""
        if memory is None:
            return None
        try:
            custom_models = memory.get_setting("custom_models", []) or []
        except Exception:
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
        """Build a data URL accepted by OpenRouter multimodal content parts."""
        return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"

    def _attachment_parts(self, attachments: list[dict[str, Any]], *, model_info: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Convert local attachments into OpenRouter content parts and plugins."""
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

    def _build_messages(self, request: ProviderRequest, *, model_info: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build OpenRouter messages and attach files only to the latest user turn."""
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

        # Native web search via the OpenRouter "web" plugin (works on any model,
        # billed per search). Mirrors the Gemini native-search toggle in the chat.
        if self.supports_plugins and str(request.native_search_mode or "off").lower() in {"auto", "force"}:
            plugins.append({"id": "web", "max_results": 5})

        return messages, plugins

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
            pass
        return self.tool_rounds

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
    def _provider_for(provider_id: str) -> "OpenRouterProvider | None":
        """Return an OpenAI-compatible provider instance for the agent tool loop.

        Only OpenAI-compatible providers (OpenRouter, Groq) share ``_run_completion_loop``
        and the message/tool schema built here, so those are the only valid agent
        targets. Anything else (e.g. gemini_api) returns None → caller keeps the main
        provider.
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

    @staticmethod
    def _tool_arguments(value: Any) -> dict[str, Any]:
        """Accept OpenRouter tool arguments as either a JSON string or an already-decoded object."""
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value or "{}")
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

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
            query = str(
                args.get("query")
                or args.get("q")
                or args.get("search")
                or args.get("task")
                or args.get("url")
                or args.get("tool")
                or ""
            )
        return {
            "tool": name,
            "ok": ok,
            "summary": summary,
            "query": query,
            "sources": extract_sources_from_mcp(result),
        }

    @staticmethod
    def _append_terminal_event(memory: Any, *, kind: str, source: str, status: str, tool_name: str, display_text: str, metadata: dict[str, Any]) -> None:
        """Mirror OpenRouter local tool calls into Terminal Agent events."""
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

    def _tool_schemas_and_runners(self, request: ProviderRequest, *, supports_tools: bool) -> tuple[list[dict[str, Any]], dict[str, Callable[[dict[str, Any]], dict[str, Any]]]]:
        """Expose MCP + local hands tools when model capabilities allow it.
        Tools are skipped entirely for models the catalog reports as not supporting tool calls.
        """
        connections = {}
        if request.memory is not None:
            try:
                raw = request.memory.get_setting("connections_config", {}) or {}
                from hana_agent_oss.api.routers.config import normalize_connections_config
                connections = normalize_connections_config(raw)
            except Exception:
                connections = {}

        if not getattr(request, "allow_tools", True):
            return [], {}

        tools: list[dict[str, Any]] = []
        runners: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        tools.extend(mcp_openai_schemas())
        # tool_runs are captured centrally in _run_completion_loop (covers every tool),
        # so the MCP runner does not need its own collector here (avoids double-count).
        runners.update(mcp_openai_runners(request.memory))

        if not supports_tools:
            return [], {}

        # === Hana's local hands (lean in-process executor; replaces Omni) ===
        # Added last so it never disturbs the leading tool bundle order.
        if bool(connections.get("localHands", True)):
            from hana_agent_oss.tools.terminal_tools import (
                inspect_dir as _terminal_inspect_dir,
                run_command as _terminal_run_command,
            )

            tools.append({
                "type": "function",
                "function": {
                    "name": "terminal_run",
                    "description": (
                        "Roda um comando no PC da Operador (Windows). Tem timeout e limite de saída. "
                        "Use shell='powershell' p/ PowerShell. ANTES de ações perigosas (deletar, formatar, "
                        "admin, mexer em credenciais/.env): investigue, mostre o que vai fazer e confirme com a usuária."
                    ),
                    "parameters": {
                        "type": "object",
                        "required": ["command"],
                        "properties": {
                            "command": {"type": "string", "description": "Comando a executar"},
                            "cwd": {"type": "string", "description": "Pasta de trabalho (opcional)"},
                            "shell": {"type": "string", "enum": ["cmd", "powershell", "bash"]},
                            "timeout": {"type": "integer", "description": "Segundos até interromper (padrão 60, máx 600)"},
                        },
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "terminal_inspect_dir",
                    "description": "Lista o conteúdo de uma pasta (um nível) para inspeção rápida.",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string", "description": "Caminho da pasta"}},
                    },
                },
            })

            def run_terminal(args: dict[str, Any]) -> dict[str, Any]:
                command = str(args.get("command") or "").strip()
                self._append_terminal_event(
                    request.memory,
                    kind="tool_call",
                    source="local_hands",
                    status="running",
                    tool_name="terminal.run",
                    display_text=f"Rodando: {command[:240]}",
                    metadata={"shell": str(args.get("shell") or "")},
                )
                result = _terminal_run_command(args)
                result_dict = result.to_dict()
                self._append_terminal_event(
                    request.memory,
                    kind="tool_result",
                    source="local_hands",
                    status="success" if result.ok else "failed",
                    tool_name="terminal.run",
                    display_text=str(result.output.get("stdout") or result.error or "Comando finalizado."),
                    metadata={"toolResult": result_dict},
                )
                return result_dict

            def run_inspect(args: dict[str, Any]) -> dict[str, Any]:
                return _terminal_inspect_dir(args).to_dict()

            runners["terminal_run"] = run_terminal
            runners["terminal_inspect_dir"] = run_inspect

            # === File read/write (atomic, UTF-8) ===
            # Writing code/text via the terminal (PowerShell here-strings) corrupts content:
            # it eats $variables, turns backticks into escapes, mangles accents (mojibake) and
            # blows up on large files (WinError 206). These tools take the content as a plain
            # JSON argument, so there is no shell escaping at all — one clean write.
            from hana_agent_oss.tools.file_tools import (
                file_exists as _file_exists,
                file_read as _file_read,
                file_write as _file_write,
            )

            tools.append({
                "type": "function",
                "function": {
                    "name": "file_write",
                    "description": (
                        "Cria ou sobrescreve um arquivo de texto/código com o conteúdo EXATO informado "
                        "(UTF-8, cria as pastas automaticamente). USE ISTO para escrever HTML/CSS/JS/Python/etc — "
                        "NUNCA jogue código pelo terminal_run com here-string (@\"...\"@), pois isso corrompe "
                        "variáveis $, crases e acentos. Uma chamada basta por arquivo."
                    ),
                    "parameters": {
                        "type": "object",
                        "required": ["path", "content"],
                        "properties": {
                            "path": {"type": "string", "description": "Caminho completo do arquivo"},
                            "content": {"type": "string", "description": "Conteúdo completo do arquivo"},
                        },
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "file_read",
                    "description": "Lê um arquivo de texto e retorna o conteúdo (UTF-8).",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string", "description": "Caminho do arquivo"}},
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "file_exists",
                    "description": "Verifica se um caminho existe (arquivo ou pasta).",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string", "description": "Caminho a verificar"}},
                    },
                },
            })

            def run_file_write(args: dict[str, Any]) -> dict[str, Any]:
                path = str(args.get("path") or "").strip()
                self._append_terminal_event(
                    request.memory,
                    kind="tool_call",
                    source="local_hands",
                    status="running",
                    tool_name="file.write",
                    display_text=f"Escrevendo arquivo: {path[:240]}",
                    metadata={},
                )
                result = _file_write(args)
                result_dict = result.to_dict()
                self._append_terminal_event(
                    request.memory,
                    kind="tool_result",
                    source="local_hands",
                    status="success" if result.ok else "failed",
                    tool_name="file.write",
                    display_text=(f"Arquivo salvo: {path}" if result.ok else (result.error or "Falha ao escrever.")),
                    metadata={"toolResult": result_dict},
                )
                return result_dict

            runners["file_write"] = run_file_write
            runners["file_read"] = lambda args: _file_read(args).to_dict()
            runners["file_exists"] = lambda args: _file_exists(args).to_dict()

            # === Co-piloto: digitar pela Operador (teclado real) ===
            from hana_agent_oss.tools.keyboard_tools import keyboard_type as _keyboard_type

            tools.append({
                "type": "function",
                "function": {
                    "name": "keyboard_type",
                    "description": (
                        "Digita um texto NO TECLADO de verdade, letra por letra, dentro do campo que a "
                        "Operador deixou focado/clicado na tela dela (caixa de resposta, formulário, editor). "
                        "Use quando ela pedir 'digita pra mim', 'responde essa pergunta aí', 'escreve isso'. "
                        "Suporta acentos e pontuação. Quebras de linha (\\n): newline_mode='space' (padrão, vira espaço), "
                        "'shift_enter' (quebra linha SEM enviar — use para texto multilinha em chats/editores) ou "
                        "'enter' (Enter real — ENVIA formulários, só se a Operador mandar enviar). "
                        "Ela pode apertar ESC para abortar a digitação."
                    ),
                    "parameters": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {
                            "text": {"type": "string", "description": "Texto exato a digitar"},
                            "cps": {"type": "number", "description": "Velocidade em caracteres/segundo (padrão 40)"},
                            "newline_mode": {"type": "string", "enum": ["space", "shift_enter", "enter"], "description": "Como digitar \\n (padrão space)"},
                            "start_delay": {"type": "number", "description": "Segundos de espera antes de começar (padrão 1.2)"},
                        },
                    },
                },
            })

            def run_keyboard_type(args: dict[str, Any]) -> dict[str, Any]:
                preview = str(args.get("text") or "")[:120]
                self._append_terminal_event(
                    request.memory,
                    kind="tool_call",
                    source="local_hands",
                    status="running",
                    tool_name="keyboard.type",
                    display_text=f"Digitando pela Operador: {preview}...",
                    metadata={},
                )
                result = _keyboard_type(args)
                result_dict = result.to_dict()
                typed = (result.output or {}).get("typed_chars", 0)
                self._append_terminal_event(
                    request.memory,
                    kind="tool_result",
                    source="local_hands",
                    status="success" if result.ok else "failed",
                    tool_name="keyboard.type",
                    display_text=(f"Digitei {typed} caracteres." if result.ok else (result.error or "Falha ao digitar.")),
                    metadata={"toolResult": result_dict},
                )
                return result_dict

            runners["keyboard_type"] = run_keyboard_type

            # === Co-piloto: mouse + olho (visão aponta, mouse clica) ===
            from hana_agent_oss.tools.mouse_tools import (
                mouse_click as _mouse_click,
                mouse_scroll as _mouse_scroll,
                screen_find as _screen_find,
            )

            tools.append({
                "type": "function",
                "function": {
                    "name": "screen_find",
                    "description": (
                        "OLHO do co-piloto: tira um print do monitor ativo e pergunta ao modelo de visão "
                        "ONDE está um elemento (botão, X de fechar, campo, link). Retorna JSON com x/y "
                        "normalizados 0-1000 prontos para usar em mouse_click. Use ANTES de clicar em "
                        "qualquer coisa — nunca chute coordenadas. Funciona mesmo quando o seu próprio "
                        "modelo não tem visão (a consulta vai para o modelo de visão configurado)."
                    ),
                    "parameters": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {
                            "query": {"type": "string", "description": "Descrição do elemento, ex: 'botão X de fechar da aba do Chrome'"},
                        },
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "mouse_click",
                    "description": (
                        "Clica na tela da Operador nas coordenadas x/y normalizadas 0-1000 do monitor ativo "
                        "(as mesmas que screen_find retorna). O cursor teleporta e clica na hora. "
                        "Obtenha as coordenadas via screen_find primeiro; após o clique, se for fazer outra "
                        "ação dependente, chame screen_find de novo para conferir o novo estado da tela."
                    ),
                    "parameters": {
                        "type": "object",
                        "required": ["x", "y"],
                        "properties": {
                            "x": {"type": "number", "description": "0-1000 (esquerda→direita)"},
                            "y": {"type": "number", "description": "0-1000 (topo→baixo)"},
                            "button": {"type": "string", "enum": ["left", "right", "middle"]},
                            "double": {"type": "boolean", "description": "Clique duplo"},
                        },
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "mouse_scroll",
                    "description": "Rola a tela (scroll). amount negativo = para baixo, positivo = para cima. Opcionalmente em x/y (0-1000).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "amount": {"type": "integer", "description": "Cliques de scroll, ex: -5 desce, 5 sobe"},
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                        },
                    },
                },
            })

            def _copilot_runner(name: str, func) -> Callable[[dict[str, Any]], dict[str, Any]]:
                def run(args: dict[str, Any]) -> dict[str, Any]:
                    detail = str(args.get("query") or f"x={args.get('x')} y={args.get('y')}")[:160]
                    self._append_terminal_event(
                        request.memory,
                        kind="tool_call",
                        source="local_hands",
                        status="running",
                        tool_name=name,
                        display_text=f"{name}: {detail}",
                        metadata={},
                    )
                    result = func(args, request.memory)
                    result_dict = result.to_dict()
                    self._append_terminal_event(
                        request.memory,
                        kind="tool_result",
                        source="local_hands",
                        status="success" if result.ok else "failed",
                        tool_name=name,
                        display_text=(str((result.output or {}).get("answer") or "ok") if result.ok else (result.error or "falhou"))[:300],
                        metadata={"toolResult": result_dict},
                    )
                    return result_dict
                return run

            runners["screen_find"] = _copilot_runner("screen.find", _screen_find)
            runners["mouse_click"] = _copilot_runner("mouse.click", _mouse_click)
            runners["mouse_scroll"] = _copilot_runner("mouse.scroll", _mouse_scroll)

        # === Reminders / alarms (in-process scheduler) ===
        from hana_agent_oss.tools.reminder_tools import (
            reminder_cancel as _reminder_cancel,
            reminder_create as _reminder_create,
            reminder_list as _reminder_list,
        )

        tools.append({
            "type": "function",
            "function": {
                "name": "reminder_create",
                "description": (
                    "Cria um lembrete/alarme. Informe 'at' (HH:MM), 'in_minutes' ou 'in_seconds'. "
                    "repeat='daily' repete todo dia. A Hana avisa por voz (se TTS ligado) e no painel quando chegar a hora."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string", "description": "O que lembrar"},
                        "at": {"type": "string", "description": "Hora HH:MM (hoje, ou amanhã se já passou)"},
                        "in_minutes": {"type": "number"},
                        "in_seconds": {"type": "number"},
                        "date": {"type": "string", "description": "Data opcional YYYY-MM-DD"},
                        "repeat": {"type": "string", "enum": ["none", "daily"]},
                    },
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "reminder_list",
                "description": "Lista os lembretes ativos.",
                "parameters": {"type": "object", "properties": {"include_done": {"type": "boolean"}}},
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "reminder_cancel",
                "description": "Cancela um lembrete pelo id.",
                "parameters": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
            },
        })
        runners["reminder_create"] = lambda args: _reminder_create(args).to_dict()
        runners["reminder_list"] = lambda args: _reminder_list(args).to_dict()
        runners["reminder_cancel"] = lambda args: _reminder_cancel(args).to_dict()

        # === Avisar a Operador no Discord (DM, mencionando ela) ===
        # Hana decide quando disparar (ex.: depois de criar um alarme). O bot do
        # Discord entrega a DM; aqui só enfileiramos na outbox.
        from hana_agent_oss.tools.discord_tools import discord_notify as _discord_notify

        tools.append({
            "type": "function",
            "function": {
                "name": "discord_notify",
                "description": (
                    "Envia uma mensagem direta (DM) pra Operador no Discord, mencionando ela. "
                    "Use quando VOCE decidir avisa-la de algo importante por fora (ex.: confirmar "
                    "que criou um alarme, lembrar de uma pendencia). Nao e automatico — voce escolhe a hora. "
                    "Escreva a mensagem ja pronta, curta e em pt-BR."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["message"],
                    "properties": {"message": {"type": "string", "description": "A mensagem pra Operador"}},
                },
            },
        })

        def run_discord_notify(args: dict[str, Any]) -> dict[str, Any]:
            message = str(args.get("message") or "").strip()
            result = _discord_notify(request.memory, message)
            self._append_terminal_event(
                request.memory,
                kind="tool_result",
                source="discord",
                status="success" if result.get("ok") else "failed",
                tool_name="discord.notify",
                display_text=(f"DM enfileirada pra Operador: {message[:160]}" if result.get("ok") else str(result.get("error"))),
                metadata={"toolResult": result},
            )
            return result

        runners["discord_notify"] = run_discord_notify

        # === Mãos na memória (a Hana gerencia as próprias lembranças) ===
        # Sempre expostas (memória é núcleo, não módulo opcional). Operam na
        # MemoryStore viva da request; o painel Memória mostra tudo depois.
        if request.memory is not None:
            mem_store = request.memory

            tools.append({
                "type": "function",
                "function": {
                    "name": "memory_search",
                    "description": (
                        "Busca nas suas memórias persistentes (perfil, fatos, diários, anotações). "
                        "Use quando a Operador perguntar 'o que você lembra de X', quando precisar "
                        "conferir um fato antigo, ou ANTES de corrigir/apagar uma memória (para achar o id)."
                    ),
                    "parameters": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {
                            "query": {"type": "string", "description": "Termos de busca"},
                            "limit": {"type": "integer", "description": "Máx. resultados (padrão 8)"},
                        },
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "memory_save",
                    "description": (
                        "Salva uma memória persistente nova (fato, preferência, decisão, contexto importante). "
                        "category: preference_like, preference_dislike, personal_fact, ou general. "
                        "Use para registrar na hora algo que a Operador pedir para você lembrar."
                    ),
                    "parameters": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {
                            "text": {"type": "string", "description": "O fato, curto e específico"},
                            "category": {"type": "string", "enum": ["preference_like", "preference_dislike", "personal_fact", "general"]},
                            "importance": {"type": "string", "enum": ["low", "medium", "high"]},
                        },
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "memory_update",
                    "description": (
                        "Corrige o texto de uma memória existente pelo id (use memory_search antes para achar). "
                        "Use quando a Operador disser que uma lembrança sua está errada ou desatualizada."
                    ),
                    "parameters": {
                        "type": "object",
                        "required": ["id", "text"],
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string", "description": "Novo texto corrigido"},
                        },
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "memory_delete",
                    "description": (
                        "Apaga (soft-delete, recuperável) uma memória pelo id. Use memory_search antes. "
                        "Confirme com a Operador antes de apagar, a não ser que ela já tenha mandado apagar."
                    ),
                    "parameters": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "memory_pin",
                    "description": "Fixa (pinned=true) ou desafixa uma memória. Fixadas nunca decaem e rankeiam mais alto — use para 'nunca esqueça isso'.",
                    "parameters": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {"id": {"type": "string"}, "pinned": {"type": "boolean"}},
                    },
                },
            })

            def _mem_compact(memory_item: dict[str, Any]) -> dict[str, Any]:
                return {
                    "id": memory_item.get("id"),
                    "text": memory_item.get("text"),
                    "category": memory_item.get("category"),
                    "importance": memory_item.get("importance"),
                    "pinned": memory_item.get("pinned"),
                    "updated_at": memory_item.get("updated_at"),
                }

            def run_memory_search(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    results = mem_store.search(str(args.get("query") or ""), limit=self._safe_int(args.get("limit"), 8))
                    return {"ok": True, "memories": [_mem_compact(m) for m in results]}
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "error": str(exc)}

            def run_memory_save(args: dict[str, Any]) -> dict[str, Any]:
                text = str(args.get("text") or "").strip()
                if not text:
                    return {"ok": False, "error": "text obrigatório"}
                try:
                    saved = mem_store.add_memory(
                        text,
                        kind="long_term",
                        source="hana_chat_tool",
                        metadata={
                            "category": str(args.get("category") or "general"),
                            "importance": str(args.get("importance") or "medium"),
                        },
                    )
                    return {"ok": True, "memory": _mem_compact(saved)}
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "error": str(exc)}

            def run_memory_update(args: dict[str, Any]) -> dict[str, Any]:
                memory_id = str(args.get("id") or "").strip()
                text = str(args.get("text") or "").strip()
                if not memory_id or not text:
                    return {"ok": False, "error": "id e text obrigatórios"}
                try:
                    updated = mem_store.add_memory(text, memory_id=memory_id, source="hana_chat_tool")
                    return {"ok": True, "memory": _mem_compact(updated)}
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "error": str(exc)}

            def run_memory_delete(args: dict[str, Any]) -> dict[str, Any]:
                memory_id = str(args.get("id") or "").strip()
                if not memory_id:
                    return {"ok": False, "error": "id obrigatório"}
                deleted = mem_store.delete_memory(memory_id, hard=False)
                return {"ok": bool(deleted), "deleted": bool(deleted), "error": None if deleted else "memória não encontrada"}

            def run_memory_pin(args: dict[str, Any]) -> dict[str, Any]:
                memory_id = str(args.get("id") or "").strip()
                if not memory_id:
                    return {"ok": False, "error": "id obrigatório"}
                pinned = bool(args.get("pinned", True))
                updated = mem_store.pin_memory(memory_id, pinned=pinned)
                return {"ok": bool(updated), "pinned": pinned, "error": None if updated else "memória não encontrada"}

            runners["memory_search"] = run_memory_search
            runners["memory_save"] = run_memory_save
            runners["memory_update"] = run_memory_update
            runners["memory_delete"] = run_memory_delete
            runners["memory_pin"] = run_memory_pin

        if not tools and not supports_tools:
            return [], {}

        return [self._sanitize_tool_schema(schema) for schema in tools], runners

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

    def _local_tool_instruction(self, *, enabled: bool, supported: bool) -> str:
        """Explain local tool availability for OpenRouter models."""
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

    def _headers(self) -> dict[str, str]:
        """Build provider request headers without exposing credentials."""
        return openrouter_headers(include_auth=True)

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

    def _run_completion_loop(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        plugins: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_runners: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        memory: Any,
        tool_runs: list[dict[str, Any]] | None = None,
        provider_routing: dict[str, Any] | None = None,
        channel: str = "",
        thinking: bool = True,
    ) -> dict[str, Any]:
        """Run a bounded OpenRouter tool-call loop and return the final response.

        When ``tool_runs`` is provided, every executed tool call records a compact
        run entry ({tool, ok, summary, query, sources}) so the chat can render a
        tool-activity card. This is the single capture point for all tools
        (MCP/Tavily, local hands).
        """
        payload_base: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if channel:
            # Internal hint (stripped before any HTTP call) so the provider can tune
            # latency per channel — e.g. disable reasoning on voice/terminal.
            payload_base["_channel"] = channel
        # Internal hint (stripped before HTTP): user's Groq "thinker" toggle.
        payload_base["_thinking"] = bool(thinking)
        routing_payload = self._provider_routing_payload(provider_routing)
        if routing_payload:
            payload_base["provider"] = routing_payload
        if plugins and self.supports_plugins:
            payload_base["plugins"] = plugins
        if tools:
            payload_base["tools"] = tools
            payload_base["tool_choice"] = "auto"

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
                runner = tool_runners.get(name)
                args = self._tool_arguments(function.get("arguments"))
                if runner is None:
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

    @staticmethod
    def _response_message(response_data: dict[str, Any]) -> dict[str, Any]:
        """Extract the first OpenRouter assistant message."""
        choices = response_data.get("choices") if isinstance(response_data, dict) else None
        if not isinstance(choices, list) or not choices:
            return {}
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        return message

    @classmethod
    def _response_text(cls, response_data: dict[str, Any]) -> str:
        """Extract normalized text from OpenRouter/Groq chat/non-chat choices.

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
