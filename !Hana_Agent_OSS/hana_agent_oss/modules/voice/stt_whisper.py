from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from hana_agent_oss.persona import build_stt_prompt

logger = logging.getLogger(__name__)

DEFAULT_STT_MODEL = "whisper-large-v3"
DEFAULT_STT_LANGUAGE = "pt"
DEFAULT_STT_PROMPT = build_stt_prompt()
STT_PROMPT_MAX_WORDS = 160
MIN_AUDIO_BYTES = 512
FFMPEG_CANDIDATES = (
    "FFMPEG_PATH",
    "HANA_FFMPEG_PATH",
)
CONVERTIBLE_AUDIO_SUFFIXES = {".webm", ".ogg", ".oga", ".mp4", ".m4a", ".aac"}

DEFAULT_CORRECTIONS: dict[str, str] = {
    "hannah": "Hana",
}

VALID_SHORT_UTTERANCES = {
    "oi",
    "oi.",
    "ok",
    "ok.",
    "ai",
    "ai.",
    "la",
    "la.",
}

LANGUAGE_ALIASES = {
    "pt-br": "pt",
    "pt_br": "pt",
    "pt-BR": "pt",
    "portuguese": "pt",
    "portugues": "pt",
    "português": "pt",
    "en-us": "en",
    "en_us": "en",
    "ja-jp": "ja",
    "ja_jp": "ja",
}

GHOST_STT_PHRASES = {
    "",
    "obrigado",
    "obrigado.",
    "obrigada",
    "obrigada.",
    "tchau",
    "tchau.",
    "tchau tchau",
    "tchau, tchau.",
    "legendas pela comunidade amara.org",
    "mistura de idiomas",
    "mistura de idiomas.",
    "o usuario fala portugues e japones",
    "o usuario fala portugues e japones.",
    "portugues e japones",
    "portugues e japones.",
    "inscreva-se no canal",
    "deixe seu like",
    "legenda adriana zanotto",
    "e ai",
    "e ai.",
    "legenda por sonia ruberti",
    "legendas por sonia ruberti",
    "sonia ruberti",
    "subtitulos por tiago anderson",
    "subtitulo por tiago anderson",
    "legendas por tiago anderson",
    "legenda por tiago anderson",
    "ate a proxima",
    "ate a proxima!",
    "ate a proxima.",
}

GHOST_STT_PATTERNS = (
    re.compile(r"^(?:subtitulos?|legendas?|legenda|caption|captions|subtitle|subtitles)\s+(?:por|by)\s+[\w .'-]{2,60}\.?$", re.IGNORECASE),
    re.compile(r"^(?:transcricao|transcription)\s+(?:por|by)\s+[\w .'-]{2,60}\.?$", re.IGNORECASE),
    re.compile(r"^(?:traduzido|traducao|translation)\s+(?:por|by)\s+[\w .'-]{2,60}\.?$", re.IGNORECASE),
    re.compile(r"^(?:inscreva-se|deixe seu like|ative o sininho)(?:.+)?\.?$", re.IGNORECASE),
    re.compile(r"^.+(?:ative o sininho|notificacoes de novos videos).*$", re.IGNORECASE),
)


class STTConfigurationError(RuntimeError):
    """Raised when the STT provider is not configured for runtime use."""


@dataclass(frozen=True)
class STTTranscriptionResult:
    provider: str
    model: str
    language: str
    text: str
    raw_text: str
    filtered: bool


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def normalize_stt_prompt(prompt: str | None) -> str:
    prompt = str(prompt or "").strip()
    if not prompt:
        return ""

    words = prompt.split()
    if len(words) <= STT_PROMPT_MAX_WORDS:
        return prompt
    return " ".join(words[:STT_PROMPT_MAX_WORDS])


def normalize_stt_language(language: str | None) -> str:
    value = str(language or DEFAULT_STT_LANGUAGE).strip()
    return LANGUAGE_ALIASES.get(value, LANGUAGE_ALIASES.get(value.lower(), value or DEFAULT_STT_LANGUAGE))


def normalize_ghost_text(text: str) -> str:
    normalized = str(text or "").lower().strip()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def is_ghost_stt_phrase(text: str) -> bool:
    normalized = normalize_ghost_text(text)
    if normalized in GHOST_STT_PHRASES:
        return True
    return any(pattern.match(normalized) for pattern in GHOST_STT_PATTERNS)


def load_stt_corrections(extra_json: str | None = None) -> dict[str, str]:
    corrections = dict(DEFAULT_CORRECTIONS)
    raw = extra_json if extra_json is not None else os.environ.get("STT_CORRECTIONS_JSON", "")
    if not raw:
        return corrections

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("[STT] Ignoring invalid STT_CORRECTIONS_JSON: %s", exc)
        return corrections

    if isinstance(parsed, dict):
        for wrong, right in parsed.items():
            wrong_text = str(wrong).strip()
            right_text = str(right).strip()
            if wrong_text and right_text:
                corrections[wrong_text] = right_text
    return corrections


def apply_stt_corrections(text: str, corrections: dict[str, str] | None = None) -> str:
    corrected = str(text or "")
    for wrong, right in (corrections or DEFAULT_CORRECTIONS).items():
        pattern = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE | re.UNICODE)
        corrected = pattern.sub(right, corrected)
    return corrected


def _extract_transcription_text(transcription: Any) -> str:
    if isinstance(transcription, str):
        return transcription.strip()
    text = getattr(transcription, "text", None)
    if text is not None:
        return str(text).strip()
    if isinstance(transcription, dict):
        return str(transcription.get("text") or "").strip()
    return str(transcription or "").strip()


def _ffmpeg_path() -> str:
    # 1. Try to read from SQLite portabilidade_config
    from hana_agent_oss.paths import RUNTIME_DB as db_path
    if db_path.exists():
        try:
            import sqlite3
            import json
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("SELECT val FROM settings WHERE key = ?", ("portabilidade_config",))
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                config = json.loads(row[0])
                custom_path = config.get("ffmpegPath")
                if custom_path and Path(custom_path).exists():
                    return str(Path(custom_path))
        except Exception:
            logger.debug("Falha ao ler ffmpegPath das settings; tentando env/PATH", exc_info=True)

    # 2. Try environment variables
    for env_name in FFMPEG_CANDIDATES:
        value = os.environ.get(env_name)
        if value and Path(value).exists():
            return str(Path(value))
    # 3. Try standard local default
    default = Path("C:/Ffmpeg/ffmpeg.exe")
    return str(default) if default.exists() else "ffmpeg"


def _convert_audio_to_wav(audio: bytes, filename: str) -> tuple[bytes, str]:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in CONVERTIBLE_AUDIO_SUFFIXES:
        return audio, filename

    with tempfile.TemporaryDirectory(prefix="hana-stt-") as temp_dir:
        input_path = Path(temp_dir) / f"input{suffix or '.webm'}"
        output_path = Path(temp_dir) / "audio.wav"
        input_path.write_bytes(audio)
        command = [
            _ffmpeg_path(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            converted = output_path.read_bytes()
            if converted:
                return converted, "audio.wav"
        except Exception as exc:
            logger.warning("[STT] FFmpeg conversion failed for %s: %s", filename, exc)
    return audio, filename


class GroqWhisperSTTProvider:
    provider_id = "groq_whisper"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        language: str | None = None,
        prompt: str | None = None,
        corrections: dict[str, str] | None = None,
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key or _env_first("GROQ_API_KEY")
        self.model = model or _env_first("GROQ_STT_MODEL", "STT_MODEL", default=DEFAULT_STT_MODEL)
        self.language = normalize_stt_language(language or _env_first("GROQ_STT_LANGUAGE", "STT_LANGUAGE", default=DEFAULT_STT_LANGUAGE))
        self.prompt = normalize_stt_prompt(
            prompt if prompt is not None else _env_first("GROQ_STT_PROMPT", "STT_PROMPT", default=DEFAULT_STT_PROMPT)
        )
        self.corrections = corrections or load_stt_corrections()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise STTConfigurationError("GROQ_API_KEY is required for Groq Whisper STT.")

        try:
            from groq import Groq
        except ImportError as exc:
            raise STTConfigurationError("The groq package is required for Groq Whisper STT.") from exc

        self._client = Groq(api_key=self.api_key)
        return self._client

    def transcribe_bytes(
        self,
        audio: bytes,
        *,
        filename: str = "audio.wav",
        model: str | None = None,
        language: str | None = None,
        prompt: str | None = None,
    ) -> STTTranscriptionResult:
        selected_model = model or self.model
        selected_language = normalize_stt_language(language or self.language)
        if not audio or len(audio) < MIN_AUDIO_BYTES:
            return STTTranscriptionResult(
                provider=self.provider_id,
                model=selected_model,
                language=selected_language,
                text="",
                raw_text="",
                filtered=True,
            )
        audio, filename = _convert_audio_to_wav(audio, filename)
        return self._transcribe_file_object(
            io.BytesIO(audio),
            filename=filename,
            model=model,
            language=language,
            prompt=prompt,
        )

    def transcribe_path(
        self,
        path: str | Path,
        *,
        model: str | None = None,
        language: str | None = None,
        prompt: str | None = None,
    ) -> STTTranscriptionResult:
        audio_path = Path(path)
        with audio_path.open("rb") as audio_file:
            return self._transcribe_file_object(
                audio_file,
                filename=audio_path.name,
                model=model,
                language=language,
                prompt=prompt,
            )

    def _transcribe_file_object(
        self,
        audio_file: BinaryIO,
        *,
        filename: str,
        model: str | None,
        language: str | None,
        prompt: str | None,
    ) -> STTTranscriptionResult:
        selected_model = model or self.model
        selected_language = normalize_stt_language(language or self.language)
        selected_prompt = normalize_stt_prompt(prompt if prompt is not None else self.prompt)

        transcription = self.client.audio.transcriptions.create(
            file=(filename or "audio.wav", audio_file),
            model=selected_model,
            language=selected_language,
            response_format="text",
            prompt=selected_prompt,
            temperature=0.0,
        )
        raw_text = _extract_transcription_text(transcription)
        filtered = self._should_filter(raw_text)
        text = "" if filtered else apply_stt_corrections(raw_text, self.corrections)
        if filtered and raw_text:
            logger.info("[STT] Filtered ghost transcription: %s", raw_text)

        return STTTranscriptionResult(
            provider=self.provider_id,
            model=selected_model,
            language=selected_language,
            text=text,
            raw_text=raw_text,
            filtered=filtered,
        )

    @staticmethod
    def _should_filter(text: str) -> bool:
        normalized = normalize_ghost_text(text)
        if is_ghost_stt_phrase(text):
            return True
        return len(normalized) < 3 and normalized not in VALID_SHORT_UTTERANCES


MotorSTTWhisper = GroqWhisperSTTProvider
