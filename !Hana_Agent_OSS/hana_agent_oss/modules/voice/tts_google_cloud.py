from __future__ import annotations

import asyncio
import base64
import io
import os
import wave
from dataclasses import dataclass
from typing import Any

import httpx

from hana_agent_oss.modules.voice.tts_edge import EdgeTTSResult, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

GOOGLE_CLOUD_TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
DEFAULT_GOOGLE_CLOUD_TTS_VOICE = "pt-BR-Neural2-C"
DEFAULT_GOOGLE_CLOUD_TTS_LANGUAGE = "pt-BR"
DEFAULT_GOOGLE_CLOUD_TTS_ENCODING = "MP3"
GOOGLE_CLOUD_TTS_MIME = "audio/mpeg"
GOOGLE_CLOUD_TTS_STREAM_SAMPLE_RATE = 24_000
GOOGLE_CLOUD_TTS_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class GoogleCloudTTSProvider:
    """Google Cloud Text-to-Speech provider isolated from Gemini and LLM keys."""

    voice: str = DEFAULT_GOOGLE_CLOUD_TTS_VOICE
    language: str = DEFAULT_GOOGLE_CLOUD_TTS_LANGUAGE
    speaking_rate: float = 1.0
    pitch: float = 0.0
    streaming: bool = False

    async def synthesize(self, text: str) -> EdgeTTSResult:
        """Generate a complete MP3 payload with the Cloud Text-to-Speech REST API."""
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        if self.streaming and self.can_attempt_streaming():
            try:
                return await asyncio.to_thread(self._synthesize_streaming_sync, clean_text)
            except Exception:
                pass

        return await self._synthesize_rest(clean_text)

    def can_attempt_streaming(self) -> bool:
        """Return whether local credentials and a streaming-compatible voice are present."""
        return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")) and _is_chirp3_voice(self.voice)

    def streaming_fallback_reason(self) -> str:
        """Return a human-readable reason why REST fallback will be used."""
        if not self.streaming:
            return ""
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            return "GOOGLE_APPLICATION_CREDENTIALS ausente para streaming Cloud TTS."
        if not _is_chirp3_voice(self.voice):
            return "Streaming Cloud TTS requer voz Chirp 3 HD; usando REST MP3."
        return ""

    async def _synthesize_rest(self, clean_text: str) -> EdgeTTSResult:
        """Call REST text:synthesize using only GOOGLE_CLOUD_TTS_API_KEY."""
        api_key = os.environ.get("GOOGLE_CLOUD_TTS_API_KEY")
        if not api_key:
            raise TTSConfigurationError("GOOGLE_CLOUD_TTS_API_KEY is required for Google Cloud TTS.")

        payload = self.rest_payload(clean_text)
        async with httpx.AsyncClient(timeout=GOOGLE_CLOUD_TTS_TIMEOUT_SECONDS) as client:
            response = await client.post(GOOGLE_CLOUD_TTS_ENDPOINT, params={"key": api_key}, json=payload)
        if response.status_code >= 400:
            detail = _response_error(response)
            raise TTSConfigurationError(f"Google Cloud TTS REST failed: {detail}")

        data = response.json()
        audio_content = data.get("audioContent")
        if not audio_content:
            raise TTSConfigurationError("Google Cloud TTS returned no audioContent.")
        audio = base64.b64decode(str(audio_content))
        return self._result(clean_text, audio, rate=str(payload["audioConfig"]["speakingRate"]))

    def _synthesize_streaming_sync(self, clean_text: str) -> EdgeTTSResult:
        """Try Cloud TTS bidirectional streaming and collect the streamed audio chunks."""
        try:
            from google.cloud import texttospeech
        except Exception as exc:  # noqa: BLE001
            raise TTSConfigurationError("google-cloud-texttospeech is required for Cloud TTS streaming.") from exc

        client = texttospeech.TextToSpeechClient()
        streaming_config = texttospeech.StreamingSynthesizeConfig(
            voice=texttospeech.VoiceSelectionParams(
                name=self.voice,
                language_code=self.language or DEFAULT_GOOGLE_CLOUD_TTS_LANGUAGE,
            )
        )
        requests = (
            texttospeech.StreamingSynthesizeRequest(streaming_config=streaming_config),
            texttospeech.StreamingSynthesizeRequest(
                input=texttospeech.StreamingSynthesisInput(text=clean_text)
            ),
        )
        audio = b"".join(response.audio_content for response in client.streaming_synthesize(requests) if response.audio_content)
        if not audio:
            raise TTSConfigurationError("Google Cloud TTS streaming returned no audio.")
        return self._result(clean_text, _pcm_to_wav(audio), rate=str(self.speaking_rate), mime_type="audio/wav")

    def rest_payload(self, clean_text: str) -> dict[str, Any]:
        """Build the REST payload for unit tests and diagnostics."""
        return {
            "input": {"text": clean_text},
            "voice": {
                "languageCode": self.language or DEFAULT_GOOGLE_CLOUD_TTS_LANGUAGE,
                "name": self.voice or DEFAULT_GOOGLE_CLOUD_TTS_VOICE,
            },
            "audioConfig": {
                "audioEncoding": DEFAULT_GOOGLE_CLOUD_TTS_ENCODING,
                "speakingRate": _clamp(self.speaking_rate, 0.25, 4.0),
                "pitch": _clamp(self.pitch, -20.0, 20.0),
            },
        }

    def _result(self, text: str, audio: bytes, *, rate: str, mime_type: str = GOOGLE_CLOUD_TTS_MIME) -> EdgeTTSResult:
        """Return a provider-neutral TTS result for the existing player/runtime."""
        return EdgeTTSResult(
            provider="google_cloud_tts",
            voice=self.voice or DEFAULT_GOOGLE_CLOUD_TTS_VOICE,
            rate=rate,
            pitch=str(_clamp(self.pitch, -20.0, 20.0)),
            volume="default",
            text=text,
            audio=audio,
            mime_type=mime_type,
        )


def _is_chirp3_voice(voice: str) -> bool:
    """Return whether the voice name is in the Cloud TTS streaming family."""
    return "chirp3" in str(voice or "").lower()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp numeric Cloud TTS tuning values to API-safe ranges."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 1.0 if minimum <= 1.0 <= maximum else 0.0
    return max(minimum, min(maximum, number))


def _response_error(response: httpx.Response) -> str:
    """Extract a compact Google API error message without logging credentials."""
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(data)[:300]


def _pcm_to_wav(audio: bytes) -> bytes:
    """Wrap Cloud TTS streaming PCM chunks as WAV for the local pygame player."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(GOOGLE_CLOUD_TTS_STREAM_SAMPLE_RATE)
        wav.writeframes(audio)
    return buffer.getvalue()
