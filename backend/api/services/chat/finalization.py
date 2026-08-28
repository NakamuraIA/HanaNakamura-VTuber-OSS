"""Limpeza final da resposta antes de exibir, falar e salvar."""

from __future__ import annotations

import re

from backend.memory.memory_xml import strip_memory_xml_tags
from backend.modules.vision.image_xml import strip_image_xml_tags
from backend.tools.skill_tools import strip_skill_xml_tags
from backend.api.services.unified_history import strip_leaked_terminal_events

_LEAKED_TOOL_CALL_RE = re.compile(r"<\|\s*\w+.*?\|>", re.DOTALL)


def strip_leaked_tool_calls(text: str) -> str:
    cleaned = _LEAKED_TOOL_CALL_RE.sub("", str(text or ""))
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def clean_model_text(text: str, *, plain_voice: bool = False) -> str:
    """Remove protocolos internos e, quando necessário, converte para fala limpa."""
    cleaned = strip_image_xml_tags(text)
    cleaned = strip_memory_xml_tags(cleaned)
    cleaned = strip_skill_xml_tags(cleaned)
    cleaned = strip_leaked_tool_calls(cleaned)
    cleaned = strip_leaked_terminal_events(cleaned)
    cleaned = re.sub(r"(?is)<think>.*?</think>", " ", cleaned).strip()
    cleaned = re.sub(r"(?is)^\s*<think>.*$", " ", cleaned).strip()
    if plain_voice:
        from backend.modules.voice.tts_readable import plainify_for_voice

        cleaned = plainify_for_voice(cleaned)
    return cleaned
