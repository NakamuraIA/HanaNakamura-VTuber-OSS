"""
Cartesia TTS provider for the new Hana OSS voice runtime.

Isolated, high quality, very low latency (often 40-90ms TTFA with their Sonic models),
competitive pricing (cheaper at volume than heavy Google Cloud usage), excellent
Brazilian Portuguese (pt-BR) support with multiple authentic female voices.

User gets voice IDs from https://play.cartesia.ai (filter Language=Portuguese (Brazil), Gender=Female).
Good native pt-BR female examples (authentic Brazilian accent/prosody, no American bleed):
- Luana: 700d1ee3-a641-4018-ba6e-899dcadc9e2b (public speaker, clear)
- Ana Paula: 1cf751f6-8749-43ab-98bd-230dd633abdb (marketer, warm)
- Beatriz: d4b44b9a-82bc-4b65-b456-763fce4c52f9 (support guide)
- Isabella: c9611be8-aae9-4a93-bb1c-98dd6b7d52a4 (warm storyteller)
Paste the UUID into the ttsVoice field in the UI / voice config. Set language="pt".

Uses only httpx (already a dep via google_cloud provider) + REST /tts/bytes for
simplicity and reliability. Streaming (SSE/WS) can be added later for even lower
perceived latency in long utterances.

For best Brazilian Portuguese results (authentic accent, no gringo bleed):
- Use the native pt-BR voices from the catalog (Luana, Ana Paula, Beatriz, Isabella...).
- Set ttsLanguage="pt" (or pt-BR).
- Filter in https://play.cartesia.ai for "Portuguese (Brazil)" female voices.

Separate from LLM/STT providers per project rules. Key: CARTESIA_API_KEY
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from hana_agent_oss.modules.voice.tts_edge import EdgeTTSResult, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

CARTESIA_TTS_BYTES_URL = "https://api.cartesia.ai/tts/bytes"
DEFAULT_CARTESIA_MODEL = "sonic-3.5"  # Recommended alias for latest stable Sonic 3.5. See https://docs.cartesia.ai/build-with-cartesia/tts-models/latest for snapshots like sonic-3.5-2026-05-04
DEFAULT_CARTESIA_LANGUAGE = "pt"
CARTESIA_VERSION = "2026-03-01"  # update when they bump stable
CARTESIA_TTS_MIME = "audio/mpeg"
CARTESIA_TIMEOUT_SECONDS = 30.0

# Cartesia requires the voice to be specified by a valid UUID (from their voice library / playground).
# Use native pt-BR voices (filter Brazil in playground) for authentic accent without American English bleed.
# Language="pt" helps select the right prosody.
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class CartesiaTTSProvider:
    """Cartesia Text-to-Speech provider (separate key, high quality + low latency focus)."""

    voice: str = ""
    model: str = DEFAULT_CARTESIA_MODEL
    language: str = DEFAULT_CARTESIA_LANGUAGE
    speed: float = 1.0
    # volume and other generation_config can be extended

    async def synthesize(self, text: str) -> EdgeTTSResult:
        """Generate audio bytes via Cartesia /tts/bytes (MP3)."""
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        api_key = os.environ.get("CARTESIA_API_KEY")
        if not api_key:
            raise TTSConfigurationError("CARTESIA_API_KEY is required for Cartesia TTS.")

        voice_id = str(self.voice or "").strip()
        if not voice_id or not _UUID_RE.match(voice_id):
            raise TTSConfigurationError(
                "Cartesia TTS failed: voice ID must be a valid UUID from a native pt-BR voice. "
                "Vá em https://play.cartesia.ai , filtre Language=Portuguese (Brazil) + Female. "
                "Exemplos nativos brasileiros (sem sotaque americano): "
                "Luana 700d1ee3-a641-4018-ba6e-899dcadc9e2b, "
                "Ana Paula 1cf751f6-8749-43ab-98bd-230dd633abdb, "
                "Beatriz d4b44b9a-82bc-4b65-b456-763fce4c52f9, "
                "Isabella c9611be8-aae9-4a93-bb1c-98dd6b7d52a4. "
                f"Copie o UUID e cole no campo Voz (ttsVoice). Valor atual: '{voice_id}'"
            )

        payload = self._build_payload(clean_text)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Cartesia-Version": CARTESIA_VERSION,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        async with httpx.AsyncClient(timeout=CARTESIA_TIMEOUT_SECONDS) as client:
            response = await client.post(CARTESIA_TTS_BYTES_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            detail = _response_error(response)
            raise TTSConfigurationError(f"Cartesia TTS failed: {detail}")

        audio = response.content
        if not audio:
            raise TTSConfigurationError("Cartesia TTS returned empty audio.")

        return self._result(
            clean_text,
            audio,
            rate=str(self.speed),
        )

    def _build_payload(self, clean_text: str) -> dict[str, Any]:
        """Build request body for /tts/bytes."""
        voice_id = str(self.voice or "").strip()
        voice_spec: dict[str, Any] = {"mode": "id", "id": voice_id}  # caller ensures this is a valid UUID

        generation_config: dict[str, Any] = {}
        try:
            spd = float(self.speed)
            if spd != 1.0:
                generation_config["speed"] = max(0.5, min(2.0, spd))
        except (TypeError, ValueError):
            pass

        output_format = {
            "container": "mp3",
            "sample_rate": 44100,
        }

        payload: dict[str, Any] = {
            "model_id": self.model or DEFAULT_CARTESIA_MODEL,
            "transcript": clean_text,
            "voice": voice_spec,
            "language": self.language or DEFAULT_CARTESIA_LANGUAGE,
            "output_format": output_format,
        }
        if generation_config:
            payload["generation_config"] = generation_config

        return payload

    def _result(self, text: str, audio: bytes, *, rate: str) -> EdgeTTSResult:
        """Return provider-neutral result consumable by existing player/runtime."""
        return EdgeTTSResult(
            provider="cartesia",
            voice=str(self.voice or "custom"),
            rate=rate,
            pitch="default",
            volume="default",
            text=text,
            audio=audio,
            mime_type=CARTESIA_TTS_MIME,
        )


def _response_error(response: httpx.Response) -> str:
    """Compact error without leaking full key material."""
    try:
        data = response.json()
    except Exception:
        return response.text[:400]
    if isinstance(data, dict):
        err = data.get("error") or data.get("message") or data
        if isinstance(err, dict):
            return str(err.get("message") or err)
        return str(err)[:400]
    return str(data)[:400]
