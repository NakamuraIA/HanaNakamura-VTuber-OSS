from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from hana_agent_oss.core.protocol import AgentRequest, AgentResponse
from hana_agent_oss.core.runtime import HanaAgentCore
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.attachments import AttachmentStore
from hana_agent_oss.modules.vision.image_service import ImageGenerationService
from hana_agent_oss.modules.vision.image_xml import extract_image_xml_actions, strip_image_xml_tags
from hana_agent_oss.memory.memory_xml import extract_memory_saves, strip_memory_xml_tags
from hana_agent_oss.tools.skill_tools import apply_skill_notes, strip_skill_xml_tags
from hana_agent_oss.providers import ProviderRequest, ProviderSelector
from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider
from hana_agent_oss.api.services.catalog import DEFAULT_CONNECTIONS, model_supports_vision
from hana_agent_oss.api.services.unified_history import build_memory_context_block, estimate_tokens, strip_leaked_terminal_events


PROVIDER_SELECTOR = ProviderSelector()

# Safety net: some weaker models occasionally emit a tool call as TEXT instead of
# doing a real function call (e.g. "<|terminal_run|{...}|>"). That text never runs
# and confuses the user, so we strip these leaked pseudo-tool tokens from the reply.
# The real fix is the persona rule + using a tool-capable model; this just keeps the
# UI clean if it slips through.
_LEAKED_TOOL_CALL_RE = re.compile(r"<\|\s*\w+.*?\|>", re.DOTALL)


def strip_leaked_tool_calls(text: str) -> str:
    cleaned = _LEAKED_TOOL_CALL_RE.sub("", str(text or ""))
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
ATTACHMENT_STORE = AttachmentStore()
LLM_PROVIDER_ALIASES = {
    "google_platform": "gemini_api",
    "google_cloud": "gemini_api",
    "google": "gemini_api",
    "google_ai_studio": "gemini_api",
    "gemini": "gemini_api",
    "open_router": "openrouter",
    "openrouters": "openrouter",
    "openrouter": "openrouter",
    "groq_cloud": "groq",
    "groqcloud": "groq",
    "glock": "groq",
    "groq": "groq",
}


def response_text(response: AgentResponse) -> str:
    if response.ok:
        return response.response or "Concluido."
    if response.error == "planner_not_connected":
        return (
            "Hana Agent OSS esta online como backend central. "
            "O planner deterministico respondeu, mas a conexao LLM/tool-calling completa ainda esta em migracao. "
            "Comandos estruturados disponiveis: tools, capabilities, file.read, file.write, memory.search, memory.compact e terminal.run."
        )
    return response.response or response.error or "Falha no Agent Core."


def agent_plan_payload(response: AgentResponse) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    if response.planner_result:
        action = response.planner_result.action
        steps.append(
            {
                "tool": action.tool_call.tool if action.tool_call else "agent_core.planner",
                "status": "planned",
                "risk": action.tool_call.risk if action.tool_call else "low",
                "summary": action.reason or action.message or action.type,
            }
        )
    if response.tool_result:
        steps.append(
            {
                "tool": response.tool_result.tool,
                "status": "success" if response.tool_result.ok else "failed",
                "risk": response.planner_result.action.tool_call.risk if response.planner_result and response.planner_result.action.tool_call else "low",
                "summary": response.tool_result.error or response.response,
            }
        )
    if response.verification:
        steps.append(
            {
                "tool": "agent_core.verifier",
                "status": "success" if response.verification.ok else "failed",
                "risk": "low",
                "summary": response.verification.message,
            }
        )
    if not steps:
        steps.append(
            {
                "tool": response.tool_result.tool if response.tool_result else "agent_core",
                "status": "ok" if response.ok else "pending",
                "risk": "low",
                "summary": response.response,
            }
        )
    return {
        "intent": response.planner_result.action.type if response.planner_result else "unknown",
        "steps": steps,
    }


def provider_plan_payload(provider: str, model: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {
        "intent": "llm_provider",
        "steps": [
            {
                "tool": f"llm.{provider}",
                "status": "success" if ok else "failed",
                "risk": "low",
                "summary": detail or model,
            }
        ],
    }


def image_plan_payload(operation: str, ok: bool, detail: str = "", *, status: str | None = None) -> dict[str, Any]:
    return {
        "intent": "image_generation",
        "steps": [
            {
                "tool": f"image.{operation}",
                "status": status or ("success" if ok else "failed"),
                "risk": "low" if ok else "medium",
                "summary": detail,
            }
        ],
    }


def _terminal_channels() -> set[str]:
    """Return channels that should mirror image XML actions into Terminal Agent events."""
    return {"terminal", "cli", "terminal_agent", "voice"}


def _append_image_terminal_event(memory: MemoryStore, operation: str, result) -> None:
    """Write an image XML execution result to the Terminal Agent log."""
    try:
        from hana_agent_oss.api.services.terminal_agent import append_terminal_event

        append_terminal_event(
            memory,
            {
                "kind": "tool_result",
                "source": "image_generation",
                "displayText": result.text,
                "speechText": "",
                "status": "success" if result.ok else "failed",
                "toolName": f"image.{operation}",
                "metadata": {"tts": False, "media": result.media, "error": result.error},
            },
        )
    except Exception:
        return


def _append_agent_core_terminal_events(memory: MemoryStore, response: AgentResponse) -> None:
    """Mirror Agent Core planning/tool events into the visible Terminal Agent log."""
    try:
        from hana_agent_oss.api.services.terminal_agent import append_terminal_event
    except Exception:
        return

    kind_by_type = {
        "request_received": "assistant_thought",
        "planner_result": "assistant_thought",
        "tool_call": "tool_call",
        "tool_result": "tool_result",
        "verification": "tool_result",
    }
    status_by_type = {
        "request_received": "planning",
        "planner_result": "planned",
        "tool_call": "running",
        "tool_result": "success",
        "verification": "verified",
    }

    for event in response.events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        tool_name = ""
        if isinstance(payload.get("tool_call"), dict):
            tool_name = str(payload["tool_call"].get("tool") or "")
        if isinstance(payload.get("tool_result"), dict):
            tool_name = str(payload["tool_result"].get("tool") or tool_name)
        status = status_by_type.get(event.type, "")
        if event.type == "tool_result" and isinstance(payload.get("tool_result"), dict) and payload["tool_result"].get("ok") is False:
            status = "failed"
        append_terminal_event(
            memory,
            {
                "kind": kind_by_type.get(event.type, "system"),
                "source": "agent_core",
                "displayText": event.message,
                "speechText": "",
                "toolName": tool_name,
                "status": status,
                "metadata": {"tts": False, "agentEvent": event.to_dict()},
            },
        )


def execute_image_xml_actions(
    actions: dict[str, list[str]],
    *,
    image_service: ImageGenerationService,
    attachments: list[dict[str, Any]],
    channel: str,
    memory: MemoryStore,
) -> list[dict[str, Any]]:
    """Execute extracted image XML actions and return normalized result metadata."""
    results: list[dict[str, Any]] = []
    operations = (
        ("gerar_imagem", "generate", lambda value: image_service.generate(value)),
        ("editar_imagem", "edit", lambda value: image_service.edit(value, attachments=attachments)),
        ("gerar_imagem_personagem", "character_generate", lambda value: image_service.generate_character(value)),
        ("editar_imagem_personagem", "character_edit", lambda value: image_service.edit_character(value, attachments=attachments)),
    )
    for tag_name, operation, handler in operations:
        for value in actions.get(tag_name, []):
            result = handler(value)
            if channel in _terminal_channels():
                if result.ok:
                    image_service.open_result(result, label="IMAGE GEN")
                _append_image_terminal_event(memory, operation, result)
            results.append(
                {
                    "tag": tag_name,
                    "operation": operation,
                    "ok": result.ok,
                    "text": result.text,
                    "error": result.error,
                    "model": result.model,
                    "media": result.media,
                    "savedPath": result.saved_path,
                }
            )
    return results


def should_use_agent_core(text: str, provider: str) -> bool:
    """Return true only when the caller explicitly selects Agent Core mode."""
    del text
    if provider in {"agent_core", "structured-planner", "structured_planner"}:
        return True
    return False


def normalize_llm_provider(provider: Any) -> str:
    """Normalize provider aliases used by chat, voice and frontend payloads."""
    value = str(provider or "").strip().lower()
    return LLM_PROVIDER_ALIASES.get(value, value or "gemini_api")


def provider_uses_gemini_only_features(provider: str) -> bool:
    """Return true only for the direct Gemini API provider."""
    return normalize_llm_provider(provider) == "gemini_api"


def provider_supports_native_search(provider: str) -> bool:
    """Providers with built-in web search: Gemini (grounding) and OpenRouter (web plugin)."""
    return normalize_llm_provider(provider) in {"gemini_api", "openrouter"}


def message_history(payload: dict[str, Any], text: str) -> list[dict[str, str]]:
    history = payload.get("history")
    messages: list[dict[str, str]] = []
    if isinstance(history, list):
        for item in history[-12:]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            # Truncate very long previous messages to prevent context bloat and weird generations
            # (e.g. random prompts or meta leakage when sending large texts for reading).
            if len(content) > 8000:
                content = content[:8000] + "... [conteúdo anterior truncado]"
            messages.append({"role": str(item.get("role") or "user"), "content": content})
    # Current text already truncated earlier if huge.
    messages.append({"role": "user", "content": text})
    return messages


def resolve_chat_attachments(payload: dict[str, Any], *, memory: MemoryStore, text: str, channel: str = "control_center") -> list[dict[str, Any]]:
    """Persist attachments the user actually uploaded this turn.

    IMPORTANT: there is NO keyword-based attachment recovery. The user explicitly
    forbids word triggers (e.g. typing "arquivo"/"áudio"/"imagem" must NEVER pull a
    stored media file into the turn — that used to break text-only turns). Attachments
    enter a turn ONLY when really uploaded in the payload. Any future "reuse last
    attachment" feature must be driven by an explicit tag/regex, not by words.
    """
    attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
    if attachments:
        return ATTACHMENT_STORE.save_many(attachments, memory=memory, channel=channel, user_text=text)
    return []


# Providers OpenAI-compativeis que sobem tokens via generate_stream (streaming real).
# Gemini fica de fora (entrega o texto inteiro de uma vez).
STREAMING_PROVIDERS = frozenset({"openrouter", "groq", "deepseek"})


async def handle_chat_payload(websocket: WebSocket, payload: dict[str, Any], *, core: HanaAgentCore, memory: MemoryStore) -> None:
    # Only the explicit Agent Core / tool path shows the "Agent Mode" planning card.
    # Plain chat turns stay clean: meta + text, no planning noise.
    provider = normalize_llm_provider(payload.get("provider") or "agent_core")
    is_agent_core = should_use_agent_core(str(payload.get("text") or ""), provider)
    if is_agent_core:
        await websocket.send_json({"type": "agent_status", "status": {"stage": "planning", "detail": "Agent Core recebeu a mensagem."}})

    # OpenRouter streams token deltas live; other providers return the full text in one shot
    # (the frontend still animates it letter-by-letter).
    use_stream = provider in STREAMING_PROVIDERS and not is_agent_core

    async def on_delta(token: str) -> None:
        await websocket.send_json({"type": "chunk", "content": token})

    async def on_activity(activity: dict[str, Any]) -> None:
        await websocket.send_json({"type": "activity", "activity": activity})

    if use_stream:
        await on_activity({"event": "model_started", "label": "Consultando o modelo", "detail": "Aguardando os primeiros tokens."})

    result = await run_text_turn(
        payload,
        core=core,
        memory=memory,
        on_delta=on_delta if use_stream else None,
        on_activity=on_activity if use_stream else None,
    )

    await websocket.send_json({"type": "meta", "meta": result["meta"]})
    if result.get("streamed"):
        # Deltas already streamed; send the cleaned authoritative text to replace the buffer
        # (strips image/memory XML tags that may have flashed mid-stream).
        await websocket.send_json({"type": "final", "content": result["text"]})
    else:
        await websocket.send_json({"type": "chunk", "content": result["text"]})

    if "media" in result and result["media"]:
        for media_item in result["media"]:
            await websocket.send_json({"type": "media", "media": media_item})

    # The Agent Mode plan/status only renders for real tool/agent turns (agent_core, image XML).
    if result.get("showPlan"):
        await websocket.send_json({"type": "agent_plan", "plan": result["plan"]})
        await websocket.send_json({"type": "agent_status", "status": result["status"]})

    await websocket.send_json({"type": "done"})


async def run_text_turn(
    payload: dict[str, Any],
    *,
    core: HanaAgentCore,
    memory: MemoryStore,
    on_delta: Callable[[str], Awaitable[None]] | None = None,
    on_activity: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Run one text turn through the selected provider or deterministic Agent Core.

    When ``on_delta`` is provided and the selected provider supports token streaming
    (currently OpenRouter), partial text is pushed live through the callback while the
    full text is still accumulated for post-processing (image XML, memory, cleanup).
    """
    text = str(payload.get("text") or payload.get("message") or "").strip()
    provider = normalize_llm_provider(payload.get("provider") or "agent_core")
    model = str(payload.get("model") or "structured-planner")
    safety_mode = str(payload.get("safety_mode") or "safe")
    channel = str(payload.get("channel") or "control_center")
    call_mode = bool(payload.get("call_mode", False))
    resolved_attachments = resolve_chat_attachments(payload, memory=memory, text=text, channel=channel)

    # Truncate very large text (e.g. user sending long articles/news to "read"/process directly,
    # without summary or vision). Prevents context bloat, token errors, or models generating
    # strange/random prompts. Full content saved to memory. Fixes vision errors for text-only
    # sends on non-vision models (e.g. DeepSeek) even if visao enabled (screen won't attach if !supports).
    if len(text) > 12000:
        try:
            memory.add_memory(
                f"[Large user text for direct reading/processing - truncated in context. Original length: {len(text)} chars.] {text[:400]}...",
                kind="user_large_text",
                source="chat_or_terminal",
                metadata={"full_length": len(text), "channel": channel}
            )
        except Exception:
            pass
        text = text[:12000] + "\n\n[... texto muito longo truncado para o contexto do modelo. O texto completo foi salvo na memória se precisar lembrar.]"

    connections = memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
    if connections.get("visao") and not should_use_agent_core(text, provider):
        # Only attach screen capture if the selected model actually supports vision.
        # This prevents "openrouter_model_does_not_support_vision" errors when the user
        # picks a text-only model on OpenRouter while testing different models.
        current_provider = provider
        current_model = model
        can_see_screen = model_supports_vision(current_provider, current_model, memory)
        if can_see_screen:
            try:
                from hana_agent_oss.modules.vision.periodic_vision import VisaoNyra
                from hana_agent_oss.api.services.terminal_agent import append_terminal_event
                visao = VisaoNyra(memory=memory)
                res = visao.capturar()
                if res.get("sucesso") and res.get("b64"):
                    mime_type = str(res.get("mime_type") or "image/png")
                    extension = str(res.get("extension") or ".png")
                    screen_attachment = {
                        "name": f"screen_capture{extension}",
                        "type": mime_type,
                        "data": res["b64"],
                        "path": res.get("caminho")
                    }
                    resolved_attachments.append(screen_attachment)
                    
                    append_terminal_event(
                        memory,
                        {
                            "kind": "tool_result",
                            "source": "vision",
                            "speechText": "",
                            "displayText": (
                                "[VISAO SOB DEMANDA ATIVADA]\n"
                                f"Captura de tela enviada para a Hana ({res.get('profile', 'full_hd_png')} "
                                f"{res.get('width', '?')}x{res.get('height', '?')} {mime_type})."
                            ),
                            "status": "success",
                            "toolName": "screen_capture",
                            "metadata": {
                                "tts": False,
                                "caminho": res.get("caminho"),
                                "mimeType": mime_type,
                                "profile": res.get("profile"),
                                "width": res.get("width"),
                                "height": res.get("height"),
                            }
                        }
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception(f"[VISÃO] Falha ao capturar a tela: {e}")
        else:
            # Log that we skipped vision because model doesn't support it (common when testing OpenRouter models)
            try:
                from hana_agent_oss.api.services.terminal_agent import append_terminal_event
                append_terminal_event(
                    memory,
                    {
                        "kind": "system",
                        "source": "vision",
                        "displayText": f"[VISÃO PULADA] Modelo atual ({current_provider}:{current_model}) não suporta visão. Desative 'visao' em Conexões ou escolha um modelo com suporte a imagem.",
                        "speechText": "",
                        "status": "skipped",
                        "metadata": {"tts": False}
                    }
                )
            except Exception:
                pass
    memory.append_event(
        "user",
        text,
        channel=channel,
        metadata={
            "provider": provider,
            "model": model,
            "attachments": [
                {"id": item.get("id"), "name": item.get("name"), "type": item.get("type"), "size": item.get("size")}
                for item in resolved_attachments
            ],
        },
    )

    image_service = ImageGenerationService(memory=memory)
    # Only attempt prompt lookup (recall last image prompt) for non-voice channels.
    # Disabled for voice to avoid any keyword "gatilhos" from user speech triggering
    # auto side-effect dumps of previous image prompts (user explicitly prohibits this).
    prompt_lookup = None
    if channel not in {"voice", "terminal_agent", "terminal"}:
        prompt_lookup = image_service.prompt_lookup_response(text, channel=channel)
    if prompt_lookup:
        prompt_result, prompt_meta = prompt_lookup
        memory.append_event(
            "hana",
            prompt_result.text,
            channel=channel,
            metadata={
                "ok": prompt_result.ok,
                "provider": "gemini_image",
                "model": prompt_result.model,
                **prompt_meta,
            },
        )
        return {
            "ok": prompt_result.ok,
            "text": prompt_result.text,
            "plan": image_plan_payload("prompt", prompt_result.ok, prompt_result.error or "prompt_lookup"),
            "meta": {
                "provider": "gemini_image",
                "model": prompt_result.model,
                "agent": "hana-agent-oss",
                "safetyMode": safety_mode,
                "nativeSearchMode": payload.get("native_search_mode"),
                "nativeSearch": False,
                **prompt_meta,
            },
            "status": {
                "stage": "success" if prompt_result.ok else "failed",
                "detail": prompt_result.error or "prompt_lookup",
                "tool_name": "image.prompt",
            },
            "media": [],
            "showPlan": True,
        }

    if not should_use_agent_core(text, provider):
        portability = memory.get_setting("portabilidade_config", {})
        media_output_path = portability.get("mediaOutputPath") if isinstance(portability, dict) else None
        # === Context-budgeted persistent-memory injection (anti-amnésia) ===
        # The chat panel previously sent ONLY the on-screen history to the LLM, so
        # Hana never saw her own long-term memory unless she called a tool. We now
        # prepend a budgeted RAG block (FTS-only => near-zero latency) and expose
        # what was injected so the Control Panel can show it.
        chat_messages = message_history(payload, text)
        injected_memories: list[dict[str, Any]] = []
        memory_block = ""
        try:
            memory_block, injected_memories = build_memory_context_block(memory, query=text)
            if memory_block:
                chat_messages.insert(0, {"role": "system", "content": memory_block})
        except Exception:
            injected_memories = []

        # === Live context meter (anti-cegueira) ===
        # Measure where the turn's tokens actually go, so Operador/we stop guessing.
        # Pure measurement: never changes what is sent. Emitted to the terminal + meta.
        context_report: dict[str, Any] = {}
        try:
            from hana_agent_oss.api.services.unified_history import (
                context_size_report,
                estimate_image_tokens,
            )
            from hana_agent_oss.persona import build_provider_system_prompt
            from hana_agent_oss.api.services.terminal_agent import append_terminal_event

            history_text = "\n".join(str(m.get("content") or "") for m in chat_messages if m.get("role") != "system")
            context_report = context_size_report(
                {
                    "persona+skills": build_provider_system_prompt(provider),
                    "memoria": memory_block,
                    "historico": history_text,
                },
                image_tokens=estimate_image_tokens(resolved_attachments),
            )
            append_terminal_event(
                memory,
                {
                    "kind": "context_audit",
                    "source": "context_meter",
                    "speechText": "",
                    "displayText": context_report.get("summary", ""),
                    "status": "info",
                    "toolName": "context.meter",
                    "metadata": {"tts": False, "contextReport": context_report},
                },
            )
        except Exception:
            context_report = {}
        # Groq "thinker" switch (GUI toggle): honored from the payload first, else the
        # persisted llm_config. Voice/terminal still auto-disable thinking regardless.
        _llm_cfg = memory.get_setting("llm_config", {})
        groq_thinking = payload.get("groqThinking")
        if groq_thinking is None:
            groq_thinking = _llm_cfg.get("groqThinking", True) if isinstance(_llm_cfg, dict) else True
        llm_request = ProviderRequest(
            provider=provider,
            model=model,
            messages=chat_messages,
            temperature=float(payload.get("temperature") or 0.7),
            native_search_mode=str(payload.get("native_search_mode") or "auto") if provider_supports_native_search(provider) else "off",
            channel=channel,
            call_mode=call_mode,
            attachments=resolved_attachments,
            media_output_path=media_output_path,
            memory=memory,
            openrouter_routing=dict(payload.get("openrouter_routing") or {}) if provider == "openrouter" else {},
            on_activity=on_activity,
            thinking=bool(groq_thinking),
        )
        streamed = False
        stream_provider = (
            OpenRouterProvider._provider_for(provider)
            if (on_delta is not None and provider in STREAMING_PROVIDERS)
            else None
        )
        if stream_provider is not None:
            # Live token streaming path: push deltas as they arrive, accumulate the full
            # raw text, then post-process exactly like the blocking path below. Works for
            # qualquer provider OpenAI-compat (OpenRouter, Groq, DeepSeek).
            llm_request.streaming = True
            parts: list[str] = []
            try:
                async for token in stream_provider.generate_stream(llm_request):
                    if not token:
                        continue
                    parts.append(token)
                    await on_delta(token)
                raw_text = "".join(parts)
                streamed = True
            except Exception as exc:  # noqa: BLE001
                raw_text = f"[ERRO: {exc}]"
            stream_error = raw_text.strip().startswith("[ERRO:")
            llm_ok = bool(raw_text.strip()) and not stream_error
            llm_error = raw_text.strip() if stream_error else None
            llm_meta: dict[str, Any] = {"provider": provider, "model": model, "nativeSearch": False}
        else:
            llm_response = await asyncio.to_thread(PROVIDER_SELECTOR.generate, llm_request)
            # Reasoning models (qwen3, gpt-oss) intermittently return an empty `content`
            # (the answer landed only in the reasoning field, or a malformed first pass)
            # and the turn looks like a dead provider even though tokens WERE generated
            # and telemetry fired. Proven recoverable: the very next identical call works.
            # So instead of failing on her screen/TTS, just retry the blocking call once.
            if (not llm_response.ok) and str(llm_response.error or "") == "empty_provider_response":
                llm_response = await asyncio.to_thread(PROVIDER_SELECTOR.generate, llm_request)
            raw_text = llm_response.text
            llm_ok = llm_response.ok
            llm_error = llm_response.error
            llm_meta = llm_response.meta or {}
        image_actions = extract_image_xml_actions(raw_text)
        image_results = execute_image_xml_actions(
            image_actions,
            image_service=image_service,
            attachments=resolved_attachments,
            channel=channel,
            memory=memory,
        )
        xml_media = [media for item in image_results for media in item.get("media", [])]
        image_errors = [str(item.get("error") or item.get("text") or "") for item in image_results if not item.get("ok")]

        # === Long-term memory saving via <salvar_memoria> XML ===
        # The model can decide to persist important facts from long calls.
        # These are saved silently and never spoken via TTS.
        memory_saves = extract_memory_saves(raw_text)
        for mem in memory_saves:
            try:
                memory.add_memory(
                    mem["text"],
                    kind="long_term",
                    source="model_self_save",
                    metadata={
                        "importance": mem.get("importance", "medium"),
                        "category": mem.get("category", "observation"),
                        "tags": mem.get("tags", []),
                        "channel": channel,
                        "auto_saved": True,
                    },
                )
            except Exception:
                pass  # Never break a turn because memory save failed

        # === Living skills: Hana annotates her own skill .md via <anotar_skill> ===
        # Notes are scoped/capped and silently applied; never spoken or shown.
        apply_skill_notes(raw_text)

        cleaned_text = strip_image_xml_tags(raw_text)
        cleaned_text = strip_memory_xml_tags(cleaned_text)
        cleaned_text = strip_skill_xml_tags(cleaned_text)
        cleaned_text = strip_leaked_tool_calls(cleaned_text)
        # Cut any leaked terminal/system event text the model parroted from the running
        # transcript (e.g. "PTT pressionado. Gravando do microfone..."). Otherwise it
        # gets spoken by TTS and saved, re-polluting future turns.
        cleaned_text = strip_leaked_terminal_events(cleaned_text)
        # Defense vs reasoning-model chain-of-thought leaking into chat/TTS: strip any
        # <think>...</think> block (some reasoning models emit it inline in content).
        import re as _re
        cleaned_text = _re.sub(r"(?is)<think>.*?</think>", " ", cleaned_text).strip()
        cleaned_text = _re.sub(r"(?is)^\s*<think>.*$", " ", cleaned_text).strip()  # unclosed think
        # Voice/terminal are PLAIN-TEXT channels: weak models ignore the "no markdown"
        # rule and emit tables/headers/bold that look wrong in the terminal and become
        # TTS garbage. Force clean prose here regardless of the model (chat/discord-text
        # keep their rich markdown).
        if channel in {"voice", "terminal_agent"} or call_mode:
            from hana_agent_oss.modules.voice.tts_readable import plainify_for_voice
            cleaned_text = plainify_for_voice(cleaned_text)
        meta = {
            "provider": provider,
            "model": model,
            "agent": "hana-agent-oss",
            "safetyMode": safety_mode,
            "nativeSearchMode": payload.get("native_search_mode") if provider_supports_native_search(provider) else "off",
            "nativeSearch": bool(llm_meta.get("nativeSearch")),
        }
        if context_report:
            meta["contextReport"] = context_report
        if llm_meta.get("servedProvider"):
            meta["servedProvider"] = llm_meta["servedProvider"]
        if llm_meta.get("speedTokensPerSec"):
            meta["speedTokensPerSec"] = llm_meta["speedTokensPerSec"]
        if llm_meta and "grounding" in llm_meta:
            meta["grounding"] = llm_meta["grounding"]
        # Surface which persistent memories were actually fed to the LLM this turn,
        # plus an approximate token cost, so the panel can show "Hana lembrou de X".
        if injected_memories:
            meta["memoryContext"] = {
                "count": len(injected_memories),
                "approxTokens": estimate_tokens(
                    "\n".join(str(m.get("text") or "") for m in injected_memories)
                ),
                "memories": [
                    {
                        "id": m.get("id"),
                        "text": str(m.get("text") or "")[:600],
                        "category": m.get("category"),
                        "pinned": bool(m.get("pinned")),
                    }
                    for m in injected_memories
                ],
            }
        # Surface tool activity in the chat: a tool-activity card (every tool) plus the
        # search/sources card (queries + sources aggregated from web tools).
        tool_runs = getattr(llm_request, "tool_runs", []) or []
        if tool_runs:
            meta["toolRuns"] = tool_runs
            agg_queries = [run["query"] for run in tool_runs if run.get("query")]
            agg_sources = [src for run in tool_runs for src in (run.get("sources") or [])]
            if agg_queries or agg_sources:
                existing = meta.get("grounding") or {}
                meta["grounding"] = {
                    "queries": list(dict.fromkeys([*existing.get("queries", []), *agg_queries])),
                    "sources": [*existing.get("sources", []), *agg_sources],
                }
        media = []
        if llm_meta and "media" in llm_meta:
            media.extend(llm_meta["media"])
        media.extend(xml_media)
        if media:
            meta["media"] = media
        if image_results:
            meta["imageActions"] = image_results
        if llm_ok and not image_errors:
            final_text = cleaned_text or ("Imagem gerada pela Hana." if image_results else "")
            memory.append_event("hana", final_text, channel=channel, metadata={"ok": True, "provider": provider, "model": model, "imageActions": image_results})
            status = {"stage": "success", "detail": f"{provider}:{model}"}
            if image_results:
                status["tool_name"] = "image.xml"
                status["detail"] = "Imagem XML processada."
        else:
            is_attachment_error = "attachment_type_not_supported" in str(llm_error or "")
            # Never dump the raw provider error onto her screen / into TTS. The technical
            # detail still goes to meta["providerError"] + the terminal log + memory below,
            # so the panel can debug it; but what she SEES/HEARS is a short in-character
            # line, not "Provider groq nao conectado: empty_provider_response...".
            if is_attachment_error:
                final_text = "Nao consegui ler esse anexo aqui, Naka — manda de outro jeito que eu olho."
            else:
                final_text = "Deu um tropeco no cerebro agora, Naka. Repete pra mim que eu pego de novo."
            if llm_ok and image_errors:
                final_text = cleaned_text or "Falha ao gerar imagem."
            meta["providerError"] = llm_error or (image_errors[0] if image_errors else "provider_error")
            memory.append_event(
                "system",
                final_text,
                channel=channel,
                metadata={"ok": False, "kind": "provider_error", "provider_error": llm_error, "imageErrors": image_errors},
            )
            status = {"stage": "failed", "detail": image_errors[0] if image_errors else (llm_error or "provider_error")}
        return {
            "ok": bool(llm_ok and not image_errors),
            "text": final_text,
            "plan": (
                image_plan_payload("xml", not image_errors, status["detail"], status=status["stage"])
                if image_results
                else provider_plan_payload(provider, model, llm_ok, llm_error or model)
            ),
            "meta": meta,
            "status": status,
            "media": media,
            # Only show the operational card when image XML actions actually ran.
            "showPlan": bool(image_results),
            # When tokens already streamed live, the WS sends an authoritative "final"
            # (cleaned) text instead of re-emitting the whole answer as a chunk.
            "streamed": streamed,
        }

    request = AgentRequest(
        text,
        channel=channel,
        safety_mode=safety_mode,
        attachments=resolved_attachments,
        metadata={
            "provider": provider,
            "model": model,
            "native_search_mode": payload.get("native_search_mode"),
        },
    )
    response = core.run(request)
    final_text = response_text(response)
    final_text = strip_memory_xml_tags(final_text)  # defensive: never leak memory tags
    _append_agent_core_terminal_events(memory, response)
    memory.append_event("hana", final_text, channel=channel, metadata={"ok": response.ok, "agentCore": response.to_dict()})
    return {
        "ok": response.ok,
        "text": final_text,
        "plan": agent_plan_payload(response),
        "meta": {
            "provider": provider,
            "model": model,
            "agent": "hana-agent-oss",
            "safetyMode": safety_mode,
            "nativeSearchMode": payload.get("native_search_mode"),
        },
        "status": {"stage": "success" if response.ok else "failed", "detail": response.error or "done"},
        "media": [],
        "showPlan": True,
    }
