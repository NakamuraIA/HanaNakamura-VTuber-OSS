from __future__ import annotations

import base64
import binascii
import io
import json
import os
import time
from pathlib import Path
from typing import Any

from backend.api.services.unified_history import channel_style_hint
from backend.modules.vision.character_library import DEFAULT_CHARACTER_ROOT
from backend.modules.vision.image_gen import DEFAULT_IMAGE_MODEL, HanaImageGen
from backend.modules.vision.image_service import media_item_for_path
from backend.persona import build_provider_system_prompt
from backend.providers.contracts import ProviderRequest, ProviderResponse
from backend.tools.mcp_provider_tools import mcp_discover_call, mcp_invoke_call, mcp_tool_instruction

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
        style_hint = channel_style_hint(request.channel, call_mode=getattr(request, "call_mode", False))
        full_system_instruction = (
            base_system_prompt
            + self._image_tool_instruction()
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
        thinking_config = self._thinking_config(
            types,
            model=model,
            channel=str(getattr(request, "channel", "") or ""),
            thinking_enabled=bool(getattr(request, "thinking", True)),
            reasoning_effort=getattr(request, "reasoning_effort", None),
        )
        if thinking_config is not None:
            config_kwargs["thinking_config"] = thinking_config
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
        thought_text = self._thought_summary(response)
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
                        "sources": sources,
                        "source": "gemini_native",
                    }

        meta = {
            "provider": "gemini_api",
            "nativeSearch": bool(native_mode in {"auto", "force"}),
            "model": model,
            "attachments": self._attachment_meta(request.attachments),
        }
        if media_list:
            meta["media"] = media_list
        if grounding_data:
            meta["grounding"] = grounding_data
        if thought_text:
            # Mesma forma que a timeline "thinking" do chat consome (ThinkingItem[]).
            # Gemini nao streama aqui, entao o resumo do raciocinio viaja no meta em
            # vez de vir token a token pelo on_reasoning.
            meta["thinking"] = [{"type": "text", "content": thought_text}]

        final_text = text.strip() or ("Imagem gerada pela Hana." if media_list else "")
        return ProviderResponse(
            ok=bool(final_text or media_list),
            text=final_text,
            error=None if final_text or media_list else "empty_provider_response",
            meta=meta,
        )

    @staticmethod
    def _thought_summary(response: Any) -> str:
        """Pull Gemini's thought-summary parts out of a response.

        response.text deliberately SKIPS parts flagged thought=True (checked in the
        google-genai source), so the reasoning never leaks into the spoken answer.
        That also means the only way to show it in the "Pensando..." box is to read
        those parts back out here.
        """
        try:
            candidates = getattr(response, "candidates", None) or []
            if not candidates:
                return ""
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) or []
            chunks = [
                str(part.text)
                for part in parts
                if getattr(part, "thought", False) and isinstance(getattr(part, "text", None), str)
            ]
            return "\n".join(chunk for chunk in chunks if chunk.strip()).strip()
        except Exception:
            # A thought summary is cosmetic; never let it break a real answer.
            return ""

    @staticmethod
    def _thinking_config(types_module: Any, *, model: str, channel: str, thinking_enabled: bool, reasoning_effort: str | None) -> Any | None:
        """Build Gemini's thinking knob, mirroring the unified contract of the other providers.

        Gemini was the last provider with NO thinking control at all: every other
        one goes through OpenAICompatibleProvider._apply_thinking_control, but this
        one is not OpenAI-compatible, so it silently kept Google's defaults and the
        chat toggle did nothing here (see docs/PROVIDERS.md).

        Two different knobs, by family:
          - gemini-3.x  -> thinking_level ("low"/"high")
          - gemini-2.5.x -> thinking_budget (int; 0 disables)

        include_thoughts=True asks for the thought summary, which is what feeds the
        "Pensando..." box in the chat.

        CRITICAL guard: Pro models cannot turn thinking off. Sending budget 0 (or
        level "low" meaning "none") to a Pro model is an API error, so for Pro we
        only lower the effort instead of disabling. Same class of guard as the
        qwen3 non-streaming case.
        """
        model_id = str(model or "").lower()
        if not model_id.startswith("gemini-"):
            return None
        # TTS/image models take no thinking config.
        if "-tts" in model_id or "-image" in model_id:
            return None

        low_latency = str(channel or "").strip().lower() in {"voice", "terminal_agent"}
        explicit = str(reasoning_effort or "").strip().lower()
        is_pro = "-pro" in model_id
        wants_off = explicit == "off" or not thinking_enabled
        wants_low = low_latency or explicit in {"none", "minimal", "low"}

        try:
            if model_id.startswith("gemini-3"):
                # Gemini 3 grades effort by level; there is no "off" for Pro.
                if wants_off and not is_pro:
                    return types_module.ThinkingConfig(thinking_level="low", include_thoughts=False)
                level = "low" if (wants_off or wants_low) else "high"
                return types_module.ThinkingConfig(thinking_level=level, include_thoughts=True)

            if model_id.startswith("gemini-2.5"):
                if wants_off:
                    # Pro cannot disable: fall back to the smallest allowed budget.
                    if is_pro:
                        return types_module.ThinkingConfig(thinking_budget=128, include_thoughts=False)
                    return types_module.ThinkingConfig(thinking_budget=0, include_thoughts=False)
                if wants_low:
                    return types_module.ThinkingConfig(thinking_budget=512, include_thoughts=True)
                # -1 = dynamic: the model decides how long to think.
                return types_module.ThinkingConfig(thinking_budget=-1, include_thoughts=True)
        except (TypeError, AttributeError):
            # Older google-genai without ThinkingConfig: keep Google's defaults
            # instead of breaking the turn.
            return None

        return None

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
        """Return a compact list of characters available for image tools.

        Vazio ("") quando NENHUM personagem esta cadastrado — antes retornava um
        "hana" fake, o que fazia o modelo tentar <gerar_imagem_personagem> e o
        backend falhar sempre com "Personagem visual nao cadastrado: hana".
        """
        root = Path(DEFAULT_CHARACTER_ROOT)
        names: list[str] = []
        if not root.is_dir():
            return ""
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
        return "; ".join(names)

    @classmethod
    def _image_tool_instruction(cls) -> str:
        """Build the XML image action guide injected into Gemini system prompts."""
        characters = cls._registered_character_summary()
        generic = (
            "\n\n[IMAGE XML ACTION MANUAL — CRITICAL RULES]\n"
            "Image generation uses XML tags, NOT function calling. Follow these rules EXACTLY:\n\n"
            "1. To request an image, write ONE silent XML tag at the END of your answer.\n"
            "   The backend executes it. If you write NO tag, NO image is generated.\n\n"
            "2. NEVER describe, praise, or comment on an image you did NOT actually generate.\n"
            "   Wrong: 'Here is your image! ✨ The lighting is perfect...'\n"
            "   Wrong: 'The image came out beautiful — warm tones, soft shadows...'\n"
            "   Right: '<gerar_imagem>prompt</gerar_imagem>'\n"
            "   After writing the tag, say only that you are generating. Do NOT describe the result.\n\n"
            "3. NEVER claim an image was generated, failed, timed out, or had an API error\n"
            "   unless you see an actual backend event confirming it. The tag text is NOT a result.\n"
            "4. NEVER narrate a multi-step 'test sequence' like 'Degrau 1, Degrau 2'. Just generate\n"
            "   what the user asked for in one tag. One tag = one image.\n\n"
            "5. NEVER use image XML when the user is only asking about a previous image or prompt.\n\n"
            "For generic images:  <gerar_imagem>English prompt</gerar_imagem>\n"
            "For generic edits:   <editar_imagem>English edit instruction</editar_imagem>\n"
        )
        if not characters:
            # Nenhum personagem cadastrado: NAO oferece as tags de personagem —
            # elas falhariam sempre com "Personagem visual nao cadastrado". Sem
            # essa instrucao, o modelo para de disparar geracao de personagem a toa.
            return generic + (
                "No visual characters are registered on this system. Do NOT use "
                "<gerar_imagem_personagem> or <editar_imagem_personagem> — there is no "
                "character to render and any such tag will fail. Use only the generic image tags above.\n"
                "Your visible sentence should say that you are starting/preparing the image, not that it is already ready.\n"
            )
        return generic + (
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
    def _mcp_callables(request: ProviderRequest) -> list[Any]:
        """Create Gemini callables for MCP discovery and invocation."""

        def mcp_discover(server_id: str = "") -> dict:
            """Discover configured MCP servers and tools."""
            return mcp_discover_call(request.memory, server_id, manager=request.mcp_manager)

        def mcp_invoke(server_id: str, tool: str, arguments: dict | None = None) -> dict:
            """Invoke one allowlisted MCP tool on one enabled server."""
            return mcp_invoke_call(
                request.memory,
                server_id,
                tool,
                arguments if isinstance(arguments, dict) else {},
                manager=request.mcp_manager,
            )

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
