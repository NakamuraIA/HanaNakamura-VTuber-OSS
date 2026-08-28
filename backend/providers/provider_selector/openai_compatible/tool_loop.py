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




class ToolLoopSupport:
    def _post_chat_completion(self, payload: dict[str, Any], *, memory: Any = None) -> dict[str, Any]:
        """Send one non-streaming Chat Completions request to the provider."""
        # Strip internal-only hints (prefixed with '_', e.g. _channel) so they never
        # reach the provider API as unknown fields.
        payload = {k: v for k, v in payload.items() if not str(k).startswith("_")}
        raw_body = ""
        for attempt in (0, 1):
            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                self._request_url(memory),
                data=body,
                headers=self._request_headers(memory),
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.http_timeout_seconds) as response:
                    raw_body = response.read().decode("utf-8", errors="replace")
                break
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                except Exception:
                    detail = ""
                if attempt == 0 and "reasoning" in payload and self._reasoning_mandatory_error(detail):
                    payload = {k: v for k, v in payload.items() if k != "reasoning"}
                    continue
                # Re-levanta com o corpo preservado (ja foi lido acima) pro chamador
                # conseguir mostrar o erro real do provider.
                import io
                raise urllib.error.HTTPError(exc.url, exc.code, exc.msg, exc.hdrs, io.BytesIO(detail.encode("utf-8")))
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

                content_parts: list[str] = []
                reasoning_parts: list[str] = []
                tool_call_acc: dict[int, dict[str, Any]] = {}

                response = None
                error_text = ""
                for attempt in (0, 1):
                    body = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(
                        self._request_url(memory),
                        data=body,
                        headers=self._request_headers(memory),
                        method="POST",
                    )
                    try:
                        response = urllib.request.urlopen(req, timeout=self.http_timeout_seconds)
                        break
                    except urllib.error.HTTPError as exc:
                        try:
                            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                        except Exception:
                            detail = ""
                        # Reasoning obrigatorio no endpoint + toggle Pensar off: tira o
                        # knob (desta rodada e das proximas) e tenta de novo.
                        if attempt == 0 and "reasoning" in payload and self._reasoning_mandatory_error(detail):
                            payload.pop("reasoning", None)
                            payload_base.pop("reasoning", None)
                            continue
                        error_text = f"[ERRO: {self.provider_id}_http_{exc.code}:{detail[:600] or exc.reason}]"
                if response is None:
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

                        # Reasoning tokens (reasoning_content=DeepSeek, reasoning=Kimi/unificado)
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                        if isinstance(reasoning, str) and reasoning:
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
                        "e peça para a Nakamura mandar 'continua' para você terminar no próximo turno. "
                        "É PROIBIDO afirmar que terminou ou prometer que 'vai fazer agora'."
                    ),
                }
            )
            final_payload = dict(payload_base)
            final_payload["messages"] = messages
            final_payload["tool_choice"] = "none"
            final_payload["stream"] = False  # force non-streaming for the final forced answer
            try:
                return self._post_chat_completion(final_payload, memory=memory)
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
            last_response = self._post_chat_completion(payload, memory=memory)
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
                    "e peça para a Nakamura mandar 'continua' para você terminar no próximo turno. "
                    "É PROIBIDO afirmar que terminou ou prometer que 'vai fazer agora'."
                ),
            }
        )
        final_payload = dict(payload_base)
        final_payload["messages"] = messages
        final_payload["tool_choice"] = "none"
        try:
            return self._post_chat_completion(final_payload, memory=memory)
        except Exception:
            return last_response


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
            from backend.providers.provider_selector.gemini_api.provider import GeminiApiProvider
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


    def _image_tool_instruction_for_request(self, request: Any) -> str:
        """Return image instruction tailored to whether native tools are available.

        When the provider has function-calling tools enabled AND an image_service
        is attached to the request, guide the model to use native function calls
        (gerar_imagem / editar_imagem / gerar_imagem_personagem / editar_imagem_personagem).
        Otherwise fall back to the XML text-tag manual (used by Gemini and tool-less providers).
        """
        has_image_service = bool(getattr(request, "image_service", None))
        if has_image_service:
            return (
                "\n\n[IMAGE TOOL — ABSOLUTE RULES — READ CAREFULLY]\n"
                "STOP ROLEPLAYING IMAGE GENERATION. You are NOT an image generator.\n"
                "You are a TEXT model that can CALL an external image tool.\n\n"
                "CRITICAL: The user CAN SEE whether you actually called the tool or not.\n"
                "If you describe an image without calling the tool, the user will KNOW you are lying.\n"
                "LYING about image generation WILL make the user EXTREMELY ANGRY. DO NOT DO IT.\n\n"
                "RULES:\n"
                "1. When asked to generate an image, your ONLY response is to call the tool. Nothing else.\n"
                "2. After calling, respond with EXACTLY: 'Chamei a tool. Resultado: [ok/error]'\n"
                "   Do NOT describe the image. Do NOT say 'PASSOU'. Do NOT add emojis.\n"
                "3. If the result is ok but path is empty, say: 'ok mas path vazio'\n"
                "4. If the result is an error, paste the error string.\n"
                "5. NEVER claim an image was generated unless the tool returned ok:true AND a path.\n\n"
                "Tools:\n"
                "- gerar_imagem(prompt) — generic image generation\n"
                "- gerar_imagem_personagem(character, mode, prompt) — character image\n"
            )
        return self._image_tool_instruction()


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
        agent silently die mid-task; Nakamura tunes this from the panel.
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
            # Raw runner output — chat.py precisa disso pra extrair "path" de
            # tools de imagem (gerar_imagem etc) e anexar a mídia no chat.
            "result": result if isinstance(result, dict) else {},
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
            from backend.providers.provider_selector.openrouter.provider import OpenRouterProvider
            return OpenRouterProvider()
        if pid in ("groq", "groqcloud", "groq_cloud", "glock"):
            from backend.providers.provider_selector.groq.provider import GroqProvider
            return GroqProvider()
        if pid in ("deepseek", "deepseek_official", "deep_seek"):
            from backend.providers.provider_selector.deepseek.provider import DeepSeekProvider
            return DeepSeekProvider()
        return None


    @staticmethod
    def _append_terminal_event(memory: Any, *, kind: str, source: str, status: str, tool_name: str, display_text: str, metadata: dict[str, Any]) -> None:
        """Mirror provider local tool calls into Terminal Agent events."""
        if memory is None:
            return
        try:
            from backend.api.services.terminal_agent import append_terminal_event

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

