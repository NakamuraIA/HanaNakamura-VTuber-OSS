"""
On-demand screen vision.

Captures the configured monitor only when requested and encodes it with a
persisted quality profile before sending it to the LLM as an image attachment.
"""

from __future__ import annotations

import base64
import logging
import os
from io import BytesIO
from typing import Any

try:
    import mss
except ImportError:
    mss = None

try:
    from PIL import Image
except ImportError:
    Image = None

logger = logging.getLogger(__name__)


DEFAULT_VISION_QUALITY_PROFILE = "full_hd_png"

VISION_QUALITY_PROFILES: dict[str, dict[str, Any]] = {
    "full_hd_png": {
        "max_width": 1920,
        "format": "PNG",
        "mime_type": "image/png",
        "extension": ".png",
        "mode": "rgb",
    },
    "readable_jpeg": {
        "max_width": 1600,
        "format": "JPEG",
        "mime_type": "image/jpeg",
        "extension": ".jpg",
        "mode": "rgb",
        "quality": 84,
    },
    "fast_jpeg": {
        "max_width": 1280,
        "format": "JPEG",
        "mime_type": "image/jpeg",
        "extension": ".jpg",
        "mode": "rgb",
        "quality": 72,
    },
    "low_color_png": {
        "max_width": 1280,
        "format": "PNG",
        "mime_type": "image/png",
        "extension": ".png",
        "mode": "palette",
        "colors": 64,
    },
    "grayscale_readable": {
        "max_width": 1440,
        "format": "PNG",
        "mime_type": "image/png",
        "extension": ".png",
        "mode": "grayscale",
    },
    "grayscale_fast": {
        "max_width": 960,
        "format": "JPEG",
        "mime_type": "image/jpeg",
        "extension": ".jpg",
        "mode": "grayscale",
        "quality": 68,
    },
}


def normalize_vision_quality_profile(value: Any) -> str:
    """Return a supported vision quality profile, preserving the safe default."""
    profile = str(value or "").strip().lower()
    if profile in VISION_QUALITY_PROFILES:
        return profile
    return DEFAULT_VISION_QUALITY_PROFILE


class VisaoNyra:
    """On-demand vision system that captures the screen only when requested."""

    def __init__(self, memory=None):
        self.memory = memory
        self._ultimo_caminho_img = None

    @property
    def monitor_index(self) -> int:
        """Dynamically read the active monitor index from database."""
        if self.memory:
            config = self.memory.get_setting("portabilidade_config", {})
            try:
                return int(config.get("activeMonitor", 1))
            except (TypeError, ValueError):
                return 1
        return 1

    @property
    def quality_profile(self) -> str:
        """Dynamically read the persisted screenshot quality profile."""
        if self.memory:
            config = self.memory.get_setting("portabilidade_config", {})
            return normalize_vision_quality_profile(config.get("visionQualityProfile"))
        return DEFAULT_VISION_QUALITY_PROFILE

    def capturar(self) -> dict[str, Any]:
        """
        Capture the screen now and return base64, path, and image metadata.

        Returns:
            dict: capture result containing base64 image data, absolute path,
            MIME type, extension, selected profile, final dimensions, and error
            text when capture fails.
        """
        if not mss:
            return {"sucesso": False, "erro": "Modulo 'mss' nao instalado. pip install mss"}

        if not Image:
            return {"sucesso": False, "erro": "Modulo 'Pillow' nao instalado. pip install Pillow"}

        try:
            img_bytes, metadata = self._capturar_screenshot()
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            path_temp = os.path.join("temp", f"ultima_visao{metadata['extension']}")
            os.makedirs("temp", exist_ok=True)
            with open(path_temp, "wb") as f:
                f.write(img_bytes)

            self._ultimo_caminho_img = os.path.abspath(path_temp)

            return {
                "sucesso": True,
                "b64": img_b64,
                "caminho": self._ultimo_caminho_img,
                **metadata,
            }

        except Exception as e:
            logger.error(f"[VISAO] Erro na captura: {e}")
            return {"sucesso": False, "erro": str(e)}

    def _capturar_screenshot(self) -> tuple[bytes, dict[str, Any]]:
        """Capture the configured monitor and encode it with the selected profile."""
        with mss.mss() as sct:
            monitor = sct.monitors[self.monitor_index]
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            return self._encode_image(img, self.quality_profile)

    def _encode_image(self, img, profile_id: str) -> tuple[bytes, dict[str, Any]]:
        """Resize, color-convert, and encode a screenshot for LLM vision input."""
        profile_id = normalize_vision_quality_profile(profile_id)
        profile = VISION_QUALITY_PROFILES[profile_id]
        img = self._resize_image(img, int(profile["max_width"]))

        mode = profile["mode"]
        if mode == "grayscale":
            img = img.convert("L")
        elif mode == "palette":
            img = img.convert("P", palette=Image.ADAPTIVE, colors=int(profile.get("colors", 64)))
        else:
            img = img.convert("RGB")

        buffer = BytesIO()
        save_kwargs: dict[str, Any] = {"format": profile["format"], "optimize": True}
        if profile["format"] == "JPEG":
            save_kwargs["quality"] = int(profile.get("quality", 80))
            if img.mode not in {"RGB", "L"}:
                img = img.convert("RGB")
        img.save(buffer, **save_kwargs)

        return buffer.getvalue(), {
            "mime_type": profile["mime_type"],
            "extension": profile["extension"],
            "profile": profile_id,
            "width": img.width,
            "height": img.height,
        }

    def _resize_image(self, img, max_width: int):
        """Resize large screenshots while preserving aspect ratio."""
        if img.width <= max_width:
            return img
        ratio = max_width / img.width
        new_size = (max_width, int(img.height * ratio))
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        return img.resize(new_size, resampling)
