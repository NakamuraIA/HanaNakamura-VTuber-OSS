"""OpenRouter image generation provider for Hana.

Uses the OpenRouter Chat Completions API with ``modalities: ["image", "text"]``
to generate and edit images via models like Riverflow V2.5 Pro/Fast.

The provider reuses the same ``OPENROUTER_API_KEY`` environment variable already
configured for the LLM provider — no extra credentials needed.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from hana_agent_oss.modules.vision.image_provider import BaseImageProvider, ImageProviderResult
from hana_agent_oss.providers.provider_selector.openrouter.catalog import (
    OPENROUTER_BASE_URL,
    openrouter_headers,
)

logger = logging.getLogger(__name__)

# Default image model for OpenRouter generation.
DEFAULT_OPENROUTER_IMAGE_MODEL = "sourceful/riverflow-v2.5-pro"
OPENROUTER_CHAT_COMPLETIONS_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_IMAGE_TIMEOUT_SECONDS = 180  # Image gen can be slow


def _mime_type_for_path(path: str) -> str:
    """Return MIME type based on file extension."""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/png")


def _image_to_data_url(path: str) -> str:
    """Read an image file and return as a base64 data URL."""
    with open(path, "rb") as f:
        raw = f.read()
    mime = _mime_type_for_path(path)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _decode_base64_image(data_url: str) -> bytes:
    """Extract raw image bytes from a base64 data URL response."""
    value = str(data_url or "")
    if "," in value and value.lower().startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value, validate=False)


class OpenRouterImageProvider(BaseImageProvider):
    """Image generation provider using OpenRouter Chat Completions API.

    Supports text-to-image and image-to-image via models like
    ``sourceful/riverflow-v2.5-pro`` and ``sourceful/riverflow-v2.5-fast``.
    """

    provider_id = "openrouter"

    def __init__(
        self,
        output_dir: str,
        model: str | None = None,
        memory: Any = None,
        reasoning: str | None = None,
    ) -> None:
        super().__init__(output_dir=output_dir)
        self.default_model = str(model or "").strip() or DEFAULT_OPENROUTER_IMAGE_MODEL
        self.reasoning = str(reasoning or "").strip() or "medium"

        # Read optional image config from memory settings.
        if memory is not None:
            try:
                img_config = memory.get_setting("image_config", {}) or {}
                if isinstance(img_config, dict):
                    if not model and img_config.get("openrouterImageModel"):
                        self.default_model = str(img_config["openrouterImageModel"]).strip()
                    if img_config.get("openrouterReasoning"):
                        self.reasoning = str(img_config["openrouterReasoning"]).strip()
            except Exception:
                pass

        logger.info(
            "[OPENROUTER IMAGE] Initialized | Model: %s | Reasoning: %s | Dir: %s",
            self.default_model,
            self.reasoning,
            self.output_dir,
        )

    # ------------------------------------------------------------------
    # Public interface (matches ImageProvider protocol)
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> ImageProviderResult:
        """Generate an image from a text prompt."""
        clean = str(prompt or "").strip()
        if not clean:
            return ImageProviderResult(ok=False, error="image_prompt_empty", model=self.default_model)
        logger.info("[OPENROUTER IMAGE] Generating: %r", clean[:80])
        return self._call_api(prompt=clean, image_paths=[], prefix="gen")

    def generate_with_references(
        self,
        prompt: str,
        reference_paths: list[str] | None = None,
        *,
        prefix: str = "char",
    ) -> ImageProviderResult:
        """Generate with reference images attached."""
        refs = [p for p in (reference_paths or []) if p and os.path.exists(p)]
        logger.info("[OPENROUTER IMAGE] Generating with %d ref(s): %r", len(refs), str(prompt or "")[:80])
        return self._call_api(prompt=prompt, image_paths=refs, prefix=prefix)

    def edit_with_references(
        self,
        prompt: str,
        *,
        source_image_path: str | None = None,
        reference_paths: list[str] | None = None,
        prefix: str = "edit",
    ) -> ImageProviderResult:
        """Edit an image using source + optional reference images."""
        source = source_image_path or self._get_latest_image()
        if not source or not os.path.exists(source):
            logger.error("[OPENROUTER IMAGE] No source image found for edit.")
            return ImageProviderResult(ok=False, error="no_source_image_for_edit", model=self.default_model)

        image_paths = [source]
        for ref in (reference_paths or []):
            if ref and os.path.exists(ref) and os.path.abspath(ref).lower() != os.path.abspath(source).lower():
                image_paths.append(ref)

        logger.info(
            "[OPENROUTER IMAGE] Editing %r with %d ref(s): %r",
            os.path.basename(source),
            max(0, len(image_paths) - 1),
            str(prompt or "")[:80],
        )
        return self._call_api(prompt=prompt, image_paths=image_paths, prefix=prefix)

    # ------------------------------------------------------------------
    # Character convenience wrappers (match HanaImageGen interface)
    # ------------------------------------------------------------------

    def generate_character(self, raw_payload: str | dict) -> str | None:
        """Generate registered character image (HanaImageGen-compatible interface)."""
        from hana_agent_oss.modules.vision.character_library import (
            DEFAULT_CHARACTER_ROOT,
            compose_character_prompt,
            parse_character_image_request,
            resolve_request_reference_paths,
        )
        request = parse_character_image_request(raw_payload, default_character_id="hana", root_dir=DEFAULT_CHARACTER_ROOT)
        refs = resolve_request_reference_paths(request)
        prompt = compose_character_prompt(request, edit=False)
        prefix = f"char_{'_'.join(request.character_ids)}_{request.mode}"
        result = self.generate_with_references(prompt, refs, prefix=prefix)
        return result.filepath

    def edit_character(self, raw_payload: str | dict) -> str | None:
        """Edit registered character image (HanaImageGen-compatible interface)."""
        from hana_agent_oss.modules.vision.character_library import (
            DEFAULT_CHARACTER_ROOT,
            compose_character_prompt,
            parse_character_image_request,
            resolve_request_reference_paths,
            resolve_source_image_path,
        )
        request = parse_character_image_request(raw_payload, default_character_id="hana", root_dir=DEFAULT_CHARACTER_ROOT)
        refs = resolve_request_reference_paths(request)
        source_path = resolve_source_image_path(request.source_image)
        prompt = compose_character_prompt(request, edit=True)
        prefix = f"edit_{'_'.join(request.character_ids)}_{request.mode}"
        result = self.edit_with_references(prompt, source_image_path=source_path, reference_paths=refs, prefix=prefix)
        return result.filepath

    # ------------------------------------------------------------------
    # HanaImageGen-compatible convenience methods
    # ------------------------------------------------------------------

    def get_latest_image(self) -> str | None:
        """Return the latest generated image path."""
        return self._get_latest_image()

    def edit(self, prompt: str, image_path: str | None = None) -> str | None:
        """Edit an existing image (HanaImageGen-compatible interface)."""
        result = self.edit_with_references(prompt, source_image_path=image_path, prefix="edit")
        return result.filepath

    # ------------------------------------------------------------------
    # Internal API call
    # ------------------------------------------------------------------

    def _call_api(
        self,
        prompt: str,
        image_paths: list[str],
        prefix: str,
    ) -> ImageProviderResult:
        """Build and send an OpenRouter Chat Completions request for image generation."""
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return ImageProviderResult(
                ok=False,
                error="missing_credentials:OPENROUTER_API_KEY",
                model=self.default_model,
            )

        # Build content parts.
        content: list[dict[str, Any]] = []
        content.append({"type": "text", "text": prompt})
        for path in image_paths:
            if path and os.path.exists(path):
                try:
                    data_url = _image_to_data_url(path)
                    content.append({"type": "image_url", "image_url": {"url": data_url}})
                except Exception as exc:
                    logger.warning("[OPENROUTER IMAGE] Failed to encode image %s: %s", path, exc)

        # Determine the correct modalities payload for OpenRouter.
        # Models that only output images (like FLUX, Recraft) fail with 404 if "text" is requested.
        from hana_agent_oss.providers.provider_selector.openrouter.catalog import get_openrouter_model
        model_spec = get_openrouter_model(self.default_model)
        
        output_mods = []
        if model_spec and isinstance(model_spec, dict):
            output_mods = model_spec.get("outputModalities") or []
            
        if "text" in output_mods:
            modalities = ["image", "text"]
        elif "image" in output_mods:
            modalities = ["image"]
        else:
            # Fallback based on known multimodal image model naming
            lower_model = self.default_model.lower()
            if "gemini" in lower_model or "gpt" in lower_model or "banana" in lower_model:
                modalities = ["image", "text"]
            else:
                modalities = ["image"]

        payload: dict[str, Any] = {
            "model": self.default_model,
            "messages": [{"role": "user", "content": content}],
            "modalities": modalities,
            "stream": False,
        }
        if self.reasoning:
            payload["reasoning"] = {"effort": self.reasoning}


        try:
            response_data = self._post_request(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            if exc.code == 400 and "reasoning" in detail.lower() and "reasoning" in payload:
                logger.warning("[OPENROUTER IMAGE] Model does not support reasoning parameter. Retrying request without reasoning.")
                del payload["reasoning"]
                try:
                    response_data = self._post_request(payload)
                except urllib.error.HTTPError as retry_exc:
                    detail_retry = retry_exc.read().decode("utf-8", errors="replace") if retry_exc.fp else str(retry_exc)
                    error_msg = f"openrouter_image_http_{retry_exc.code}:{detail_retry[:500]}"
                    logger.error("[OPENROUTER IMAGE] HTTP error on retry: %s", error_msg)
                    return ImageProviderResult(ok=False, error=error_msg, model=self.default_model)
                except Exception as retry_exc:
                    error_msg = f"openrouter_image_error_on_retry:{retry_exc}"
                    logger.error("[OPENROUTER IMAGE] Request error on retry: %s", error_msg)
                    return ImageProviderResult(ok=False, error=error_msg, model=self.default_model)
            else:
                error_msg = f"openrouter_image_http_{exc.code}:{detail[:500]}"
                logger.error("[OPENROUTER IMAGE] HTTP error: %s", error_msg)
                return ImageProviderResult(ok=False, error=error_msg, model=self.default_model)
        except Exception as exc:
            logger.error("[OPENROUTER IMAGE] Request error: %s", exc)
            return ImageProviderResult(ok=False, error=f"openrouter_image_error:{exc}", model=self.default_model)

        # Extract image from response.
        filepath = self._extract_and_save_image(response_data, prompt, prefix)
        text = self._extract_text(response_data)

        if filepath:
            return ImageProviderResult(ok=True, filepath=filepath, text=text, model=self.default_model)
        return ImageProviderResult(
            ok=False,
            error="openrouter_image_no_image_in_response",
            text=text,
            model=self.default_model,
        )

    def _post_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a POST request to OpenRouter Chat Completions."""
        body = json.dumps(payload).encode("utf-8")
        headers = openrouter_headers(include_auth=True)
        request = urllib.request.Request(
            OPENROUTER_CHAT_COMPLETIONS_URL,
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=OPENROUTER_IMAGE_TIMEOUT_SECONDS) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        if not raw_body:
            return {}
        return json.loads(raw_body)

    def _extract_and_save_image(self, response_data: dict[str, Any], prompt: str, prefix: str) -> str | None:
        """Parse the OpenRouter response and save the first image found."""
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            logger.warning("[OPENROUTER IMAGE] Empty response (no choices).")
            return None

        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        if not isinstance(message, dict):
            return None

        # Images come in message.images[] array as data URLs.
        images = message.get("images")
        if isinstance(images, list):
            for img in images:
                if not isinstance(img, dict):
                    continue
                img_url_obj = img.get("image_url") if isinstance(img.get("image_url"), dict) else {}
                data_url = str(img_url_obj.get("url") or "")
                if data_url:
                    try:
                        image_bytes = _decode_base64_image(data_url)
                        return self._save_bytes(image_bytes, prompt, prefix=prefix)
                    except Exception as exc:
                        logger.warning("[OPENROUTER IMAGE] Failed to decode image: %s", exc)

        # Fallback: some models may return inline base64 in content parts.
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "image_url":
                    img_data = part.get("image_url", {})
                    data_url = str(img_data.get("url") or "") if isinstance(img_data, dict) else ""
                    if data_url:
                        try:
                            image_bytes = _decode_base64_image(data_url)
                            return self._save_bytes(image_bytes, prompt, prefix=prefix)
                        except Exception as exc:
                            logger.warning("[OPENROUTER IMAGE] Failed to decode fallback image: %s", exc)

        logger.warning("[OPENROUTER IMAGE] No image found in response.")
        return None

    @staticmethod
    def _extract_text(response_data: dict[str, Any]) -> str:
        """Extract text content from the response."""
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                str(p.get("text") or "").strip()
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            return "\n".join(p for p in parts if p).strip()
        return ""
