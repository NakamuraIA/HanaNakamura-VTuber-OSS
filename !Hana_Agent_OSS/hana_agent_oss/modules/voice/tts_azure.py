"""
Azure Cognitive Services TTS provider for the new Hana OSS voice runtime.

Provides high-quality native Brazilian Portuguese (pt-BR) voices with authentic accent
(no American English bleed). Excellent naturalness, prosody, and support for SSML
(rate, pitch, style).

Uses pure httpx + Microsoft TTS REST API (no extra SDK dependency beyond what's
already used for other providers). Low latency when region is close (brazilsouth etc.).

Config via env:
- AZURE_SPEECH_KEY (or AZURE_TTS_KEY)
- AZURE_REGION (e.g. "brazilsouth", "eastus")

Separate from LLM/STT. Voices like pt-BR-FranciscaNeural, pt-BR-ThalitaNeural are
top-tier native female Brazilian options.

See catalog for full list of offered pt-BR voices.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from hana_agent_oss.modules.voice.tts_edge import EdgeTTSResult, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

DEFAULT_AZURE_VOICE = "pt-BR-FranciscaNeural"
DEFAULT_AZURE_LANGUAGE = "pt-BR"
AZURE_TTS_MIME = "audio/mpeg"
AZURE_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class AzureTTSProvider:
    """Azure TTS provider (native pt-BR strength, good quality + reasonable latency)."""

    voice: str = DEFAULT_AZURE_VOICE
    language: str = DEFAULT_AZURE_LANGUAGE
    speed: float = 1.0
    pitch: float = 0.0
    # region and key from env

    async def synthesize(self, text: str) -> EdgeTTSResult:
        """Synthesize using Azure REST (SSML for prosody control)."""
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        key = os.environ.get("AZURE_SPEECH_KEY") or os.environ.get("AZURE_TTS_KEY")
        region = os.environ.get("AZURE_REGION") or "brazilsouth"

        if not key or not region:
            raise TTSConfigurationError(
                "AZURE_SPEECH_KEY and AZURE_REGION are required for Azure TTS. "
                "Get key from Azure Portal > Cognitive Services > Speech."
            )

        ssml = self._build_ssml(clean_text)

        endpoint = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
            "User-Agent": "HanaAgentTTS",
        }

        async with httpx.AsyncClient(timeout=AZURE_TIMEOUT_SECONDS) as client:
            response = await client.post(endpoint, headers=headers, content=ssml.encode("utf-8"))

        if response.status_code >= 400:
            detail = _response_error(response)
            raise TTSConfigurationError(f"Azure TTS failed: {detail}")

        audio = response.content
        if not audio:
            raise TTSConfigurationError("Azure TTS returned empty audio.")

        return self._result(clean_text, audio)

    def _build_ssml(self, clean_text: str) -> str:
        """Build SSML with voice + optional prosody for speed/pitch."""
        rate = self._format_rate(self.speed)
        pitch = self._format_pitch(self.pitch)

        prosody_attrs = []
        if rate != "default":
            prosody_attrs.append(f'rate="{rate}"')
        if pitch != "default":
            prosody_attrs.append(f'pitch="{pitch}"')

        prosody_open = f"<prosody {' '.join(prosody_attrs)}>" if prosody_attrs else ""
        prosody_close = "</prosody>" if prosody_attrs else ""

        # Escape for SSML safety (basic)
        escaped = clean_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        return f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{self.language or DEFAULT_AZURE_LANGUAGE}">
  <voice name="{self.voice or DEFAULT_AZURE_VOICE}">
    {prosody_open}{escaped}{prosody_close}
  </voice>
</speak>"""

    def _format_rate(self, speed: float) -> str:
        try:
            s = float(speed)
            if abs(s - 1.0) < 0.05:
                return "default"
            pct = int((s - 1.0) * 100)
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct}%"
        except (TypeError, ValueError):
            return "default"

    def _format_pitch(self, pitch: float) -> str:
        try:
            p = float(pitch)
            if abs(p) < 0.5:
                return "default"
            # Treat as semitones or percent; Azure accepts +2st or +10%
            if abs(p) <= 10:
                sign = "+" if p >= 0 else ""
                return f"{sign}{int(p)}st"  # semitones, common for Azure
            sign = "+" if p >= 0 else ""
            return f"{sign}{int(p)}%"
        except (TypeError, ValueError):
            return "default"

    def _result(self, text: str, audio: bytes) -> EdgeTTSResult:
        return EdgeTTSResult(
            provider="azure",
            voice=str(self.voice or DEFAULT_AZURE_VOICE),
            rate=str(self.speed),
            pitch=str(self.pitch),
            volume="default",
            text=text,
            audio=audio,
            mime_type=AZURE_TTS_MIME,
        )


def _response_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        return response.text[:400] or f"HTTP {response.status_code}"
    if isinstance(data, dict):
        return str(data.get("error") or data.get("message") or data)[:400]
    return str(data)[:400]
