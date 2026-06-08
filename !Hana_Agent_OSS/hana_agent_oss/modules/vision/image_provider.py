"""Abstract image provider contract and shared base class for Hana image generation.

All image providers (Gemini, OpenRouter, etc.) implement the same interface
so that ImageGenerationService can dispatch operations transparently.
The active provider is selected at runtime from the ``image_provider`` setting
stored in MemoryStore — Hana (the LLM) never needs to know which backend
is generating the images.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider result
# ---------------------------------------------------------------------------

@dataclass
class ImageProviderResult:
    """Normalized result returned by any image provider."""

    ok: bool
    filepath: str | None = None
    text: str = ""
    model: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Provider protocol (structural typing)
# ---------------------------------------------------------------------------

@runtime_checkable
class ImageProvider(Protocol):
    """Contract that all image generation providers must implement."""

    provider_id: str
    default_model: str
    output_dir: str

    def generate(self, prompt: str) -> ImageProviderResult:
        """Generate an image from a text prompt and save to output_dir."""
        ...

    def generate_with_references(
        self,
        prompt: str,
        reference_paths: list[str] | None = None,
        *,
        prefix: str = "char",
    ) -> ImageProviderResult:
        """Generate an image using reference images plus text prompt."""
        ...

    def edit_with_references(
        self,
        prompt: str,
        *,
        source_image_path: str | None = None,
        reference_paths: list[str] | None = None,
        prefix: str = "edit",
    ) -> ImageProviderResult:
        """Edit an image using a source image plus optional references."""
        ...


# ---------------------------------------------------------------------------
# Shared base class with common file/utility logic
# ---------------------------------------------------------------------------

class BaseImageProvider:
    """Shared utilities for all image providers (filename, save, open, etc.)."""

    provider_id: str = "base"
    default_model: str = "unknown"

    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        self.last_image_path: str | None = None
        os.makedirs(self.output_dir, exist_ok=True)

    def _sanitize_filename(self, prompt: str, prefix: str = "") -> str:
        """Create a safe file name from the prompt."""
        slug = re.sub(r"[^\w\s-]", "", str(prompt or "")[:50]).strip()
        slug = re.sub(r"\s+", "_", slug) or "image"
        safe_prefix = re.sub(r"[^\w-]", "_", str(prefix or "").strip()).strip("_")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = f"{safe_prefix}_" if safe_prefix else ""
        return f"{timestamp}_{tag}{slug}.png"

    def _save_bytes(self, image_bytes: bytes, prompt: str, prefix: str = "") -> str | None:
        """Save raw image bytes to output_dir and return the file path."""
        if not image_bytes:
            return None
        filename = self._sanitize_filename(prompt, prefix=prefix)
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        self.last_image_path = filepath
        logger.info("[%s] Image saved: %s", self.provider_id.upper(), filepath)
        return filepath

    def _open_if_possible(self, filepath: str | None, label: str) -> None:
        """Open a generated image on the desktop (Windows startfile)."""
        if not filepath:
            return
        try:
            os.startfile(filepath)  # type: ignore[attr-defined]
        except Exception as e:
            logger.error("[%s] Error opening image: %s", label, e)

    def _get_latest_image(self) -> str | None:
        """Return the latest generated image path."""
        if self.last_image_path and os.path.exists(self.last_image_path):
            return self.last_image_path
        import glob
        pattern = os.path.join(self.output_dir, "*.png")
        files = glob.glob(pattern)
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    def _result_from_filepath(self, filepath: str | None, error_code: str) -> ImageProviderResult:
        """Build a provider result from a saved filepath or error."""
        if filepath:
            return ImageProviderResult(ok=True, filepath=filepath, model=self.default_model)
        return ImageProviderResult(ok=False, error=error_code, model=self.default_model)


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

# Image provider aliases for normalization.
IMAGE_PROVIDER_ALIASES: dict[str, str] = {
    "gemini_api": "gemini_api",
    "gemini": "gemini_api",
    "google": "gemini_api",
    "google_ai_studio": "gemini_api",
    "openrouter": "openrouter",
    "open_router": "openrouter",
}

# Default image provider when none is configured.
DEFAULT_IMAGE_PROVIDER = "gemini_api"


def normalize_image_provider(provider: Any) -> str:
    """Normalize image provider ID strings."""
    value = str(provider or "").strip().lower()
    return IMAGE_PROVIDER_ALIASES.get(value, value or DEFAULT_IMAGE_PROVIDER)


def create_image_provider(
    provider_id: str,
    output_dir: str,
    *,
    model: str | None = None,
    memory: Any = None,
) -> BaseImageProvider:
    """Factory: create the appropriate image provider instance.

    Parameters
    ----------
    provider_id:
        Normalized provider ID (``"gemini_api"`` or ``"openrouter"``).
    output_dir:
        Directory where generated images are saved.
    model:
        Optional model override. When ``None``, the provider default is used.
    memory:
        Optional MemoryStore for reading extra settings (e.g. reasoning level).
    """
    normalized = normalize_image_provider(provider_id)

    if normalized == "openrouter":
        from hana_agent_oss.modules.vision.openrouter_image import OpenRouterImageProvider
        return OpenRouterImageProvider(output_dir=output_dir, model=model, memory=memory)

    # Default: Gemini API (existing HanaImageGen).
    from hana_agent_oss.modules.vision.image_gen import HanaImageGen
    return HanaImageGen(output_dir=output_dir)
