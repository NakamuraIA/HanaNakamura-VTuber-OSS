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

from backend.api.services.unified_history import channel_style_hint
from backend.persona import build_provider_system_prompt
from backend.providers.contracts import ProviderRequest, ProviderResponse
from backend.tools.mcp_provider_tools import extract_sources_from_mcp
from .attachments import AttachmentSupport
from .messages import MessageSupport
from .tool_loop import ToolLoopSupport
# build_tool_schemas_and_runners is imported lazily inside _tool_schemas_and_runners.


logger = logging.getLogger(__name__)

SUPPORTED_TEXT_ATTACHMENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/xml",
}


class OpenAICompatibleProvider(AttachmentSupport, MessageSupport, ToolLoopSupport):
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

    def _request_url(self, memory: Any | None = None) -> str:
        """Return the endpoint for one request.

        Most providers have one fixed endpoint.  Providers with a persisted
        region selection can override this hook without mutating a shared
        provider instance.
        """
        return self.chat_completions_url

    def _request_headers(self, memory: Any | None = None) -> dict[str, str]:
        """Return headers for one request; subclasses may use saved settings."""
        return self._headers()

    def _api_key(self, memory: Any | None = None) -> str | None:
        """Return the credential for one request without exposing it in logs."""
        return os.environ.get(self.api_key_env)

    def _credentials_available(self, memory: Any | None = None) -> bool:
        return bool(self._api_key(memory))

    # ========================================================================
    # Public API
    # ========================================================================

    async def generate_stream(self, request: ProviderRequest) -> AsyncGenerator[str, None]:
        """Stream tokens from the provider as an async generator of text chunks."""
        api_key = self._api_key(request.memory)
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

        # Run blocking HTTP in thread to avoid freezing the async event loop
        loop = asyncio.get_running_loop()
        response = None
        try:
            for attempt in (0, 1):
                body = json.dumps(payload_base).encode("utf-8")
                req = urllib.request.Request(
                    self._request_url(request.memory),
                    data=body,
                    headers=self._request_headers(request.memory),
                    method="POST",
                )
                try:
                    response = await loop.run_in_executor(
                        None,
                        lambda: urllib.request.urlopen(req, timeout=self.http_timeout_seconds),
                    )
                    break
                except urllib.error.HTTPError as exc:
                    try:
                        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                    except Exception:
                        detail = ""
                    # Endpoint de reasoning obrigatorio (ex: Kimi K3) + toggle Pensar
                    # off: tira o knob e tenta de novo em vez de quebrar o turno.
                    if attempt == 0 and "reasoning" in payload_base and self._reasoning_mandatory_error(detail):
                        payload_base.pop("reasoning", None)
                        continue
                    import io
                    raise urllib.error.HTTPError(exc.url, exc.code, exc.msg, exc.hdrs, io.BytesIO(detail.encode("utf-8")))
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

                    # Reasoning tokens — forward to caller when requested.
                    # Campo varia por modelo: DeepSeek usa reasoning_content,
                    # Kimi/OpenRouter unificado usa reasoning.
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if isinstance(reasoning, str) and reasoning and request.on_reasoning is not None:
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
                    if candidate is not None and candidate._credentials_available(request.memory):
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
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        api_key = self._api_key(request.memory)
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


    # Escala unificada de esforço (OpenRouter). Definida na base pra o branch
    # openrouter funcionar mesmo quando o método mora aqui.
    OPENROUTER_REASONING_LEVELS = ("none", "minimal", "low", "medium", "high", "max")







    # ========================================================================
    # Generic helpers — shared by all OpenAI-compatible providers
    # ========================================================================





    def _tool_schemas_and_runners(self, request: ProviderRequest, *, supports_tools: bool) -> tuple[list[dict[str, Any]], dict[str, Callable[[dict[str, Any]], dict[str, Any]]]]:
        """Monta as ferramentas (schemas + runners). Lógica em tools_builder."""
        from .tools_builder import build_tool_schemas_and_runners

        return build_tool_schemas_and_runners(self, request, supports_tools=supports_tools)
