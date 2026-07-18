"""
Image generation and editing for Hana via Google Gemini image models.

The model defaults to gemini-3.1-flash-image-preview. The output directory
is resolved from SQLite portabilidade_config -> mediaOutputPath, falling
back to ~/Pictures/Hana Artista. No legacy CONFIG dependency.
"""

from __future__ import annotations

import datetime
import glob
import logging
import os
import re
import threading
import base64

from google import genai
from google.genai import types

from hana_agent_oss.modules.vision.character_library import (
    DEFAULT_CHARACTER_ROOT,
    compose_character_prompt,
    parse_character_image_request,
    resolve_request_reference_paths,
    resolve_source_image_path,
)
from hana_agent_oss.modules.vision.image_provider import BaseImageProvider, ImageProviderResult

logger = logging.getLogger(__name__)


DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image-preview"


def _default_output_dir():
    """Auto-detect the user's Pictures folder and create Hana Artista."""
    try:
        pictures = os.path.join(os.path.expanduser("~"), "Pictures", "Hana Artista")
        os.makedirs(pictures, exist_ok=True)
        return pictures
    except Exception:
        fallback = os.path.join("C:\\", "Hana Artista")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def resolve_output_dir(memory=None, output_dir: str | None = None) -> str:
    """Resolve the image output folder from explicit input, MemoryStore, or fallback."""
    if output_dir:
        selected = output_dir
    else:
        selected = None
        if memory is not None:
            try:
                config = memory.get_setting("portabilidade_config", {})
                if isinstance(config, dict):
                    selected = config.get("mediaOutputPath")
            except Exception:
                selected = None
    if selected:
        selected_str = str(selected).strip()
        if not selected_str or selected_str in (".", "./", "data", "./data", "data/", "./data/"):
            selected_str = _default_output_dir()
        resolved = os.path.abspath(os.path.expanduser(os.path.expandvars(selected_str)))
        os.makedirs(resolved, exist_ok=True)
        return resolved
    return _default_output_dir()


def _mime_type_for_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/png")


class HanaImageGen(BaseImageProvider):
    """Google Gemini image generator/editor with character references. Inherits BaseImageProvider."""

    def __init__(self, output_dir: str | None = None, memory=None):
        resolved_dir = resolve_output_dir(memory=memory, output_dir=output_dir)
        super().__init__(output_dir=resolved_dir)

        self.provider_id = "gemini_api"
        self.default_model = DEFAULT_IMAGE_MODEL
        self.modelo = DEFAULT_IMAGE_MODEL
        self.client = None
        self._init_client()

        logger.info("[IMAGE GEN] Inicializado | Modelo: %s | Pasta: %s", self._model_id(), self.output_dir)


    def _model_id(self) -> str:
        """Return the active image generation model ID."""
        return self.modelo or DEFAULT_IMAGE_MODEL

    def _init_client(self):
        """Initialize Google GenAI client from environment variables."""
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.error("[IMAGE GEN] GEMINI_API_KEY nao encontrada no .env.")
            return
        try:
            self.client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.error("[IMAGE GEN] Erro ao inicializar cliente GenAI: %s", e)



    def _save_image_from_response(self, response, prompt: str, prefix: str = "") -> str | None:
        """Extract inline image data from Gemini response and save it."""
        if not response.candidates or not response.candidates[0].content:
            logger.warning("[IMAGE GEN] Resposta vazia do modelo.")
            return None

        for part in response.candidates[0].content.parts:
            image_bytes = self._image_bytes_from_part(part)
            if image_bytes:
                return self._save_bytes(image_bytes, prompt, prefix=prefix)

        logger.warning("[IMAGE GEN] Nenhuma imagem encontrada na resposta.")
        return None

    @staticmethod
    def _image_bytes_from_part(part) -> bytes | None:
        """Read image bytes from different google-genai SDK response shapes."""
        inline_data = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
        if inline_data:
            data = getattr(inline_data, "data", None)
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                try:
                    return base64.b64decode(data, validate=False)
                except Exception:
                    return data.encode("utf-8")

        as_image = getattr(part, "as_image", None)
        if callable(as_image):
            try:
                image = as_image()
                image_bytes = getattr(image, "image_bytes", None)
                if isinstance(image_bytes, bytes):
                    return image_bytes
            except Exception:
                return None
        return None

    def _image_part(self, path: str):
        with open(path, "rb") as file:
            image_bytes = file.read()
        return types.Part.from_bytes(data=image_bytes, mime_type=_mime_type_for_path(path))

    def _content_parts(self, prompt: str, image_paths: list[str] | None = None):
        paths = [path for path in image_paths or [] if path and os.path.exists(path)]
        if not paths:
            return prompt

        parts = [self._image_part(path) for path in paths]
        parts.append(types.Part.from_text(text=prompt))
        return parts

    def _generate_content(self, contents):
        return self.client.models.generate_content(
            model=self._model_id(),
            contents=contents,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )

    def generate(self, prompt: str) -> str | None:
        """Generate an image from a text prompt."""
        if not self.client:
            logger.error("[IMAGE GEN] Cliente nao inicializado.")
            return None

        logger.info("[IMAGE GEN] Gerando: %r", str(prompt or "")[:80])

        try:
            response = self._generate_content(prompt)
            return self._save_image_from_response(response, prompt, prefix="gen")
        except Exception as e:
            logger.error("[IMAGE GEN] Erro ao gerar imagem: %s", e)
            return None

    def generate_with_references(self, prompt: str, reference_paths: list[str] | None = None, *, prefix: str = "char") -> str | None:
        """Generate an image using reference images plus text prompt."""
        if not self.client:
            logger.error("[IMAGE GEN] Cliente nao inicializado.")
            return None

        refs = [path for path in reference_paths or [] if path and os.path.exists(path)]
        logger.info("[IMAGE GEN] Gerando com %d referencia(s): %r", len(refs), str(prompt or "")[:80])

        try:
            response = self._generate_content(self._content_parts(prompt, refs))
            return self._save_image_from_response(response, prompt, prefix=prefix)
        except Exception as e:
            logger.error("[IMAGE GEN] Erro ao gerar imagem com referencias: %s", e)
            return None

    def get_latest_image(self) -> str | None:
        """Return latest generated image path (delegates to base class)."""
        return self._get_latest_image()


    def edit(self, prompt: str, image_path: str | None = None) -> str | None:
        """Edit an existing image with a text prompt."""
        return self.edit_with_references(prompt, source_image_path=image_path, reference_paths=None, prefix="edit")

    def edit_with_references(
        self,
        prompt: str,
        *,
        source_image_path: str | None = None,
        reference_paths: list[str] | None = None,
        prefix: str = "edit_char",
    ) -> str | None:
        """Edit an image using source image plus optional identity references."""
        if not self.client:
            logger.error("[IMAGE EDIT] Cliente nao inicializado.")
            return None

        source_path = source_image_path or self.get_latest_image()
        if not source_path or not os.path.exists(source_path):
            logger.error("[IMAGE EDIT] Nenhuma imagem encontrada para editar. Path: %s", source_path)
            return None

        image_paths = [source_path]
        for ref_path in reference_paths or []:
            if ref_path and os.path.exists(ref_path) and os.path.abspath(ref_path).lower() != os.path.abspath(source_path).lower():
                image_paths.append(ref_path)

        logger.info(
            "[IMAGE EDIT] Editando %r com %d referencia(s): %r",
            os.path.basename(source_path),
            max(0, len(image_paths) - 1),
            str(prompt or "")[:80],
        )

        try:
            response = self._generate_content(self._content_parts(prompt, image_paths))
            return self._save_image_from_response(response, prompt, prefix=prefix)
        except Exception as e:
            logger.error("[IMAGE EDIT] Erro ao editar imagem: %s", e)
            return None

    def generate_character(self, raw_payload: str | dict) -> str | None:
        """Generate one or more registered characters using identity references."""
        request = parse_character_image_request(
            raw_payload,
            default_character_id="hana",
            root_dir=DEFAULT_CHARACTER_ROOT,
        )
        refs = resolve_request_reference_paths(request)
        prompt = compose_character_prompt(request, edit=False)
        prefix = f"char_{'_'.join(request.character_ids)}_{request.mode}"
        return self.generate_with_references(prompt, refs, prefix=prefix)

    def edit_character(self, raw_payload: str | dict) -> str | None:
        """Edit latest/source image while preserving registered character identities."""
        request = parse_character_image_request(
            raw_payload,
            default_character_id="hana",
            root_dir=DEFAULT_CHARACTER_ROOT,
        )
        refs = resolve_request_reference_paths(request)
        source_path = resolve_source_image_path(request.source_image)
        prompt = compose_character_prompt(request, edit=True)
        prefix = f"edit_{'_'.join(request.character_ids)}_{request.mode}"
        return self.edit_with_references(prompt, source_image_path=source_path, reference_paths=refs, prefix=prefix)

    def generate_and_show(self, prompt: str):
        """Generate and open image in a background thread."""
        def _worker():
            filepath = self.generate(prompt)
            self._open_if_possible(filepath, "IMAGE GEN")

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        logger.info("[IMAGE GEN] Thread de geracao iniciada: %r", str(prompt or "")[:50])

    def edit_and_show(self, prompt: str, image_path: str | None = None):
        """Edit and open image in a background thread."""
        def _worker():
            filepath = self.edit(prompt, image_path=image_path)
            self._open_if_possible(filepath, "IMAGE EDIT")

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        logger.info("[IMAGE EDIT] Thread de edicao iniciada: %r", str(prompt or "")[:50])

    def generate_character_and_show(self, raw_payload: str | dict):
        """Generate a registered character image and open it."""
        def _worker():
            filepath = self.generate_character(raw_payload)
            self._open_if_possible(filepath, "IMAGE GEN")

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        logger.info("[IMAGE GEN] Thread de personagem iniciada.")

    def edit_character_and_show(self, raw_payload: str | dict):
        """Edit a registered character image and open it."""
        def _worker():
            filepath = self.edit_character(raw_payload)
            self._open_if_possible(filepath, "IMAGE EDIT")

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        logger.info("[IMAGE EDIT] Thread de personagem iniciada.")

