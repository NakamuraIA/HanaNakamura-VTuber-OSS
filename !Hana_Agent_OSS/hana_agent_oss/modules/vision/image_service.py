"""Central image generation service for Gemini image flows."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.vision.character_library import (
    DEFAULT_CHARACTER_ID,
    DEFAULT_CHARACTER_ROOT,
    compose_character_prompt,
    parse_character_image_request,
    resolve_request_reference_paths,
)
from hana_agent_oss.modules.vision.image_gen import (
    DEFAULT_IMAGE_MODEL,
    HanaImageGen,
    resolve_output_dir,
)
from hana_agent_oss.modules.vision.image_provider import (
    DEFAULT_IMAGE_PROVIDER,
    create_image_provider,
    normalize_image_provider,
)


IMAGE_WORDS = {
    "imagem",
    "foto",
    "arte",
    "desenho",
    "ilustracao",
    "avatar",
    "retrato",
    "wallpaper",
    "png",
    "image",
    "picture",
    "art",
    "drawing",
}
GENERATE_WORDS = {
    "gera",
    "gerar",
    "gere",
    "cria",
    "criar",
    "crie",
    "desenha",
    "desenhar",
    "desenhe",
    "faz",
    "faca",
    "produza",
    "generate",
    "create",
    "draw",
}
EDIT_WORDS = {
    "edita",
    "editar",
    "edite",
    "muda",
    "mudar",
    "mude",
    "altera",
    "alterar",
    "altere",
    "remove",
    "remova",
    "troca",
    "trocar",
    "transforma",
    "transformar",
    "ajusta",
    "ajustar",
    "edit",
    "change",
    "remove",
    "transform",
}
SELF_REFERENCE_WORDS = {"sua", "seu", "voce", "vc", "dela", "hana", "rana"}
PENDING_IMAGE_ACTION_KEY = "pending_image_action"
LAST_IMAGE_GENERATION_KEY = "last_image_generation"
PENDING_IMAGE_ACTION_TTL_SECONDS = 300
IMAGE_CONFIRMATION_WORDS = {"sim", "s", "pode", "gera", "gerar", "gere", "confirma", "confirmo", "manda", "vai", "ok", "bora"}
IMAGE_CANCEL_WORDS = {"nao", "n", "cancela", "cancelar", "cancele", "deixa", "para", "pare", "stop"}


@dataclass
class ImageOperationResult:
    """Normalized image operation result consumed by APIs, tools, and chat."""

    ok: bool
    text: str
    media: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    model: str = DEFAULT_IMAGE_MODEL
    saved_path: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-safe response payload."""
        return {
            "ok": self.ok,
            "text": self.text,
            "media": self.media,
            "error": self.error,
            "model": self.model,
            "savedPath": self.saved_path,
        }


def media_item_for_path(filepath: str, *, status: str = "ready", error: str | None = None) -> dict[str, Any]:
    """Build a chat media payload for a generated image path."""
    filename = os.path.basename(filepath) if filepath else "imagem"
    item: dict[str, Any] = {
        "type": "image",
        "job_id": f"image-{Path(filename).stem or uuid.uuid4().hex[:8]}",
        "name": filename,
        "status": status,
    }
    if filepath:
        item["url"] = f"/api/media/image/{filename}"
    if error:
        item["error"] = error
    return item


def failed_media_item(error: str) -> dict[str, Any]:
    """Build a visible failed image media payload."""
    return {
        "type": "image",
        "job_id": f"image-failed-{uuid.uuid4().hex[:8]}",
        "name": "Imagem da Hana",
        "status": "failed",
        "error": error,
    }


def _normalize_match_text(value: str) -> str:
    """Normalize user text for accent-insensitive Portuguese command matching."""
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.lower()


def _has_word(text: str, word: str) -> bool:
    """Return true when a normalized word appears as a standalone token."""
    return bool(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text))


def _has_any_word(text: str, words: set[str]) -> bool:
    """Return true when any normalized command word is present."""
    return any(_has_word(text, word) for word in words)


def _confirmation_decision(text: str) -> str | None:
    """Classify a short natural-language reply as image confirmation or cancelation."""
    normalized = _normalize_match_text(text)
    tokens = re.findall(r"\b\w+\b", normalized)
    if not tokens or len(tokens) > 12:
        return None
    token_set = set(tokens)
    if token_set & IMAGE_CANCEL_WORDS:
        return "cancel"
    if token_set & IMAGE_CONFIRMATION_WORDS:
        return "confirm"
    return None


def _looks_like_prompt_lookup(text: str) -> bool:
    """Detect requests to show the prompt from the last image without generating a new image.

    DISABLED per user request: no keyword-based triggers ("gatilhos") from user input text
    that automatically dump previous image prompts or long unrelated texts.
    The user explicitly prohibits any side-effect triggers based on words/phrases in spoken or typed input.
    If the user wants a previous prompt, they can ask explicitly and the AI should use long-term memory
    if it was saved via <salvar_memoria>, or respond naturally without auto-dumping.
    """
    # Disabled to respect "proibido ter qualquer tipo de gatilho que venha de mim"
    return False
    # Original logic (commented out):
    # normalized = _normalize_match_text(text)
    # if not _has_word(normalized, "prompt"):
    #     return False
    # lookup_words = {"usou", "usado", "usada", "ultimo", "ultima", "final", "completo", "manda", "mostra", "mostre", "qual", "envia"}
    # return any(_has_word(normalized, word) for word in lookup_words)


def _registered_character_aliases(root_dir: str = DEFAULT_CHARACTER_ROOT) -> dict[str, str]:
    """Load character aliases from data/characters without hardcoding names."""
    aliases: dict[str, str] = {}
    root = Path(root_dir)
    if not root.is_dir():
        return aliases

    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        character_path = folder / "character.json"
        if not character_path.exists():
            continue
        character_id = _normalize_match_text(folder.name).strip()
        if not character_id:
            continue
        aliases[character_id] = character_id
        try:
            data = json.loads(character_path.read_text(encoding="utf-8-sig"))
        except Exception:
            data = {}
        if not isinstance(data, dict):
            continue
        for key in ("display_name", "name", "nickname", "apelido"):
            value = _normalize_match_text(str(data.get(key) or "")).strip()
            if value:
                aliases[value] = character_id
                for token in value.split():
                    if len(token) >= 3:
                        aliases[token] = character_id
    return aliases


def detect_character_id(text: str, *, root_dir: str = DEFAULT_CHARACTER_ROOT) -> str | None:
    """Detect the requested registered character from chat text."""
    normalized = _normalize_match_text(text)
    aliases = _registered_character_aliases(root_dir)
    for alias, character_id in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if alias and _has_word(normalized, alias):
            return character_id
    if _has_any_word(normalized, SELF_REFERENCE_WORDS):
        return DEFAULT_CHARACTER_ID
    return None


def infer_image_operation(
    text: str,
    attachments: list[dict[str, Any]] | None = None,
    *,
    root_dir: str = DEFAULT_CHARACTER_ROOT,
) -> str | None:
    """Infer explicit image requests without relying on LLM tool-calling."""
    prompt = str(text or "")
    normalized = _normalize_match_text(prompt)
    has_edit_word = _has_any_word(normalized, EDIT_WORDS)
    has_image_word = _has_any_word(normalized, IMAGE_WORDS)
    has_generate_word = _has_any_word(normalized, GENERATE_WORDS)
    character_id = detect_character_id(prompt, root_dir=root_dir)
    has_image_attachment = any(str(item.get("type") or "").startswith("image/") for item in attachments or [] if isinstance(item, dict))

    if has_image_attachment and has_edit_word:
        return "character_edit" if character_id else "edit"
    if has_image_attachment and has_image_word and has_generate_word:
        return "character_edit" if character_id else "edit"
    if has_edit_word and has_image_word:
        return "character_edit" if character_id else "edit"
    if has_image_word and character_id:
        return "character_generate"
    if has_image_word and has_generate_word:
        return "generate"
    return None


def _decode_data_url(data_url: str) -> bytes:
    value = str(data_url or "")
    if "," in value and value.lower().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=False)
    except binascii.Error as exc:
        raise ValueError("invalid_base64_image_attachment") from exc


def _attachment_paths(attachments: list[dict[str, Any]] | None, output_dir: str) -> list[str]:
    paths: list[str] = []
    scratch_dir = Path(output_dir) / "_inputs"
    for item in attachments or []:
        if not isinstance(item, dict) or not str(item.get("type") or "").startswith("image/"):
            continue
        raw_path = str(item.get("path") or "").strip()
        if raw_path and os.path.exists(raw_path):
            paths.append(os.path.abspath(raw_path))
            continue
        raw_data = str(item.get("data") or "").strip()
        if not raw_data:
            continue
        scratch_dir.mkdir(parents=True, exist_ok=True)
        ext = ".png"
        name = str(item.get("name") or "").lower()
        for candidate in (".png", ".jpg", ".jpeg", ".webp"):
            if name.endswith(candidate):
                ext = candidate
                break
        path = scratch_dir / f"{uuid.uuid4().hex}{ext}"
        path.write_bytes(_decode_data_url(raw_data))
        paths.append(str(path))
    return paths


def _clipboard_image_paths(output_dir: str) -> list[str]:
    """Read image files or bitmap data copied to the Windows clipboard."""
    try:
        from PIL import ImageGrab
    except Exception:
        return []

    try:
        clipboard = ImageGrab.grabclipboard()
    except Exception:
        return []

    paths: list[str] = []
    if isinstance(clipboard, list):
        for item in clipboard:
            path = os.path.abspath(str(item))
            if os.path.exists(path) and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                paths.append(path)
        return paths

    if hasattr(clipboard, "save"):
        scratch_dir = Path(output_dir) / "_clipboard"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        path = scratch_dir / f"{uuid.uuid4().hex}.png"
        try:
            clipboard.save(path, "PNG")
        except Exception:
            return []
        return [str(path)]
    return []


def _character_payload_from_args(
    raw_prompt: str | dict[str, Any],
    *,
    character_id: str,
    mode: str,
    references: list[str] | None,
    source_image: str | None = None,
) -> dict[str, Any]:
    """Build a character payload from either raw XML JSON or explicit API args."""
    raw_text = "" if isinstance(raw_prompt, dict) else str(raw_prompt or "").strip()
    if isinstance(raw_prompt, dict):
        payload = dict(raw_prompt)
    else:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and {
            "prompt",
            "character",
            "character_id",
            "characters",
            "character_ids",
            "personagem",
            "personagens",
        } & set(parsed):
            payload = parsed
        else:
            payload = {"prompt": raw_text}

    if not any(key in payload for key in ("character", "character_id", "characters", "character_ids", "personagem", "personagens")):
        payload["character"] = character_id
    if not str(payload.get("prompt") or "").strip():
        payload["prompt"] = raw_text
    if not str(payload.get("mode") or payload.get("modo") or "").strip():
        payload["mode"] = mode
    if references and not any(key in payload for key in ("references", "reference_images", "use_references", "refs", "referencias")):
        payload["references"] = references
    if source_image is not None and not any(key in payload for key in ("source_image", "image_path", "imagem_base")):
        payload["source_image"] = source_image
    return payload


def _unpack_result(res: Any) -> tuple[str | None, str | None]:
    """Unpack a result that could be an ImageProviderResult or a string filepath/None."""
    if res is None:
        return None, None
    if hasattr(res, "filepath"):
        return res.filepath, res.error
    return str(res), None


class ImageGenerationService:
    """Coordinate Gemini image operations and normalize chat/API results."""

    def __init__(self, memory: MemoryStore | None = None, output_dir: str | None = None, image_provider: str | None = None) -> None:
        self.memory = memory
        self.output_dir = resolve_output_dir(memory=memory, output_dir=output_dir)
        # Resolve image provider from explicit arg, memory setting, or default.
        if image_provider:
            self._image_provider_id = normalize_image_provider(image_provider)
        elif memory is not None:
            try:
                stored = memory.get_setting("image_provider", None)
                self._image_provider_id = normalize_image_provider(stored) if stored else DEFAULT_IMAGE_PROVIDER
            except Exception:
                self._image_provider_id = DEFAULT_IMAGE_PROVIDER
        else:
            self._image_provider_id = DEFAULT_IMAGE_PROVIDER
        self.generator = create_image_provider(self._image_provider_id, self.output_dir, memory=memory)

    @classmethod
    def from_media_output_path(
        cls,
        media_output_path: str | None = None,
        *,
        memory: MemoryStore | None = None,
    ) -> "ImageGenerationService":
        """Create the service for provider tools while preserving optional runtime state."""
        return cls(memory=memory, output_dir=media_output_path)

    def generate(self, prompt: str) -> ImageOperationResult:
        """Generate a new image from text."""
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            return self._failed("image_prompt_empty")
        res = self.generator.generate(clean_prompt)
        filepath, error = _unpack_result(res)
        result = self._from_filepath(filepath, "Imagem gerada pela Hana.", error or "image_generation_failed")
        if result.ok:
            self._save_last_generation(
                {
                    "operation": "generate",
                    "user_prompt": clean_prompt,
                    "final_prompt": clean_prompt,
                    "character_id": None,
                    "references": [],
                    "source_image": None,
                },
                result,
            )
        return result

    def generate_character(
        self,
        prompt: str | dict[str, Any],
        *,
        character_id: str = DEFAULT_CHARACTER_ID,
        mode: str = "scene",
        references: list[str] | None = None,
    ) -> ImageOperationResult:
        """Generate a registered character image from a single or multi-character payload."""
        payload = _character_payload_from_args(
            prompt,
            character_id=character_id,
            mode=mode,
            references=references or [],
        )
        try:
            prepared = self._prepare_character_action("character_generate", payload)
            res = self.generator.generate_character(payload)
            filepath, error = _unpack_result(res)
        except Exception as exc:
            return self._failed(str(exc))
        character_label = str(prepared.get("character_id") or character_id)
        result = self._from_filepath(filepath, f"Imagem da personagem {character_label} gerada pela Hana.", error or "character_image_generation_failed")
        if result.ok:
            self._save_last_generation(prepared, result)
        return result

    def edit(
        self,
        prompt: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
        source_image: str | None = None,
        references: list[str] | None = None,
    ) -> ImageOperationResult:
        """Edit or vary an image using uploaded/source images."""
        image_paths = _attachment_paths(attachments, self.output_dir)
        source_path = source_image if source_image and os.path.exists(source_image) else None
        if not source_path and not image_paths:
            image_paths = _clipboard_image_paths(self.output_dir)
        if not source_path and image_paths:
            source_path = image_paths[0]
        res = self.generator.edit_with_references(prompt, source_image_path=source_path, reference_paths=extra_refs, prefix="edit")
        filepath, error = _unpack_result(res)
        result = self._from_filepath(filepath, "Imagem editada pela Hana.", error or "image_edit_failed")
        if result.ok:
            self._save_last_generation(
                {
                    "operation": "edit",
                    "user_prompt": str(prompt or "").strip(),
                    "final_prompt": str(prompt or "").strip(),
                    "character_id": None,
                    "references": extra_refs,
                    "source_image": source_path,
                },
                result,
            )
        return result

    def edit_character(
        self,
        prompt: str | dict[str, Any],
        *,
        character_id: str = DEFAULT_CHARACTER_ID,
        source_image: str = "latest",
        mode: str = "scene",
        references: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ImageOperationResult:
        """Edit a character image while preserving registered identity."""
        image_paths = _attachment_paths(attachments, self.output_dir)
        if not image_paths:
            image_paths = _clipboard_image_paths(self.output_dir)
        selected_source = source_image
        if image_paths:
            selected_source = image_paths[0]
        payload = _character_payload_from_args(
            prompt,
            character_id=character_id,
            mode=mode,
            references=references or [],
            source_image=selected_source,
        )
        try:
            prepared = self._prepare_character_action("character_edit", payload)
            res = self.generator.edit_character(payload)
            filepath, error = _unpack_result(res)
        except Exception as exc:
            return self._failed(str(exc))
        character_label = str(prepared.get("character_id") or character_id)
        result = self._from_filepath(filepath, f"Imagem da personagem {character_label} editada pela Hana.", error or "character_image_edit_failed")
        if result.ok:
            self._save_last_generation(prepared, result)
        return result

    def queue_pending_action(
        self,
        operation: str,
        *,
        prompt: str,
        user_prompt: str = "",
        character_id: str = DEFAULT_CHARACTER_ID,
        source_image: str = "latest",
        mode: str = "scene",
        references: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        channel: str = "control_center",
    ) -> ImageOperationResult:
        """Persist an image action that must be confirmed before the API is called."""
        if not self.memory:
            return self._failed("image_confirmation_state_unavailable")

        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            return self._failed("image_prompt_empty")

        try:
            action = self._build_pending_action(
                operation,
                prompt=clean_prompt,
                user_prompt=user_prompt or clean_prompt,
                character_id=character_id,
                source_image=source_image,
                mode=mode,
                references=references or [],
                attachments=attachments or [],
                channel=channel,
            )
        except Exception as exc:
            return self._failed(str(exc))

        self.memory.set_setting(PENDING_IMAGE_ACTION_KEY, action)
        self._append_terminal_event(
            {
                "kind": "tool_call",
                "source": "image_generation",
                "displayText": (
                    f"Aguardando confirmacao para {self._operation_label(operation)}.\n"
                    f"Prompt pedido: {action['user_prompt']}"
                ),
                "speechText": "",
                "status": "waiting_permission",
                "toolName": f"image.{operation}",
                "metadata": {"tts": False, "pendingImageAction": self.public_pending_action(action)},
            }
        )
        question = f"Quer que eu {self._operation_label(operation)} agora? Responda sim para confirmar ou nao para cancelar."
        return ImageOperationResult(ok=True, text=question, model=DEFAULT_IMAGE_MODEL)

    def handle_pending_confirmation(self, text: str, *, channel: str = "control_center") -> tuple[str | None, ImageOperationResult | None, dict[str, Any] | None]:
        """Execute or cancel the current pending image action from a natural reply."""
        action = self.get_pending_action()
        if not action:
            return None, None, None

        decision = _confirmation_decision(text)
        if decision is None:
            return None, None, None

        self.clear_pending_action()
        if decision == "cancel":
            result = ImageOperationResult(ok=True, text="Cancelado. Nao gerei nem editei nenhuma imagem.", model=DEFAULT_IMAGE_MODEL)
            self._append_terminal_event(
                {
                    "kind": "tool_result",
                    "source": "image_generation",
                    "displayText": "Acao de imagem cancelada pela Nakamura.",
                    "speechText": "",
                    "status": "cancelled",
                    "toolName": f"image.{action.get('operation', 'pending')}",
                    "metadata": {"tts": False, "pendingImageAction": self.public_pending_action(action)},
                }
            )
            return "cancelled", result, action

        result = self.execute_pending_action(action)
        return "confirmed", result, action

    def prompt_lookup_response(self, text: str, *, channel: str = "control_center") -> tuple[ImageOperationResult, dict[str, Any]] | None:
        """Return the last saved image prompt without triggering image generation."""
        if not _looks_like_prompt_lookup(text):
            return None
        last = self.get_last_generation()
        if not last:
            result = ImageOperationResult(ok=False, text="Ainda nao tenho prompt de imagem salvo.", error="last_image_prompt_not_found", model=DEFAULT_IMAGE_MODEL)
            return result, {}

        final_prompt = str(last.get("final_prompt") or "").strip()
        display_text = self._last_prompt_display(last)
        if channel in {"terminal", "cli", "terminal_agent", "voice"}:
            text_result = "Mandei o prompt completo no terminal."
            self._append_terminal_event(
                {
                    "kind": "tool_result",
                    "source": "image_generation",
                    "displayText": display_text,
                    "speechText": "",
                    "status": "success",
                    "toolName": "image.prompt",
                    "metadata": {"tts": False, "imagePrompt": last},
                }
            )
        else:
            text_result = display_text
        result = ImageOperationResult(ok=True, text=text_result, model=str(last.get("model") or DEFAULT_IMAGE_MODEL), saved_path=last.get("saved_path"))
        return result, {"imagePrompt": last, "finalPrompt": final_prompt}

    def get_pending_action(self) -> dict[str, Any] | None:
        """Return the live pending action, clearing it when the TTL expired."""
        if not self.memory:
            return None
        action = self.memory.get_setting(PENDING_IMAGE_ACTION_KEY, None)
        if not isinstance(action, dict) or not action:
            return None
        if float(action.get("expires_at") or 0) <= time.time():
            self.clear_pending_action()
            return None
        return action

    def clear_pending_action(self) -> None:
        """Remove the current pending image action from runtime settings."""
        if self.memory:
            self.memory.set_setting(PENDING_IMAGE_ACTION_KEY, None)

    def public_pending_action(self, action: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a compact, UI-safe view of the pending image action."""
        selected = action or self.get_pending_action() or {}
        return {
            "id": selected.get("id"),
            "operation": selected.get("operation"),
            "characterId": selected.get("character_id"),
            "userPrompt": selected.get("user_prompt"),
            "createdAt": selected.get("created_at"),
            "expiresAt": selected.get("expires_at"),
        }

    def execute_pending_action(self, action: dict[str, Any]) -> ImageOperationResult:
        """Run a confirmed pending image action and persist the final prompt metadata."""
        operation = str(action.get("operation") or "")
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        if operation == "generate":
            result = self.generate(str(args.get("prompt") or action.get("user_prompt") or ""))
        elif operation == "character_generate":
            result = self.generate_character(
                str(args.get("prompt") or action.get("user_prompt") or ""),
                character_id=str(args.get("character_id") or DEFAULT_CHARACTER_ID),
                mode=str(args.get("mode") or "scene"),
                references=args.get("references") if isinstance(args.get("references"), list) else [],
            )
        elif operation == "edit":
            result = self.edit(
                str(args.get("prompt") or action.get("user_prompt") or ""),
                source_image=str(args.get("source_image") or "latest"),
                references=args.get("references") if isinstance(args.get("references"), list) else [],
            )
        elif operation == "character_edit":
            result = self.edit_character(
                str(args.get("prompt") or action.get("user_prompt") or ""),
                character_id=str(args.get("character_id") or DEFAULT_CHARACTER_ID),
                source_image=str(args.get("source_image") or "latest"),
                mode=str(args.get("mode") or "scene"),
                references=args.get("references") if isinstance(args.get("references"), list) else [],
            )
        else:
            result = self._failed("unknown_pending_image_action")

        if result.ok:
            self._save_last_generation(action, result)
        return result

    def get_last_generation(self) -> dict[str, Any] | None:
        """Return metadata for the last successful image generation/edit."""
        if not self.memory:
            return None
        value = self.memory.get_setting(LAST_IMAGE_GENERATION_KEY, None)
        return value if isinstance(value, dict) and value else None

    def run_inferred(self, text: str, attachments: list[dict[str, Any]] | None = None) -> tuple[str | None, ImageOperationResult | None]:
        """Run an inferred explicit image operation from chat text."""
        operation = infer_image_operation(text, attachments)
        if operation == "edit":
            return operation, self.edit(text, attachments=attachments)
        if operation == "character_edit":
            character_id = detect_character_id(text) or DEFAULT_CHARACTER_ID
            return operation, self.edit_character(text, character_id=character_id, attachments=attachments)
        if operation == "character_generate":
            character_id = detect_character_id(text) or DEFAULT_CHARACTER_ID
            return operation, self.generate_character(text, character_id=character_id)
        if operation == "generate":
            return operation, self.generate(text)
        return None, None

    def open_result(self, result: ImageOperationResult, *, label: str = "IMAGE GEN") -> None:
        """Open a generated image on the desktop when the calling channel expects it."""
        if result.saved_path:
            self.generator._open_if_possible(result.saved_path, label)

    def _build_pending_action(
        self,
        operation: str,
        *,
        prompt: str,
        user_prompt: str,
        character_id: str,
        source_image: str,
        mode: str,
        references: list[str],
        attachments: list[dict[str, Any]],
        channel: str,
    ) -> dict[str, Any]:
        """Create the persisted payload for a deferred image action."""
        created_at = time.time()
        source_path = self._resolved_source_image(source_image, attachments) if operation in {"edit", "character_edit"} else None
        action: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "operation": operation,
            "user_prompt": str(user_prompt or prompt).strip(),
            "created_at": created_at,
            "expires_at": created_at + PENDING_IMAGE_ACTION_TTL_SECONDS,
            "channel": channel,
            "model": DEFAULT_IMAGE_MODEL,
            "args": {
                "prompt": prompt,
                "character_id": character_id,
                "source_image": source_path or source_image,
                "mode": mode,
                "references": list(references or []),
            },
        }

        if operation in {"character_generate", "character_edit"}:
            payload = {
                "character": character_id,
                "prompt": prompt,
                "mode": mode,
                "references": references or [],
                "source_image": source_path or source_image,
            }
            action.update(self._prepare_character_action(operation, payload))
        else:
            action.update(
                {
                    "final_prompt": prompt,
                    "character_id": None,
                    "references": [],
                    "source_image": source_path or source_image if operation == "edit" else None,
                }
            )
        return action

    def _prepare_character_action(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Prepare character prompt metadata without calling the Gemini Image API."""
        request = parse_character_image_request(payload)
        refs = resolve_request_reference_paths(request)
        final_prompt = compose_character_prompt(request, edit=operation == "character_edit")
        character_label = request.character_id if len(request.character_ids) == 1 else ", ".join(request.character_ids)
        return {
            "operation": operation,
            "user_prompt": request.prompt,
            "final_prompt": final_prompt,
            "character_id": character_label,
            "character_ids": list(request.character_ids),
            "references": refs,
            "source_image": request.source_image or None,
        }

    def _resolved_source_image(self, source_image: str, attachments: list[dict[str, Any]] | None) -> str | None:
        """Resolve uploaded or clipboard image paths for deferred edit actions."""
        if source_image and source_image != "latest" and os.path.exists(source_image):
            return os.path.abspath(source_image)
        image_paths = _attachment_paths(attachments, self.output_dir)
        if not image_paths:
            image_paths = _clipboard_image_paths(self.output_dir)
        return image_paths[0] if image_paths else None

    def _save_last_generation(self, action: dict[str, Any], result: ImageOperationResult) -> None:
        """Persist prompt metadata for the last successful image output."""
        if not self.memory or not result.ok:
            return
        payload = {
            "operation": action.get("operation"),
            "user_prompt": action.get("user_prompt"),
            "final_prompt": action.get("final_prompt") or action.get("user_prompt"),
            "character_id": action.get("character_id"),
            "character_ids": action.get("character_ids") or [],
            "references": action.get("references") or [],
            "source_image": action.get("source_image"),
            "saved_path": result.saved_path,
            "media": result.media,
            "model": result.model,
            "created_at": time.time(),
        }
        self.memory.set_setting(LAST_IMAGE_GENERATION_KEY, payload)

    def _append_terminal_event(self, payload: dict[str, Any]) -> None:
        """Append a Terminal Agent event when runtime memory is available."""
        if not self.memory:
            return
        try:
            from hana_agent_oss.api.services.terminal_agent import append_terminal_event

            append_terminal_event(self.memory, payload)
        except Exception:
            return

    @staticmethod
    def _operation_label(operation: str) -> str:
        """Return a concise Portuguese action label for confirmation prompts."""
        labels = {
            "generate": "gere essa imagem",
            "character_generate": "gere essa imagem de personagem",
            "edit": "edite essa imagem",
            "character_edit": "edite essa personagem",
        }
        return labels.get(operation, "execute essa imagem")

    @staticmethod
    def _last_prompt_display(last: dict[str, Any]) -> str:
        """Format the last image prompt for terminal/chat display."""
        return (
            "PROMPT FINAL DA ULTIMA IMAGEM\n"
            f"Operacao: {last.get('operation') or 'image'}\n"
            f"Personagem: {last.get('character_id') or 'nenhum'}\n"
            f"Arquivo: {last.get('saved_path') or 'n/a'}\n\n"
            f"{last.get('final_prompt') or last.get('user_prompt') or ''}"
        )

    def _from_filepath(self, filepath: str | None, success_text: str, failure_error: str) -> ImageOperationResult:
        if not filepath:
            return self._failed(failure_error)
        return ImageOperationResult(
            ok=True,
            text=success_text,
            media=[media_item_for_path(filepath)],
            model=getattr(self.generator, "default_model", DEFAULT_IMAGE_MODEL),
            saved_path=filepath,
        )

    def _failed(self, error: str) -> ImageOperationResult:
        return ImageOperationResult(
            ok=False,
            text=f"Falha ao gerar imagem: {error}",
            media=[failed_media_item(error)],
            error=error,
            model=getattr(self.generator, "default_model", DEFAULT_IMAGE_MODEL),
        )
