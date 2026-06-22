"""ElevenLabs TTS provider for the Hana OSS voice runtime.

The provider uses the REST API directly through httpx, keeping ElevenLabs
isolated from LLM and STT providers. Voice IDs may come from the user's own
library, cloned voices, generated voices, or the public voice library.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from hana_agent_oss.modules.voice.tts_edge import EdgeTTSResult, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_TTS_STREAM_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
DEFAULT_ELEVENLABS_VOICE = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_ELEVENLABS_MODEL = "eleven_flash_v2_5"
DEFAULT_ELEVENLABS_LANGUAGE = "pt"
ELEVENLABS_TTS_MODELS = (
    "eleven_flash_v2_5",
    "eleven_turbo_v2_5",
    "eleven_multilingual_v2",
    "eleven_v3",
)
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"
ELEVENLABS_TTS_MIME = "audio/mpeg"
ELEVENLABS_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ElevenlabsTTSProvider:
    """Generate configurable ElevenLabs speech while preserving the TTS contract."""

    voice: str = DEFAULT_ELEVENLABS_VOICE
    model: str = DEFAULT_ELEVENLABS_MODEL
    language: str = DEFAULT_ELEVENLABS_LANGUAGE
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    speaker_boost: bool = True
    speed: float = 1.0

    async def synthesize(self, text: str) -> EdgeTTSResult:
        """Generate audio bytes via Elevenlabs TTS REST API (MP3)."""
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise TTSConfigurationError(
                "ELEVENLABS_API_KEY is required for Elevenlabs TTS. "
                "Get your API key at https://elevenlabs.io/app/settings/api-keys"
            )

        voice_id = str(self.voice or "").strip() or DEFAULT_ELEVENLABS_VOICE
        model_id = str(self.model or "").strip() or DEFAULT_ELEVENLABS_MODEL
        if not voice_id:
            raise TTSConfigurationError("ElevenLabs TTS requires a voice ID.")
        if not model_id:
            raise TTSConfigurationError("ElevenLabs TTS requires a model ID.")

        url = ELEVENLABS_TTS_URL.format(voice_id=quote(voice_id, safe=""))

        payload = self._build_payload(clean_text)
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        }

        async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers=headers,
                params={"output_format": ELEVENLABS_OUTPUT_FORMAT},
                json=payload,
            )

        if response.status_code >= 400:
            detail = _response_error(response)
            raise TTSConfigurationError(f"Elevenlabs TTS failed: {detail}")

        audio = response.content
        if not audio:
            raise TTSConfigurationError("Elevenlabs TTS returned empty audio.")

        return self._result(clean_text, audio)

    async def stream_audio_chunks(self, text: str):
        """Yield ElevenLabs MP3 chunks as soon as the /stream endpoint sends them.

        Lets the runtime start playing the first words while the rest is still
        generated, cutting time-to-first-audio. Same payload as synthesize().
        """
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            return

        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise TTSConfigurationError(
                "ELEVENLABS_API_KEY is required for Elevenlabs TTS. "
                "Get your API key at https://elevenlabs.io/app/settings/api-keys"
            )

        voice_id = str(self.voice or "").strip() or DEFAULT_ELEVENLABS_VOICE
        url = ELEVENLABS_TTS_STREAM_URL.format(voice_id=quote(voice_id, safe=""))
        payload = self._build_payload(clean_text)
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        }

        async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                params={"output_format": ELEVENLABS_OUTPUT_FORMAT},
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    detail = body.decode("utf-8", errors="replace")[:400] if body else f"HTTP {response.status_code}"
                    raise TTSConfigurationError(f"Elevenlabs TTS streaming failed: {detail}")
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk

    def _build_payload(self, clean_text: str) -> dict[str, Any]:
        """Build request body for Elevenlabs TTS API."""
        model_id = str(self.model or DEFAULT_ELEVENLABS_MODEL).strip()
        voice_settings: dict[str, Any] = {
            "stability": max(0.0, min(1.0, float(self.stability))),
            "similarity_boost": max(0.0, min(1.0, float(self.similarity_boost))),
            "style": max(0.0, min(1.0, float(self.style))),
            "use_speaker_boost": bool(self.speaker_boost),
            "speed": max(0.5, min(2.0, float(self.speed))),
        }

        payload: dict[str, Any] = {
            "text": clean_text,
            "model_id": model_id,
            "voice_settings": voice_settings,
        }

        language = _language_code(self.language)
        if language:
            payload["language_code"] = language

        return payload

    def _result(self, text: str, audio: bytes) -> EdgeTTSResult:
        """Return provider-neutral result consumable by existing player/runtime."""
        return EdgeTTSResult(
            provider="elevenlabs",
            voice=str(self.voice or DEFAULT_ELEVENLABS_VOICE),
            rate=str(self.speed),
            pitch="default",
            volume="default",
            text=text,
            audio=audio,
            mime_type=ELEVENLABS_TTS_MIME,
        )


def _response_error(response: httpx.Response) -> str:
    """Compact error without leaking full key material."""
    try:
        data = response.json()
    except Exception:
        return response.text[:400] or f"HTTP {response.status_code}"
    if isinstance(data, dict):
        err = data.get("detail") or data.get("error") or data.get("message") or data
        if isinstance(err, dict):
            return str(err.get("message") or err)[:400]
        return str(err)[:400]
    return str(data)[:400]


def _language_code(language: Any) -> str:
    """Convert UI locales such as pt-BR into the ISO 639-1 API field."""
    value = str(language or "").strip().lower().replace("_", "-")
    if not value or value in {"auto", "automatic"}:
        return ""
    return value.split("-", 1)[0]
