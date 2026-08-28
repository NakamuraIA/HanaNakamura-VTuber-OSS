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




class AttachmentSupport:
    def _attachment_parts(self, attachments: list[dict[str, Any]], *, model_info: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Convert local attachments into content parts and plugins.

        Base implementation handles images, PDFs and text. Providers that
        need different behaviour (e.g. Groq which rejects PDFs) override this.
        """
        parts: list[dict[str, Any]] = []
        plugins: list[dict[str, Any]] = []
        known_no_vision = bool(model_info) and not bool(model_info.get("supportsVision"))

        for item in attachments:
            if not isinstance(item, dict):
                continue
            mime_type = str(item.get("type") or "application/octet-stream").strip().lower()
            filename = str(item.get("name") or "attachment").strip() or "attachment"
            raw = self._decode_attachment(item)
            if not raw:
                raise ValueError("empty_attachment")

            if mime_type.startswith("image/"):
                if known_no_vision:
                    # Skip image attachments for models without vision support.
                    # This prevents errors when visao is enabled but model (e.g. DeepSeek text) can't handle images.
                    # The text message will proceed without the screen image.
                    continue
                parts.append({"type": "image_url", "image_url": {"url": self._data_url(mime_type, raw)}})
                continue

            if mime_type == "application/pdf":
                parts.append(
                    {
                        "type": "file",
                        "file": {
                            "filename": filename,
                            "file_data": self._data_url(mime_type, raw),
                        },
                    }
                )
                plugins.append({"id": "file-parser", "pdf": {"engine": "cloudflare-ai"}})
                continue

            if mime_type in SUPPORTED_TEXT_ATTACHMENT_TYPES or mime_type.startswith("text/"):
                text = raw.decode("utf-8", errors="replace")
                parts.append({"type": "text", "text": f"\n\n[Attachment: {filename}]\n{text[:200000]}"})
                continue

            # Unsupported attachment type (e.g. an auto-recovered audio/mpeg on a
            # text-only model): skip it gracefully instead of breaking the whole
            # turn. The text message still goes through.
            continue

        return parts, plugins


    @staticmethod
    def _decode_attachment(item: dict[str, Any]) -> bytes:
        """Read an attachment from disk or decode frontend base64/data URL payloads."""
        if item.get("path"):
            return Path(str(item.get("path"))).read_bytes()
        value = str(item.get("data") or "")
        if "," in value and value.lower().startswith("data:"):
            value = value.split(",", 1)[1]
        try:
            return base64.b64decode(value, validate=False)
        except binascii.Error as exc:
            raise ValueError("invalid_base64_attachment") from exc


    @staticmethod
    def _data_url(mime_type: str, raw: bytes) -> str:
        """Build a data URL accepted by multimodal content parts."""
        return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"


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

