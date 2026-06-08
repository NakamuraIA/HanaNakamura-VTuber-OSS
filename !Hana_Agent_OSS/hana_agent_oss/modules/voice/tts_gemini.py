from __future__ import annotations

import io
import os
import wave
import asyncio
import base64
from dataclasses import dataclass
from typing import Any

from hana_agent_oss.modules.voice.tts_edge import EdgeTTSResult, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

DEFAULT_GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_GEMINI_TTS_VOICE = "Kore"
DEFAULT_GEMINI_TTS_PROMPT = (
    "You are generating TTS audio in Brazilian Portuguese.\n"
    "Voice character: young adult AI assistant.\n"
    "Tone: warm, playful, slightly teasing, but not childish.\n"
    "Pace: medium, with natural pauses.\n"
    "Accent: neutral Brazilian Portuguese.\n"
    "Do not read these instructions aloud. Only synthesize the transcript."
)
GEMINI_TTS_VOICES = {
    "Achernar",
    "Achird",
    "Algenib",
    "Algieba",
    "Alnilam",
    "Aoede",
    "Autonoe",
    "Callirrhoe",
    "Charon",
    "Despina",
    "Enceladus",
    "Erinome",
    "Fenrir",
    "Gacrux",
    "Iapetus",
    "Kore",
    "Laomedeia",
    "Leda",
    "Orus",
    "Puck",
    "Pulcherrima",
    "Rasalgethi",
    "Sadachbia",
    "Sadaltager",
    "Schedar",
    "Sulafat",
    "Umbriel",
    "Vindemiatrix",
    "Zephyr",
    "Zubenelgenubi",
}
GEMINI_TTS_SAMPLE_RATE = 24_000
GEMINI_TTS_CHANNELS = 1
GEMINI_TTS_SAMPLE_WIDTH = 2
GEMINI_TTS_MIME = "audio/wav"


@dataclass(frozen=True)
class GeminiTTSProvider:
    """Google AI Studio Gemini TTS provider used only for text-to-speech audio."""

    model: str = DEFAULT_GEMINI_TTS_MODEL
    voice: str = DEFAULT_GEMINI_TTS_VOICE
    language: str = "pt-BR"
    style_prompt: str = DEFAULT_GEMINI_TTS_PROMPT

    async def synthesize(self, text: str) -> EdgeTTSResult:
        """Generate WAV audio from sanitized text through Gemini speech generation.
        
        Splits the text into smaller chunks and synthesizes them concurrently to prevent timeouts/errors on larger texts.
        """
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        chunks = split_text_for_tts(clean_text, max_chars=150)
        if not chunks:
            raise ValueError("No text chunks to synthesize.")

        voice = _normalize_voice(self.voice)

        # Concurrently synthesize all chunks
        tasks = [asyncio.to_thread(self._synthesize_chunk_pcm, chunk) for chunk in chunks]
        results = await asyncio.gather(*tasks)

        # Concatenate PCM bytes and build a single WAV
        final_pcm = b"".join(results)
        final_wav = _pcm_to_wav(final_pcm)

        return EdgeTTSResult(
            provider="gemini_tts",
            voice=voice,
            rate="default",
            pitch="default",
            volume="default",
            text=clean_text,
            audio=final_wav,
            mime_type=GEMINI_TTS_MIME,
        )

    def _synthesize_chunk_pcm(self, text: str) -> bytes:
        """Synthesize a single text chunk and return raw 24kHz 16-bit mono PCM bytes."""
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:  # noqa: BLE001
            raise TTSConfigurationError("The google-genai package is required for Gemini TTS.") from exc

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise TTSConfigurationError("GEMINI_API_KEY or GOOGLE_API_KEY is required for Gemini TTS.")

        client = genai.Client(api_key=api_key)
        model = (self.model or DEFAULT_GEMINI_TTS_MODEL).strip() or DEFAULT_GEMINI_TTS_MODEL
        voice = _normalize_voice(self.voice)
        language = (self.language or "pt-BR").strip() or "pt-BR"
        prompt = _build_prompt(text, self.style_prompt)

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    language_code=language,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    ),
                ),
            ),
        )
        audio_bytes, _ = _extract_audio(response)
        if not audio_bytes:
            raise TTSConfigurationError("Gemini TTS returned no audio for a chunk.")
            
        return _get_raw_pcm(audio_bytes)

    def synthesize_sync(self, text: str) -> EdgeTTSResult:
        """Fallback synchronous method that synthesizes the entire text in a single block."""
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        try:
            from google import genai
            from google.genai import types
        except Exception as exc:  # noqa: BLE001
            raise TTSConfigurationError("The google-genai package is required for Gemini TTS.") from exc

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise TTSConfigurationError("GEMINI_API_KEY or GOOGLE_API_KEY is required for Gemini TTS.")

        client = genai.Client(api_key=api_key)
        model = (self.model or DEFAULT_GEMINI_TTS_MODEL).strip() or DEFAULT_GEMINI_TTS_MODEL
        voice = _normalize_voice(self.voice)
        language = (self.language or "pt-BR").strip() or "pt-BR"
        prompt = _build_prompt(clean_text, self.style_prompt)

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    language_code=language,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    ),
                ),
            ),
        )
        audio_bytes, mime_type = _extract_audio(response)
        if not audio_bytes:
            raise TTSConfigurationError("Gemini TTS returned no audio.")
        if not _looks_like_wav(audio_bytes):
            audio_bytes = _pcm_to_wav(audio_bytes)
            mime_type = GEMINI_TTS_MIME

        return EdgeTTSResult(
            provider="gemini_tts",
            voice=voice,
            rate="default",
            pitch="default",
            volume="default",
            text=clean_text,
            audio=audio_bytes,
            mime_type=_normalize_mime_type(mime_type),
        )


def _extract_audio(response: Any) -> tuple[bytes, str]:
    """Extract inline audio bytes from a Gemini SDK response object."""
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
            if not inline_data:
                continue
            data = getattr(inline_data, "data", None)
            if not data:
                continue
            mime_type = getattr(inline_data, "mime_type", None) or getattr(inline_data, "mimeType", None) or "audio/pcm"
            if isinstance(data, str):
                return base64.b64decode(data), str(mime_type)
            return bytes(data), str(mime_type)
    return b"", ""


def _build_prompt(clean_text: str, style_prompt: str) -> str:
    """Build a separated director prompt so Gemini does not speak instructions."""
    style = str(style_prompt or DEFAULT_GEMINI_TTS_PROMPT).strip() or DEFAULT_GEMINI_TTS_PROMPT
    return (
        f"{style}\n\n"
        "# DIRECTOR'S NOTES\n"
        "Do not add words, explanations, greetings, or commentary.\n"
        "Do not read section names aloud.\n\n"
        "# TRANSCRIPT\n"
        f"{clean_text}"
    )


def _normalize_voice(voice: str) -> str:
    """Map non-Gemini voice IDs from other providers to the Gemini default voice."""
    value = str(voice or "").strip()
    if value in GEMINI_TTS_VOICES:
        return value
    if value.startswith("pt-") or value.endswith("Neural"):
        return DEFAULT_GEMINI_TTS_VOICE
    return value or DEFAULT_GEMINI_TTS_VOICE


def _looks_like_wav(audio: bytes) -> bool:
    """Return whether audio already has a RIFF/WAVE container."""
    return audio.startswith(b"RIFF") and b"WAVE" in audio[:16]


def _pcm_to_wav(audio: bytes) -> bytes:
    """Wrap Gemini raw 24 kHz 16-bit mono PCM as a WAV file for pygame playback."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(GEMINI_TTS_CHANNELS)
        wav.setsampwidth(GEMINI_TTS_SAMPLE_WIDTH)
        wav.setframerate(GEMINI_TTS_SAMPLE_RATE)
        wav.writeframes(audio)
    return buffer.getvalue()


def _normalize_mime_type(mime_type: str) -> str:
    """Normalize Gemini audio MIME strings to a format understood by the local player."""
    value = str(mime_type or "").lower()
    if "wav" in value or "wave" in value:
        return GEMINI_TTS_MIME
    return GEMINI_TTS_MIME


def _get_raw_pcm(audio_bytes: bytes) -> bytes:
    """Extract raw PCM bytes from WAV, or return as-is if already raw PCM."""
    if _looks_like_wav(audio_bytes):
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
                return wav.readframes(wav.getnframes())
        except Exception:
            pass
    return audio_bytes


def split_text_for_tts(text: str, max_chars: int = 150) -> list[str]:
    """Split text into sentences using punctuation while maintaining a safe length for TTS synthesis."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(current_chunk) + len(sentence) + 1 <= max_chars:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)
            if len(sentence) > max_chars:
                words = sentence.split(" ")
                sub_chunk = ""
                for word in words:
                    if len(sub_chunk) + len(word) + 1 <= max_chars:
                        if sub_chunk:
                            sub_chunk += " " + word
                        else:
                            sub_chunk = word
                    else:
                        if sub_chunk:
                            chunks.append(sub_chunk)
                        sub_chunk = word
                if sub_chunk:
                    current_chunk = sub_chunk
            else:
                current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk)
    return chunks
