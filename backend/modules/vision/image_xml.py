"""XML action helpers for Hana image generation responses."""

from __future__ import annotations

import re


IMAGE_XML_TAGS = (
    "gerar_imagem",
    "editar_imagem",
    "gerar_imagem_personagem",
    "editar_imagem_personagem",
)


def extract_image_xml_actions(text: str) -> dict[str, list[str]]:
    """Extract supported image XML actions from a raw assistant response."""
    value = str(text or "")
    actions: dict[str, list[str]] = {}
    for tag in IMAGE_XML_TAGS:
        pattern = rf"<{tag}>(.*?)</{tag}>"
        actions[tag] = [
            item.strip()
            for item in re.findall(pattern, value, flags=re.IGNORECASE | re.DOTALL)
            if item and item.strip()
        ]
    return actions


def strip_image_xml_tags(text: str) -> str:
    """Remove image XML actions from text shown in chat or spoken by TTS."""
    cleaned = str(text or "")
    for tag in IMAGE_XML_TAGS:
        cleaned = re.sub(rf"<{tag}>.*?</{tag}>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
