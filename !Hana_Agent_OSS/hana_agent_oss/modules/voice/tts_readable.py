from __future__ import annotations

import re

from hana_agent_oss.memory.memory_xml import strip_memory_xml_tags


CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
MARKDOWN_CONTROL_RE = re.compile(r"(^|\s)[>#*_~|`]+")
BULLET_DASH_RE = re.compile(r"(^|\s)[\-–—•]+(\s|$)")
REPEATED_PUNCTUATION_RE = re.compile(r"([!?.,;:]){2,}")
SYMBOL_RE = re.compile(r"[{}\[\]()<>=\\/|@#$%^&*_+~★☆]")
SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([!?.,;:])")
WHITESPACE_RE = re.compile(r"\s+")
EMOJI_RE = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\u2600-\u27bf"
    "\u2b00-\u2bff"
    "\u2190-\u21ff"
    "\ufe00-\ufe0f"  # variation selectors (emoji vs text presentation)
    "\u200d"          # zero-width joiner (compound emoji like \ud83d\udc68\u200d\ud83d\udc69\u200d\ud83d\udc67)
    "\U0001f000-\U0001f0ff"  # mahjong/dominoes/cards
    "]+",
    re.UNICODE,
)

# Strip TTS generation meta logs that sometimes leak into response text (e.g. "TTS google_cloud_tts gerou audio: ...")
# These should never be spoken.
TTS_META_RE = re.compile(
    r"(?i)\bTTS\s+.*?(gerou\s+audio|falando|gerou|audio|provider|voice|streaming|fallback|finalizada|runtime)\b.*?(?=\s|$|\.|,)",
    re.IGNORECASE,
)


def sanitize_tts_text(text: str) -> str:
    """Convert display/chat text into speech-safe text for future TTS providers.

    Also removes <salvar_memoria> tags so internal long-term memories are never spoken.
    """
    value = str(text or "")
    value = strip_memory_xml_tags(value)
    value = TTS_META_RE.sub(" ", value)
    value = EMOJI_RE.sub(" ", value)
    value = CODE_BLOCK_RE.sub(" ", value)
    value = MARKDOWN_IMAGE_RE.sub(lambda match: f" {match.group(1)} ", value)
    value = MARKDOWN_LINK_RE.sub(lambda match: f" {match.group(1)} ", value)
    value = URL_RE.sub(" link ", value)
    value = INLINE_CODE_RE.sub(lambda match: f" {match.group(1)} ", value)
    value = MARKDOWN_CONTROL_RE.sub(" ", value)
    value = BULLET_DASH_RE.sub(" ", value)
    value = REPEATED_PUNCTUATION_RE.sub(lambda match: match.group(0)[0], value)
    value = SYMBOL_RE.sub(" ", value)
    value = SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", value)
    value = value.replace(":", ".").replace(";", ".")
    value = value.replace("\r", " ").replace("\n", " ")
    return WHITESPACE_RE.sub(" ", value).strip()


def tts_payload(display_text: str, explicit_tts_text: str | None = None) -> dict[str, str]:
    source = explicit_tts_text if explicit_tts_text is not None else display_text
    return {
        "display_text": strip_memory_xml_tags(str(display_text or "")),
        "tts_text": sanitize_tts_text(source),
    }
