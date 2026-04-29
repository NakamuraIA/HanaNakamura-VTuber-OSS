"""
Image generation and editing for Hana via Google Gemini image models.

The model is configurable through IMAGE_GENERATION.model and defaults to
gemini-3.1-flash-image-preview. Legacy text-only tags still work, while the
character-aware methods add reference images and identity rules.
"""

from __future__ import annotations

import datetime
import glob
import logging
import os
import re
import threading

from google import genai
from google.genai import types

from src.config.config_loader import CONFIG
from src.modules.vision.character_library import (
    compose_character_prompt,
    parse_character_image_request,
    resolve_reference_paths,
    resolve_source_image_path,
)

logger = logging.getLogger(__name__)


DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image-preview"


def _resolve_output_dir():
    """Auto-detect the user's Pictures folder and create Hana Artista."""
    try:
        pictures = os.path.join(os.path.expanduser("~"), "Pictures", "Hana Artista")
        os.makedirs(pictures, exist_ok=True)
        return pictures
    except Exception:
        fallback = os.path.join("C:\\", "Hana Artista")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _image_settings() -> dict:
    settings = CONFIG.get("IMAGE_GENERATION", {})
    return settings if isinstance(settings, dict) else {}


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


DEFAULT_OUTPUT_DIR = _resolve_output_dir()


class HanaImageGen:
    """Google Gemini image generator/editor with optional character references."""

    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR):
        configured_output = str(_image_settings().get("output_dir") or "").strip()
        if configured_output:
            output_dir = os.path.abspath(os.path.expanduser(os.path.expandvars(configured_output)))

        self.output_dir = output_dir
        self.modelo = str(_image_settings().get("model") or _image_settings().get("model_id") or DEFAULT_IMAGE_MODEL).strip()
        self.client = None
        self.last_image_path: str | None = None
        self._init_client()

        os.makedirs(self.output_dir, exist_ok=True)
        logger.info("[IMAGE GEN] Inicializado | Modelo: %s | Pasta: %s", self._model_id(), self.output_dir)

    def _model_id(self) -> str:
        settings = _image_settings()
        model = str(settings.get("model") or settings.get("model_id") or self.modelo or DEFAULT_IMAGE_MODEL).strip()
        return model or DEFAULT_IMAGE_MODEL

    def _init_client(self):
        """Initialize Google GenAI client."""
        api_key = os.getenv("GEMINI_API_KEY") or CONFIG.get("GEMINI_API_KEY")
        if not api_key:
            logger.error("[IMAGE GEN] GEMINI_API_KEY nao encontrada no .env.")
            return
        try:
            self.client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.error("[IMAGE GEN] Erro ao inicializar cliente GenAI: %s", e)

    def _sanitize_filename(self, prompt: str, prefix: str = "") -> str:
        """Create a safe file name from the prompt."""
        slug = re.sub(r"[^\w\s-]", "", str(prompt or "")[:50]).strip()
        slug = re.sub(r"\s+", "_", slug) or "image"
        safe_prefix = re.sub(r"[^\w-]", "_", str(prefix or "").strip()).strip("_")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = f"{safe_prefix}_" if safe_prefix else ""
        return f"{timestamp}_{tag}{slug}.png"

    def _save_image_from_response(self, response, prompt: str, prefix: str = "") -> str | None:
        """Extract inline image data from Gemini response and save it."""
        if not response.candidates or not response.candidates[0].content:
            logger.warning("[IMAGE GEN] Resposta vazia do modelo.")
            return None

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                filename = self._sanitize_filename(prompt, prefix=prefix)
                filepath = os.path.join(self.output_dir, filename)

                with open(filepath, "wb") as file:
                    file.write(part.inline_data.data)

                self.last_image_path = filepath
                logger.info("[IMAGE GEN] Imagem salva: %s", filepath)
                return filepath

        logger.warning("[IMAGE GEN] Nenhuma imagem encontrada na resposta.")
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
        """Return latest generated image path."""
        if self.last_image_path and os.path.exists(self.last_image_path):
            return self.last_image_path

        pattern = os.path.join(self.output_dir, "*.png")
        files = glob.glob(pattern)
        if not files:
            return None

        return max(files, key=os.path.getmtime)

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
        """Generate a registered character using identity prompt and references."""
        settings = _image_settings()
        request = parse_character_image_request(
            raw_payload,
            default_character_id=str(settings.get("default_character") or "hana"),
            root_dir=os.path.abspath(str(settings.get("character_root") or os.path.join("data", "characters"))),
        )
        refs = resolve_reference_paths(request.profile, request.references)
        prompt = compose_character_prompt(request, edit=False)
        prefix = f"char_{request.character_id}_{request.mode}"
        return self.generate_with_references(prompt, refs, prefix=prefix)

    def edit_character(self, raw_payload: str | dict) -> str | None:
        """Edit latest/source image while preserving a registered character."""
        settings = _image_settings()
        request = parse_character_image_request(
            raw_payload,
            default_character_id=str(settings.get("default_character") or "hana"),
            root_dir=os.path.abspath(str(settings.get("character_root") or os.path.join("data", "characters"))),
        )
        refs = resolve_reference_paths(request.profile, request.references)
        source_path = resolve_source_image_path(request.source_image)
        prompt = compose_character_prompt(request, edit=True)
        prefix = f"edit_{request.character_id}_{request.mode}"
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

    def _open_if_possible(self, filepath: str | None, label: str):
        if not filepath:
            return
        try:
            os.startfile(filepath)
        except Exception as e:
            logger.error("[%s] Erro ao abrir imagem: %s", label, e)
