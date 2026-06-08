"""
Minimax TTS (T2A v2) provider for the new Hana OSS voice runtime.

High-quality multilingual TTS with strong support for Portuguese (pt-BR).
Turbo models emphasize low latency, HD for higher quality.
300+ voices including many native-sounding Portuguese female options
(Portuguese_ConfidentWoman, Portuguese_SentimentalLady, etc.).

Uses pure httpx (no extra deps) + Bearer auth with the provided sk-api- key.
Non-streaming for simplicity (returns full MP3 bytes like other providers).
Streaming (SSE) can be added later for even lower perceived latency.

Config via env:
- MINIMAX_API_KEY (the sk-api-... key)

Recommended for pt-BR:
- model: "speech-2.8-turbo" (low latency) or "speech-2.8-hd"
- language_boost: "Portuguese"
- voice_id from https://www.minimax.io/audio/voices or platform console (filter Portuguese female)

Separate from LLM/STT providers per project rules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from hana_agent_oss.modules.voice.tts_edge import EdgeTTSResult, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

MINIMAX_TTS_URL = "https://api.minimax.io/v1/t2a_v2"
# For potentially lower TTFA (Time To First Audio), some users prefer:
# MINIMAX_TTS_URL = "https://api-uw.minimax.io/v1/t2a_v2"

DEFAULT_MINIMAX_MODEL = "speech-2.8-turbo"
DEFAULT_MINIMAX_VOICE = "Portuguese_ConfidentWoman"
DEFAULT_MINIMAX_LANGUAGE_BOOST = "Portuguese"
MINIMAX_TTS_MIME = "audio/mpeg"
MINIMAX_TIMEOUT_SECONDS = 60.0  # longer for safety on long text


@dataclass(frozen=True)
class MinimaxTTSProvider:
    """Minimax Text-to-Audio v2 provider (good quality, low-latency turbo models, many pt voices)."""

    voice: str = DEFAULT_MINIMAX_VOICE
    model: str = DEFAULT_MINIMAX_MODEL
    speed: float = 1.0
    volume: float = 1.0
    pitch: int = 0
    language_boost: str = DEFAULT_MINIMAX_LANGUAGE_BOOST

    async def synthesize(self, text: str) -> EdgeTTSResult:
        """Generate audio bytes via Minimax T2A v2 (non-streaming, hex audio response)."""
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        api_key = os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            raise TTSConfigurationError(
                "MINIMAX_API_KEY is required for Minimax TTS. "
                "Get it from platform.minimax.io (user center > API Keys)."
            )

        payload = self._build_payload(clean_text)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=MINIMAX_TIMEOUT_SECONDS) as client:
            response = await client.post(MINIMAX_TTS_URL, headers=headers, json=payload)

        if response.status_code >= 400:
            detail = _response_error(response)
            raise TTSConfigurationError(f"Minimax TTS failed: {detail}")

        try:
            data = response.json()
        except Exception as exc:
            raise TTSConfigurationError("Minimax TTS returned invalid JSON.") from exc

        base = data.get("base_resp", {})
        if base.get("status_code") != 0:
            raise TTSConfigurationError(
                f"Minimax TTS error: {base.get('status_msg', 'unknown error')}"
            )

        audio_hex = (data.get("data") or {}).get("audio") or ""
        if not audio_hex:
            raise TTSConfigurationError("Minimax TTS returned no audio data.")

        try:
            audio = bytes.fromhex(audio_hex)
        except Exception as exc:
            raise TTSConfigurationError("Minimax TTS audio data was not valid hex.") from exc

        if not audio:
            raise TTSConfigurationError("Minimax TTS produced empty audio.")

        return self._result(clean_text, audio)

    def _build_payload(self, clean_text: str) -> dict[str, Any]:
        """Build the T2A v2 request body."""
        voice_setting: dict[str, Any] = {
            "voice_id": str(self.voice or DEFAULT_MINIMAX_VOICE).strip(),
            "speed": max(0.5, min(2.0, float(self.speed or 1.0))),
            "vol": max(0.1, min(10.0, float(self.volume or 1.0))),
            "pitch": max(-12, min(12, int(self.pitch or 0))),
        }

        audio_setting: dict[str, Any] = {
            "format": "mp3",
            "sample_rate": 32000,
            "bitrate": 128000,
            "channel": 1,
        }

        payload: dict[str, Any] = {
            "model": self.model or DEFAULT_MINIMAX_MODEL,
            "text": clean_text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": voice_setting,
            "audio_setting": audio_setting,
            "language_boost": self.language_boost or DEFAULT_MINIMAX_LANGUAGE_BOOST,
        }

        return payload

    def _result(self, text: str, audio: bytes) -> EdgeTTSResult:
        """Return provider-neutral result for the runtime/player."""
        return EdgeTTSResult(
            provider="minimax",
            voice=str(self.voice or DEFAULT_MINIMAX_VOICE),
            rate=str(self.speed),
            pitch=str(self.pitch),
            volume=str(self.volume),
            text=text,
            audio=audio,
            mime_type=MINIMAX_TTS_MIME,
        )


def _response_error(response: httpx.Response) -> str:
    """Extract useful error message."""
    try:
        data = response.json()
    except Exception:
        return response.text[:400] or f"HTTP {response.status_code}"
    base = data.get("base_resp", {}) if isinstance(data, dict) else {}
    if base.get("status_msg"):
        return str(base["status_msg"])[:400]
    if isinstance(data, dict):
        return str(data.get("error") or data.get("message") or data)[:400]
    return str(data)[:400]
