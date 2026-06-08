from __future__ import annotations

import base64
import binascii
import io
import json
import os
import time
from pathlib import Path
from typing import Any

from hana_agent_oss.api.services.unified_history import channel_style_hint
from hana_agent_oss.modules.vision.character_library import DEFAULT_CHARACTER_ROOT
from hana_agent_oss.modules.vision.image_gen import DEFAULT_IMAGE_MODEL, HanaImageGen
from hana_agent_oss.modules.vision.image_service import media_item_for_path
from hana_agent_oss.persona import build_provider_system_prompt
from hana_agent_oss.providers.contracts import ProviderRequest, ProviderResponse
from hana_agent_oss.api.services.agent_jobs import agent_job_cancel as run_agent_job_cancel, get_agent_job_manager
from hana_agent_oss.tools.mcp_provider_tools import mcp_discover_call, mcp_invoke_call, mcp_tool_instruction
from hana_agent_oss.tools.omni_tools import omni_supervise as run_omni_supervise

INLINE_ATTACHMENT_LIMIT_BYTES = 19 * 1024 * 1024
FILE_PROCESSING_TIMEOUT_SECONDS = 60
SUPPORTED_ATTACHMENT_PREFIXES = (
    "image/",
    "audio/",
    "video/",
    "text/",
)
SUPPORTED_ATTACHMENT_TYPES = {
    "application/pdf",
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "application/octet-stream",
}


class GeminiApiProvider:
    """Google AI Studio Gemini API provider."""

    aliases = {"gemini_api", "gemini", "google", "google_ai_studio"}

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        try:
            from google import genai
            from google.genai import types
        except Exception:
            return ProviderResponse(ok=False, error="missing_optional_dependency:google-genai")

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return ProviderResponse(ok=False, error="missing_credentials:GOOGLE_API_KEY_or_GEMINI_API_KEY")

        try:
            client = genai.Client(api_key=api_key)
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(ok=False, error=f"client_init_error:{exc}")

        media_list = []

        tools = []
        native_mode = request.native_search_mode or "auto"
        if native_mode in {"auto", "force"}:
            tools.append(types.Tool(google_search=types.GoogleSearch()))
        omni_tool = self._omni_supervise_callable(request)
        if omni_tool is not None:
            tools.append(omni_tool)
        cancel_tool = self._agent_job_cancel_callable(request)
        if cancel_tool is not None:
            tools.append(cancel_tool)
        mcp_tools = self._mcp_callables(request)
        tools.extend(mcp_tools)

        try:
            attachment_parts = self._attachment_parts(client, types, request.attachments)
        except ValueError as exc:
            return ProviderResponse(ok=False, error=f"attachment_error:{exc}")
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(ok=False, error=f"attachment_upload_error:{exc}")

        contents = []
        recent_messages = request.messages[-20:]
        for index, msg in enumerate(recent_messages):
            role = "user" if msg.get("role") in {"user", "system"} else "model"
            text = str(msg.get("content") or "").strip()
            parts = []
            if role == "user" and index == len(recent_messages) - 1 and attachment_parts:
                parts.extend(attachment_parts)
            if text:
                parts.append(types.Part.from_text(text=text))
            elif attachment_parts and role == "user" and index == len(recent_messages) - 1:
                parts.append(types.Part.from_text(text="Analise os anexos enviados."))
            if not parts:
                continue
            contents.append(types.Content(role=role, parts=parts))

        if not contents and attachment_parts:
            contents.append(types.Content(role="user", parts=[*attachment_parts, types.Part.from_text(text="Analise os anexos enviados.")]))

        model = (request.model or "").strip() or "gemini-3.1-pro-preview"
        base_system_prompt = build_provider_system_prompt("gemini_api")
        style_hint = channel_style_hint(request.channel)
        full_system_instruction = (
            base_system_prompt
            + self._image_tool_instruction()
            + self._omni_tool_instruction(enabled=omni_tool is not None)
            + self._agent_jobs_tool_instruction(enabled=cancel_tool is not None)
            + mcp_tool_instruction(enabled=bool(mcp_tools) and model != DEFAULT_IMAGE_MODEL)
            + style_hint
        )

        # Adicionar o hint de visão se houver captura de tela
        has_screen_capture = any(
            isinstance(item, dict) and str(item.get("name") or "").startswith("screen_capture")
            for item in request.attachments
        )
        if has_screen_capture:
            vision_hint = (
                "\n\n[INSTRUÇÃO DE VISÃO - PERSONALIDADE NEURO-SAMA / EVIL NEURO + CALL]\n"
                "Você tem acesso à tela atual via captura (screen_capture). Isso acontece especialmente quando está em call de Discord (bot ou cabo virtual) com pessoas assistindo a tela.\n"
                "Aja de forma totalmente natural, como uma VTuber presente na call (estilo Neuro-sama / Evil Neuro).\n"
                "NÃO descreva a tela de forma chata ('Estou vendo...', 'Na imagem há...'). Comente de forma integrada, piadas, reações, palpites sobre o que está rolando.\n"
                "IMPORTANTE: A Nakamura pode estar presente e no comando agora. Quando as falas vierem dela, trate-a como a usuária principal e operadora. Ainda reaja naturalmente ao grupo e à tela."
            )
            full_system_instruction += vision_hint

        if model == DEFAULT_IMAGE_MODEL:
            tools = []

        tools, tool_config, has_function_calling = self._prepare_tool_config(types, tools)

        config_kwargs = {
            "temperature": request.temperature,
            "tools": tools or None,
            "system_instruction": full_system_instruction,
        }
        if has_function_calling:
            config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=False)
        if tool_config is not None:
            config_kwargs["tool_config"] = tool_config
        if model == DEFAULT_IMAGE_MODEL:
            config_kwargs["response_modalities"] = ["TEXT", "IMAGE"]
        config = types.GenerateContentConfig(**config_kwargs)

        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(ok=False, error=f"provider_error:{exc}")

        if model == DEFAULT_IMAGE_MODEL:
            try:
                generator = HanaImageGen(output_dir=request.media_output_path)
                prompt_text = request.messages[-1].get("content", "image") if request.messages else "image"
                saved_path = generator._save_image_from_response(response, prompt_text, prefix="gen")
                if saved_path:
                    media_list.append(media_item_for_path(saved_path))
                    if request.channel in {"terminal", "cli"}:
                        generator._open_if_possible(saved_path, "IMAGE GEN")
            except Exception:
                pass

        text = getattr(response, "text", "") or ""
        grounding_data = None
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
                metadata = candidate.grounding_metadata
                queries = []
                if hasattr(metadata, "web_search_queries") and metadata.web_search_queries:
                    queries = list(metadata.web_search_queries)
                
                sources = []
                if hasattr(metadata, "grounding_chunks") and metadata.grounding_chunks:
                    for chunk in metadata.grounding_chunks:
                        if hasattr(chunk, "web") and chunk.web:
                            web = chunk.web
                            title = getattr(web, "title", "") or ""
                            uri = getattr(web, "uri", "") or ""
                            if uri:
                                sources.append({
                                    "title": title,
                                    "uri": uri
                                })
                if queries or sources:
                    grounding_data = {
                        "queries": queries,
                        "sources": sources
                    }

        meta = {
            "provider": "gemini_api",
            "nativeSearch": bool(native_mode in {"auto", "force"}),
            "model": model,
            "attachments": self._attachment_meta(request.attachments),
            "capabilities": self.capabilities_payload(),
        }
        if media_list:
            meta["media"] = media_list
        if grounding_data:
            meta["grounding"] = grounding_data

        final_text = text.strip() or ("Imagem gerada pela Hana." if media_list else "")
        return ProviderResponse(
            ok=bool(final_text or media_list),
            text=final_text,
            error=None if final_text or media_list else "empty_provider_response",
            meta=meta,
        )

    @staticmethod
    def _prepare_tool_config(types_module: Any, tools: list[Any]) -> tuple[list[Any], Any | None, bool]:
        """Build Gemini tool config for server-side tools and local callables."""

        has_server_side_tool = any(not callable(tool) for tool in tools)
        has_function_calling = any(callable(tool) for tool in tools)
        if not has_server_side_tool and not has_function_calling:
            return tools, None, False

        try:
            tool_config_kwargs: dict[str, Any] = {}
            if has_function_calling:
                tool_config_kwargs["functionCallingConfig"] = types_module.FunctionCallingConfig(mode="AUTO")
            if has_server_side_tool:
                tool_config_kwargs["includeServerSideToolInvocations"] = True
            tool_config = types_module.ToolConfig(**tool_config_kwargs)
        except (TypeError, AttributeError):
            # Keep server-side tools such as Google Search and drop local callables
            # instead of letting one optional bridge break normal Gemini chat.
            server_tools = [tool for tool in tools if not callable(tool)]
            return server_tools, None, False

        return tools, tool_config, has_function_calling

    @staticmethod
    def _registered_character_summary() -> str:
        """Return a compact list of characters available for image tools."""
        root = Path(DEFAULT_CHARACTER_ROOT)
        names: list[str] = []
        if not root.is_dir():
            return "hana"
        for folder in root.iterdir():
            if not folder.is_dir() or not (folder / "character.json").exists():
                continue
            label = folder.name
            try:
                data = json.loads((folder / "character.json").read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    display = str(data.get("display_name") or "").strip()
                    nickname = str(data.get("nickname") or "").strip()
                    aliases = ", ".join(item for item in (display, nickname) if item)
                    if aliases:
                        label = f"{folder.name} ({aliases})"
            except Exception:
                pass
            names.append(label)
        return "; ".join(names) if names else "hana"

    @classmethod
    def _image_tool_instruction(cls) -> str:
        """Build the XML image action guide injected into Gemini system prompts."""
        characters = cls._registered_character_summary()
        return (
            "\n\n[IMAGE XML ACTION MANUAL]\n"
            "Image generation does not use function calling. To request image work, write one silent XML tag at the end of your answer.\n"
            "The backend executes only valid XML image tags. If you do not write a tag, no image will be generated.\n"
            "Never claim that an image was generated, failed, timed out, or had an API error unless the backend result is returned in a later turn/event.\n"
            "Never use image XML when Nakamura only asks about a previous image, asks which prompt was used, or discusses image generation behavior.\n"
            "For generic images, use exactly: <gerar_imagem>English prompt for the image</gerar_imagem>.\n"
            "For generic edits, use exactly: <editar_imagem>English edit instruction</editar_imagem>.\n"
            "For Hana, 'you', 'sua', Nyra, Shogun, or registered characters, use exactly <gerar_imagem_personagem>{valid JSON}</gerar_imagem_personagem>.\n"
            "For character edits, use exactly <editar_imagem_personagem>{valid JSON}</editar_imagem_personagem>.\n"
            f"Currently registered visual characters: {characters}.\n"
            "Single-character JSON shape: {\"character\":\"hana\",\"mode\":\"scene\",\"prompt\":\"English creative prompt\",\"references\":[],\"preserve_identity\":true}.\n"
            "Multi-character JSON shape: {\"characters\":[\"hana\",\"nyra\"],\"mode\":\"scene\",\"prompt\":\"English creative prompt containing both characters\",\"references\":[],\"preserve_identity\":true}.\n"
            "When Nakamura asks for two or more registered characters together, use one character XML tag with a characters array, never several separate image tags.\n"
            "Use character folder IDs normalized to lowercase, for example hana, nyra, shogun, or nakamura when explicitly requested.\n"
            "If an explicitly requested character is not registered yet, do not replace it with another character; use the requested lowercase ID so the backend can report the missing character.json.\n"
            "Do not invent image paths. Keep references empty unless Nakamura explicitly names reference keys; empty references use default_references from character.json.\n"
            "Your visible sentence should say that you are starting/preparing the image, not that it is already ready.\n"
        )

    @staticmethod
    def _append_omni_terminal_event(memory: Any, *, kind: str, status: str, display_text: str, metadata: dict[str, Any]) -> None:
        """Mirror Gemini-triggered Omni function calls into Terminal Agent events."""
        if memory is None:
            return
        try:
            from hana_agent_oss.api.services.terminal_agent import append_terminal_event

            append_terminal_event(
                memory,
                {
                    "kind": kind,
                    "source": "omni_bridge",
                    "displayText": display_text,
                    "speechText": "",
                    "status": status,
                    "toolName": "omni.supervise",
                    "metadata": {"tts": False, **metadata},
                },
            )
        except Exception:
            return

    @staticmethod
    def _omni_tool_instruction(*, enabled: bool) -> str:
        """Build the Omni function-calling guide injected into Gemini system prompts."""
        if not enabled:
            return (
                "\n\n[OMNI LOCAL EXECUTOR STATUS]\n"
                "The omni_supervise function is not available in this turn. Do not write omni_supervise(...) as visible text.\n"
                "If Nakamura asks for local PC automation, say the Omni bridge is not enabled/configured instead of pretending to call it.\n"
            )
        return (
            "\n\n[OMNI LOCAL EXECUTOR MANUAL]\n"
            "For local computer, process, file-system, window, clipboard, OCR, or PC automation tasks that are outside normal conversation, use the function omni_supervise.\n"
            "This function starts a background job and returns quickly with job_id/status=running. It does not mean Omni finished yet.\n"
            "Use mode='inspect' for analysis-only requests. Use mode='execute' only when Nakamura explicitly asks to perform a concrete action. Use mode='review' when Nakamura asks Omni to inspect prior work, validate a result, or explain what is wrong.\n"
            "Pass acceptance as a short plain-text checklist, not as an array.\n"
            "Never use Omni for normal chat, persona, STT, TTS, image generation, web search, or questions you can answer directly.\n"
            "If the function result has ok=false, quote the returned error field exactly and do not invent causes such as timeouts, API bugs, or internal crashes.\n"
            "When the function returns job_id/status=running, tell Nakamura the job started and that the final report will appear in Terminal Agent. Do not summarize a result that has not arrived yet.\n"
            "For destructive actions, credentials, .env files, commits, deletes, formatting, or irreversible operations, ask Nakamura for confirmation before calling Omni in execute mode.\n"
        )

    @staticmethod
    def _agent_jobs_tool_instruction(*, enabled: bool) -> str:
        """Build the guide for cancelling background jobs through a real tool call."""
        if not enabled:
            return ""
        return (
            "\n\n[BACKGROUND AGENT JOBS]\n"
            "Omni runs as cancellable background jobs. If Nakamura explicitly asks to stop, cancel, parar, or abort a running Omni job, call agent_job_cancel.\n"
            "This is not a hidden trigger: only use the real tool call when the user asks to cancel a background job.\n"
            "Do not use the TTS stop/hotkey semantics for jobs; job cancellation is separate from stopping speech.\n"
        )

    def _omni_supervise_callable(self, request: ProviderRequest):
        """Create the Gemini callable that delegates supervised local tasks to Omni."""
        connections = {}
        if request.memory is not None:
            try:
                connections = request.memory.get_setting("connections_config", {}) or {}
            except Exception:
                connections = {}
        if not bool(connections.get("omni")):
            return None
        omni_url = str(connections.get("omniUrl") or "").strip()

        def omni_supervise(task: str, mode: str = "inspect", acceptance: str = "", max_rounds: int = 3) -> dict:
            """Delegate a local PC task to Omni-Agent OS and return Hana supervision status."""
            normalized_task = str(task or "").strip()
            normalized_mode = str(mode or "inspect").strip().lower()
            normalized_acceptance = acceptance if isinstance(acceptance, (str, list)) else ""
            self._append_omni_terminal_event(
                request.memory,
                kind="tool_call",
                status="running",
                display_text=f"Delegando tarefa ao Omni ({normalized_mode}): {normalized_task[:240]}",
                metadata={"mode": normalized_mode},
            )
            result = run_omni_supervise(
                {
                    "task": normalized_task,
                    "mode": normalized_mode,
                    "acceptance": normalized_acceptance,
                    "max_rounds": max_rounds,
                    "base_url": omni_url,
                    "_background_job": True,
                }
            )
            result_dict = result.to_dict()
            self._append_omni_terminal_event(
                request.memory,
                kind="tool_result",
                status="success" if result.ok else "failed",
                display_text=str(result.output.get("response") or result.output.get("message") or result.error or "Omni job iniciado."),
                metadata={"mode": normalized_mode, "toolResult": result_dict},
            )
            return result_dict

        omni_supervise.__annotations__ = {
            "task": str,
            "mode": str,
            "acceptance": str,
            "max_rounds": int,
            "return": dict,
        }
        return omni_supervise

    @staticmethod
    def _agent_job_cancel_callable(request: ProviderRequest):
        """Create the Gemini callable that cancels active background agent jobs."""
        if get_agent_job_manager() is None:
            return None

        def agent_job_cancel(job_id: str = "", agent: str = "", active: bool = True, reason: str = "user_request") -> dict:
            """Cancel one Omni background job by id, agent, or active jobs."""
            result = run_agent_job_cancel(
                {
                    "job_id": str(job_id or "").strip(),
                    "agent": str(agent or "").strip().lower(),
                    "active": bool(active),
                    "reason": str(reason or "user_request").strip() or "user_request",
                }
            )
            return result.to_dict()

        agent_job_cancel.__annotations__ = {
            "job_id": str,
            "agent": str,
            "active": bool,
            "reason": str,
            "return": dict,
        }
        return agent_job_cancel

    @staticmethod
    def _mcp_callables(request: ProviderRequest) -> list[Any]:
        """Create Gemini callables for MCP discovery and invocation."""

        def mcp_discover(server_id: str = "") -> dict:
            """Discover configured MCP servers and tools."""
            return mcp_discover_call(request.memory, server_id)

        def mcp_invoke(server_id: str, tool: str, arguments: dict | None = None) -> dict:
            """Invoke one allowlisted MCP tool on one enabled server."""
            return mcp_invoke_call(request.memory, server_id, tool, arguments if isinstance(arguments, dict) else {})

        mcp_discover.__annotations__ = {"server_id": str, "return": dict}
        mcp_invoke.__annotations__ = {"server_id": str, "tool": str, "arguments": dict, "return": dict}
        return [mcp_discover, mcp_invoke]

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
    def _decode_data_url(data_url: str) -> bytes:
        value = str(data_url or "")
        if "," in value and value.lower().startswith("data:"):
            value = value.split(",", 1)[1]
        try:
            return base64.b64decode(value, validate=False)
        except binascii.Error as exc:
            raise ValueError("invalid_base64_attachment") from exc

    @staticmethod
    def _is_supported_attachment(mime_type: str) -> bool:
        mime = str(mime_type or "").lower().strip()
        return mime in SUPPORTED_ATTACHMENT_TYPES or any(mime.startswith(prefix) for prefix in SUPPORTED_ATTACHMENT_PREFIXES)

    @staticmethod
    def _wait_for_uploaded_file(client, uploaded):
        name = getattr(uploaded, "name", None)
        if not name:
            return uploaded
        deadline = time.monotonic() + FILE_PROCESSING_TIMEOUT_SECONDS
        current = uploaded
        while time.monotonic() < deadline:
            state = str(getattr(current, "state", "") or "").upper()
            if "FAILED" in state:
                raise ValueError("file_processing_failed")
            if not state or "PROCESSING" not in state:
                return current
            time.sleep(1)
            current = client.files.get(name=name)
        raise ValueError("file_processing_timeout")

    @classmethod
    def _attachment_parts(cls, client, types, attachments: list[dict[str, Any]]) -> list[Any]:
        parts = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            mime_type = str(item.get("type") or "application/octet-stream").strip() or "application/octet-stream"
            if not cls._is_supported_attachment(mime_type):
                raise ValueError(f"unsupported_attachment_type:{mime_type}")
            if item.get("path"):
                raw = Path(str(item.get("path"))).read_bytes()
            else:
                raw = cls._decode_data_url(str(item.get("data") or ""))
            if not raw:
                raise ValueError("empty_attachment")
            if len(raw) <= INLINE_ATTACHMENT_LIMIT_BYTES:
                parts.append(types.Part.from_bytes(data=raw, mime_type=mime_type))
                continue

            filename = str(item.get("name") or "attachment").strip() or "attachment"
            buffer = io.BytesIO(raw)
            buffer.name = filename
            uploaded = client.files.upload(
                file=buffer,
                config={"mime_type": mime_type, "display_name": filename},
            )
            uploaded = cls._wait_for_uploaded_file(client, uploaded)
            file_uri = getattr(uploaded, "uri", None)
            uploaded_mime = getattr(uploaded, "mime_type", None) or getattr(uploaded, "mimeType", None) or mime_type
            if not file_uri:
                raise ValueError("uploaded_file_missing_uri")
            parts.append(types.Part.from_uri(file_uri=file_uri, mime_type=uploaded_mime))
        return parts

    @staticmethod
    def capabilities_payload() -> dict[str, Any]:
        return {
            "multimodal_input": True,
            "supports_image": True,
            "supports_audio": True,
            "supports_video": True,
            "supports_pdf": True,
            "supports_native_web_search": True,
            "supports_streaming": True,
            "supports_structured_output": True,
            "supports_function_calling": True,
            "supports_code_execution": True,
            "supports_image_generation": True,
            "supports_video_generation": True,
            "supports_tts": True,
            "supports_live_voice": True,
            "supports_memory_embeddings": True,
            "supports_rag": True,
        }
