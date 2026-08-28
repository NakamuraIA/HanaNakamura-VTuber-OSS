"""OpenRouter transcription provider for the Hana OSS voice runtime.

Endpoint dedicado de transcricao (POST /api/v1/audio/transcriptions), nao chat
multimodal — audio vai em base64 dentro de input_audio.data/format. Varios
modelos reais (Whisper, GPT-4o Transcribe, Chirp 3...) sob a MESMA
OPENROUTER_API_KEY ja usada pro LLM. A doc deles avisa que o campo "prompt" e
aceito e ignorado, entao — diferente do Groq — este provider nao manda bias.
Lista de modelos: get_openrouter_stt_catalog() (endpoint ao vivo, sem tabela).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from backend.providers.stt.registry import STTConfigurationError, STTTranscriptionResult
from backend.providers.stt.whisper import (
    VALID_SHORT_UTTERANCES,
    apply_stt_corrections,
    is_ghost_stt_phrase,
    load_stt_corrections,
    normalize_ghost_text,
    normalize_stt_language,
)
from backend.providers.provider_selector.openrouter.catalog import openrouter_headers

logger = logging.getLogger(__name__)

OPENROUTER_TRANSCRIPTIONS_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
DEFAULT_OPENROUTER_STT_MODEL = "openai/whisper-1"
OPENROUTER_TIMEOUT_SECONDS = 30.0
MIN_AUDIO_BYTES = 512

_AUDIO_FORMAT_BY_SUFFIX = {
    ".wav": "wav", ".mp3": "mp3", ".flac": "flac", ".m4a": "m4a",
    ".ogg": "ogg", ".oga": "ogg", ".webm": "webm", ".aac": "aac",
}


def _audio_format(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return _AUDIO_FORMAT_BY_SUFFIX.get(suffix, "wav")


class OpenRouterSTTProvider:
    provider_id = "openrouter"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        language: str | None = None,
        corrections: dict[str, str] | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.model = model or DEFAULT_OPENROUTER_STT_MODEL
        self.language = normalize_stt_language(language) if language else ""
        self.corrections = corrections or load_stt_corrections()

    def transcribe_bytes(
        self,
        audio: bytes,
        *,
        filename: str = "audio.wav",
        model: str | None = None,
        language: str | None = None,
        prompt: str | None = None,  # aceito pela assinatura comum, ignorado de proposito (ver docstring)
    ) -> STTTranscriptionResult:
        selected_model = model or self.model
        selected_language = normalize_stt_language(language or self.language)
        if not audio or len(audio) < MIN_AUDIO_BYTES:
            return STTTranscriptionResult(
                provider=self.provider_id, model=selected_model, language=selected_language,
                text="", raw_text="", filtered=True,
            )
        if not self.api_key:
            raise STTConfigurationError("OPENROUTER_API_KEY is required for OpenRouter STT.")

        payload: dict[str, Any] = {
            "model": selected_model,
            "input_audio": {
                "data": base64.b64encode(audio).decode("ascii"),
                "format": _audio_format(filename),
            },
        }
        if selected_language:
            payload["language"] = selected_language

        request = urllib.request.Request(
            OPENROUTER_TRANSCRIPTIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=openrouter_headers(include_auth=True),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=OPENROUTER_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise STTConfigurationError(f"OpenRouter STT failed: {detail[:400]}") from exc
        except Exception as exc:
            raise STTConfigurationError(f"OpenRouter STT failed: {exc}") from exc

        raw_text = str(body.get("text") or "").strip()
        filtered = self._should_filter(raw_text)
        text = "" if filtered else apply_stt_corrections(raw_text, self.corrections)
        return STTTranscriptionResult(
            provider=self.provider_id, model=selected_model, language=selected_language,
            text=text, raw_text=raw_text, filtered=filtered,
        )

    @staticmethod
    def _should_filter(text: str) -> bool:
        """Mesmo filtro de alucinacao do Groq (reaproveitado) — sem is_prompt_echo,
        que so faz sentido quando um prompt de bias de verdade foi enviado."""
        normalized = normalize_ghost_text(text)
        if is_ghost_stt_phrase(text):
            return True
        return len(normalized) < 3 and normalized not in VALID_SHORT_UTTERANCES
