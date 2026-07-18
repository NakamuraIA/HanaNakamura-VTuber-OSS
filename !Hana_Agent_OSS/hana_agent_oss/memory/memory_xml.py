"""XML helpers for Hana to save long-term memories using <salvar_memoria> tags.

This allows the model to decide what is worth remembering permanently
without polluting short-term conversation history or TTS output.
"""

from __future__ import annotations

import json
import re
from typing import Any

MEMORY_TAG_NAME_RE = r"salvar[_\s-]*mem[oó]ria"
MEMORY_XML_BLOCK_RE = re.compile(
    rf"<\s*{MEMORY_TAG_NAME_RE}\b[^>]*>.*?<\s*/\s*{MEMORY_TAG_NAME_RE}\s*>",
    re.IGNORECASE | re.DOTALL,
)
MEMORY_XML_EXTRACT_RE = re.compile(
    rf"<\s*{MEMORY_TAG_NAME_RE}\b(?P<attrs>[^>]*)>(?P<body>.*?)<\s*/\s*{MEMORY_TAG_NAME_RE}\s*>",
    re.IGNORECASE | re.DOTALL,
)
VERBALIZED_MEMORY_BLOCK_RE = re.compile(
    rf"\b{MEMORY_TAG_NAME_RE}\b\s*(?:[:=]?\s*)?(?:\{{.*?\}}|[\"']?text[\"']?\s*[:=].*?)(?:\b{MEMORY_TAG_NAME_RE}\b|$)",
    re.IGNORECASE | re.DOTALL,
)


def extract_memory_saves(text: str) -> list[dict[str, Any]]:
    """Extract <salvar_memoria> blocks from the assistant's raw response.

    Supports two formats:
    1. Plain text: <salvar_memoria>Some important fact here</salvar_memoria>
    2. JSON: <salvar_memoria>{"text": "...", "importance": "high", "category": "preference"}</salvar_memoria>

    Returns a list of dicts ready to be saved via MemoryStore.add_memory().
    """
    value = str(text or "")
    results: list[dict[str, Any]] = []

    for match in MEMORY_XML_EXTRACT_RE.finditer(value):
        raw = match.group("body").strip()
        attrs = match.group("attrs") or ""
        if not raw:
            continue

        entry: dict[str, Any] = {
            "text": raw,
            "importance": "medium",
            "category": "observation",
            "source": "model_self_save",
        }

        # Read lightweight attributes such as category="game_state".
        for key in ("importance", "category"):
            attr_match = re.search(rf"\b{key}\s*=\s*(['\"])(.*?)\1", attrs, flags=re.IGNORECASE)
            if attr_match:
                entry[key] = attr_match.group(2).strip()

        # Try to parse as JSON for richer metadata.
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                entry["text"] = str(parsed.get("text") or parsed.get("content") or raw).strip()
                if parsed.get("importance"):
                    entry["importance"] = str(parsed["importance"]).lower()
                if parsed.get("category"):
                    entry["category"] = str(parsed["category"])
                if parsed.get("tags"):
                    entry["tags"] = parsed["tags"]
        except (json.JSONDecodeError, TypeError):
            pass

        # Only keep if there's actual content worth saving.
        if entry["text"] and len(entry["text"]) > 8:
            results.append(entry)

    return results


def strip_memory_xml_tags(text: str) -> str:
    """Remove <salvar_memoria> tags so they never reach TTS or user-facing text."""
    cleaned = str(text or "")
    cleaned = MEMORY_XML_BLOCK_RE.sub("", cleaned)
    cleaned = VERBALIZED_MEMORY_BLOCK_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
