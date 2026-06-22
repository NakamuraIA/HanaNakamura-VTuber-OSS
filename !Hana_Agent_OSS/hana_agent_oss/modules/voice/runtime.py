from __future__ import annotations

import asyncio
import io
import logging
import math
import re
import tempfile
import threading
import time
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from hana_agent_oss.api.services.catalog import DEFAULT_CONNECTIONS, DEFAULT_LLM_CONFIG, DEFAULT_VOICE_CONFIG
from hana_agent_oss.api.services.chat import STREAMING_PROVIDERS, run_text_turn
from hana_agent_oss.api.services.terminal_agent import append_terminal_event
from hana_agent_oss.api.services.unified_history import build_unified_history
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.voice import audio_control
from hana_agent_oss.modules.voice.speech_state import is_speaking, set_speaking
from hana_agent_oss.modules.voice.stt_whisper import GroqWhisperSTTProvider, STTConfigurationError
from hana_agent_oss.persona import build_stt_prompt
from hana_agent_oss.modules.voice.tts_edge import EdgeTTSProvider, EdgeTTSPlayer, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_gemini import DEFAULT_GEMINI_TTS_MODEL, DEFAULT_GEMINI_TTS_VOICE, GeminiTTSProvider
from hana_agent_oss.modules.voice.tts_google_cloud import (
    DEFAULT_GOOGLE_CLOUD_TTS_VOICE,
    GoogleCloudTTSProvider,
)
from hana_agent_oss.modules.voice.tts_cartesia import CartesiaTTSProvider, DEFAULT_CARTESIA_MODEL
from hana_agent_oss.modules.voice.tts_azure import AzureTTSProvider
from hana_agent_oss.modules.voice.tts_minimax import MinimaxTTSProvider
from hana_agent_oss.modules.voice.tts_elevenlabs import ElevenlabsTTSProvider, DEFAULT_ELEVENLABS_VOICE, DEFAULT_ELEVENLABS_MODEL
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2
BLOCK_SIZE = 1024
BLOCK_MS = int(BLOCK_SIZE / SAMPLE_RATE * 1000)
PRE_ROLL_MS = 250
MIN_ACTIVE_VOICE_MS = 240
MIN_RECORDING_MS = 450
PTT_MIN_ACTIVE_VOICE_MS = BLOCK_MS
PTT_MIN_RECORDING_MS = 80
PTT_MIN_PEAK_RMS = 0.012
PTT_THRESHOLD_SCALE = 0.60
MAX_RECORDING_MS = 18_000
INTERRUPT_DEBOUNCE_SECONDS = 0.5
# Run neural inference whenever there is any non-silence energy. Kept well below
# the gate's decision floor so quiet speech is never skipped before Silero sees it.
SILERO_PREFILTER_RMS = 0.004
# Throttle for the live VAD calibration diagnostic (helps tune prob threshold).
VAD_DIAG_INTERVAL_SECONDS = 3.0
# Barge-in (falar por cima): criterios ELEVADOS contra eco quando a Hana usa
# caixas de som (o mic capta a propria voz dela). Exige fala alta e sustentada.
BARGE_IN_PROB = 0.70
BARGE_IN_MIN_RMS = 0.050
BARGE_IN_MIN_SPEECH_MS = 400
# Teto de tamanho do texto FALADO (protege credito de TTS, que e caro). O modelo
# as vezes ignora a instrucao de ser curto; isso garante o corte. 0 = sem limite.
DEFAULT_TTS_MAX_CHARS = 350


@dataclass
class VoiceRuntimeConfig:
    """Runtime-ready voice config derived from persisted UI settings."""

    stt_provider: str = "groq_whisper"
    stt_model: str = "whisper-large-v3"
    stt_language: str = "pt"
    stt_enabled: bool = False
    input_device_id: str = ""
    input_device_label: str = ""
    second_output_enabled: bool = False
    second_output_device_id: str = ""
    second_output_device_label: str = ""
    vad_enabled: bool = True
    ptt_enabled: bool = False
    call_mode: bool = False
    vad_threshold: float = 0.035
    vad_mode: str = "silero"
    vad_prob_threshold: float = 0.5
    barge_in_enabled: bool = False
    silence_timeout_ms: int = 900
    tts_enabled: bool = False
    tts_provider: str = "edge"
    tts_model: str = ""
    tts_voice: str = "pt-BR-FranciscaNeural"
    tts_language: str = "pt-BR"
    tts_prompt: str = ""
    tts_speed: float = 1.0
    tts_pitch: float = 0.0
    tts_volume: float = 1.0
    tts_streaming: bool = False
    tts_stability: float = 0.5
    tts_similarity: float = 0.75
    tts_style: float = 0.0
    tts_speaker_boost: bool = True
    tts_max_chars: int = DEFAULT_TTS_MAX_CHARS

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "VoiceRuntimeConfig":
        source = dict(DEFAULT_VOICE_CONFIG)
        source.update(payload or {})
        try:
            vad_threshold = float(source.get("vadThreshold") or DEFAULT_VOICE_CONFIG["vadThreshold"])
        except (TypeError, ValueError):
            vad_threshold = float(DEFAULT_VOICE_CONFIG["vadThreshold"])
        try:
            silence_timeout_ms = int(source.get("silenceTimeoutMs") or DEFAULT_VOICE_CONFIG["silenceTimeoutMs"])
        except (TypeError, ValueError):
            silence_timeout_ms = int(DEFAULT_VOICE_CONFIG["silenceTimeoutMs"])
        try:
            vad_prob_threshold = float(source.get("vadProbThreshold", DEFAULT_VOICE_CONFIG["vadProbThreshold"]))
        except (TypeError, ValueError):
            vad_prob_threshold = float(DEFAULT_VOICE_CONFIG["vadProbThreshold"])
        vad_mode = str(source.get("vadMode") or DEFAULT_VOICE_CONFIG["vadMode"]).strip().lower()
        if vad_mode not in {"silero", "rms"}:
            vad_mode = "silero"
        try:
            tts_speed = float(source.get("ttsSpeed") or DEFAULT_VOICE_CONFIG["ttsSpeed"])
        except (TypeError, ValueError):
            tts_speed = float(DEFAULT_VOICE_CONFIG["ttsSpeed"])
        try:
            tts_pitch = float(source.get("ttsPitch") or DEFAULT_VOICE_CONFIG["ttsPitch"])
        except (TypeError, ValueError):
            tts_pitch = float(DEFAULT_VOICE_CONFIG["ttsPitch"])
        try:
            tts_volume = float(source.get("ttsVolume", DEFAULT_VOICE_CONFIG["ttsVolume"]))
        except (TypeError, ValueError):
            tts_volume = float(DEFAULT_VOICE_CONFIG["ttsVolume"])
        try:
            tts_stability = float(source.get("ttsStability", DEFAULT_VOICE_CONFIG["ttsStability"]))
        except (TypeError, ValueError):
            tts_stability = float(DEFAULT_VOICE_CONFIG["ttsStability"])
        try:
            tts_similarity = float(source.get("ttsSimilarity", DEFAULT_VOICE_CONFIG["ttsSimilarity"]))
        except (TypeError, ValueError):
            tts_similarity = float(DEFAULT_VOICE_CONFIG["ttsSimilarity"])
        try:
            tts_style = float(source.get("ttsStyle", DEFAULT_VOICE_CONFIG["ttsStyle"]))
        except (TypeError, ValueError):
            tts_style = float(DEFAULT_VOICE_CONFIG["ttsStyle"])
        try:
            tts_max_chars = int(source.get("ttsMaxChars", DEFAULT_VOICE_CONFIG["ttsMaxChars"]))
        except (TypeError, ValueError):
            tts_max_chars = DEFAULT_TTS_MAX_CHARS

        return cls(
            stt_provider=str(source.get("sttProvider") or "groq_whisper"),
            stt_model=str(source.get("sttModel") or "whisper-large-v3"),
            stt_language=str(source.get("sttLanguage") or "pt"),
            stt_enabled=bool(source.get("sttEnabled", False)),
            input_device_id=str(source.get("inputDeviceId") or ""),
            input_device_label=str(source.get("inputDeviceLabel") or ""),
            second_output_enabled=bool(source.get("secondOutputEnabled", False)),
            second_output_device_id=str(source.get("secondOutputDeviceId") or ""),
            second_output_device_label=str(source.get("secondOutputDeviceLabel") or ""),
            vad_enabled=bool(source.get("vadEnabled", True)),
            ptt_enabled=bool(source.get("pttEnabled", False)),
            call_mode=bool(source.get("callMode", False)),
            vad_threshold=max(0.001, vad_threshold),
            vad_mode=vad_mode,
            vad_prob_threshold=max(0.0, min(1.0, vad_prob_threshold)),
            barge_in_enabled=bool(source.get("bargeInEnabled", False)),
            silence_timeout_ms=max(250, silence_timeout_ms),
            tts_enabled=bool(source.get("ttsEnabled")),
            tts_provider=str(source.get("ttsProvider") or "edge"),
            tts_model=str(source.get("ttsModel") or ""),
            tts_voice=str(source.get("ttsVoice") or "pt-BR-FranciscaNeural"),
            tts_language=str(source.get("ttsLanguage") or "pt-BR"),
            tts_prompt=str(source.get("ttsPrompt") or ""),
            tts_speed=tts_speed,
            tts_pitch=tts_pitch,
            tts_volume=max(0.0, min(1.0, tts_volume)),
            tts_streaming=bool(source.get("ttsStreaming", True)),
            tts_stability=max(0.0, min(1.0, tts_stability)),
            tts_similarity=max(0.0, min(1.0, tts_similarity)),
            tts_style=max(0.0, min(1.0, tts_style)),
            tts_speaker_boost=bool(source.get("ttsSpeakerBoost", True)),
            tts_max_chars=max(0, tts_max_chars),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sttProvider": self.stt_provider,
            "sttModel": self.stt_model,
            "sttLanguage": self.stt_language,
            "sttEnabled": self.stt_enabled,
            "inputDeviceId": self.input_device_id,
            "inputDeviceLabel": self.input_device_label,
            "secondOutputEnabled": self.second_output_enabled,
            "secondOutputDeviceId": self.second_output_device_id,
            "secondOutputDeviceLabel": self.second_output_device_label,
            "vadEnabled": self.vad_enabled,
            "pttEnabled": self.ptt_enabled,
            "callMode": self.call_mode,
            "vadThreshold": self.vad_threshold,
            "vadMode": self.vad_mode,
            "vadProbThreshold": self.vad_prob_threshold,
            "bargeInEnabled": self.barge_in_enabled,
            "silenceTimeoutMs": self.silence_timeout_ms,
            "ttsEnabled": self.tts_enabled,
            "ttsProvider": self.tts_provider,
            "ttsModel": self.tts_model,
            "ttsVoice": self.tts_voice,
            "ttsLanguage": self.tts_language,
            "ttsPrompt": self.tts_prompt,
            "ttsSpeed": self.tts_speed,
            "ttsPitch": self.tts_pitch,
            "ttsVolume": self.tts_volume,
            "ttsStreaming": self.tts_streaming,
            "ttsStability": self.tts_stability,
            "ttsSimilarity": self.tts_similarity,
            "ttsStyle": self.tts_style,
            "ttsSpeakerBoost": self.tts_speaker_boost,
            "ttsMaxChars": self.tts_max_chars,
        }


@dataclass
class VoiceRuntimeStatus:
    """Serializable status snapshot for the control panel."""

    running: bool = False
    state: str = "idle"
    error: str = ""
    started_at: float = 0.0
    updated_at: float = field(default_factory=time.time)
    turns: int = 0
    last_transcript: str = ""
    last_response: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "state": self.state,
            "error": self.error,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "turns": self.turns,
            "lastTranscript": self.last_transcript,
            "lastResponse": self.last_response,
            "config": self.config,
        }


class RmsVoiceGate:
    """Deterministic capture gate run before expensive STT calls.

    Owns the start/stop *timing* (pre-roll, min duration, silence timeout). The
    per-frame "is this voice?" decision is either pure energy (``rms >=
    threshold``) or, when a neural ``speech_prob`` is supplied, a hybrid of the
    neural probability AND an amplitude floor — so the same timing logic serves
    both the RMS and the Silero VAD modes.
    """

    def __init__(
        self,
        *,
        threshold: float,
        silence_timeout_ms: int,
        frame_ms: int = BLOCK_MS,
        min_active_ms: int = MIN_ACTIVE_VOICE_MS,
        min_recording_ms: int = MIN_RECORDING_MS,
        max_recording_ms: int = MAX_RECORDING_MS,
        prob_threshold: float = 0.5,
        min_rms: float = 0.006,
    ) -> None:
        self.threshold = max(0.001, float(threshold))
        self.silence_timeout_ms = max(frame_ms, int(silence_timeout_ms))
        self.frame_ms = max(1, int(frame_ms))
        self.min_active_ms = int(min_active_ms)
        self.min_recording_ms = int(min_recording_ms)
        self.max_recording_ms = int(max_recording_ms)
        self.prob_threshold = max(0.0, min(1.0, float(prob_threshold)))
        self.min_rms = max(0.0, float(min_rms))
        self.recording = False
        self.active_ms = 0
        self.silence_ms = 0
        self.duration_ms = 0
        self.max_rms = 0.0

    def reset(self) -> None:
        self.recording = False
        self.active_ms = 0
        self.silence_ms = 0
        self.duration_ms = 0
        self.max_rms = 0.0

    def push(self, rms: float, *, speech_prob: float | None = None) -> str:
        self.max_rms = max(self.max_rms, rms)
        if speech_prob is None:
            is_active = rms >= self.threshold
        else:
            # Hybrid: neural says "speech" AND there is enough amplitude.
            is_active = speech_prob >= self.prob_threshold and rms >= self.min_rms

        if not self.recording:
            if is_active:
                self.recording = True
                self.active_ms = self.frame_ms
                self.silence_ms = 0
                self.duration_ms = self.frame_ms
                return "start"
            return "idle"

        self.duration_ms += self.frame_ms
        if is_active:
            self.active_ms += self.frame_ms
            self.silence_ms = 0
        else:
            self.silence_ms += self.frame_ms

        if self.duration_ms >= self.max_recording_ms:
            return "end"
        if self.silence_ms >= self.silence_timeout_ms and self.duration_ms >= self.min_recording_ms:
            return "end" if self.active_ms >= self.min_active_ms else "discard"
        return "recording"


class BargeInGate:
    """Decide when sustained user speech should interrupt the Hana's TTS.

    Uses an elevated bar (loud + confident + sustained) so the model's own voice
    leaking into the mic on speakers does not make it cut itself off. Inactive
    frames decay the counter so intermittent echo blips never accumulate.
    """

    def __init__(
        self,
        *,
        prob_threshold: float = BARGE_IN_PROB,
        min_rms: float = BARGE_IN_MIN_RMS,
        min_speech_ms: int = BARGE_IN_MIN_SPEECH_MS,
        frame_ms: int = BLOCK_MS,
    ) -> None:
        self.prob_threshold = max(0.0, min(1.0, float(prob_threshold)))
        self.min_rms = max(0.0, float(min_rms))
        self.min_speech_ms = max(frame_ms, int(min_speech_ms))
        self.frame_ms = max(1, int(frame_ms))
        self.active_ms = 0

    def push(self, rms: float, speech_prob: float | None = None) -> bool:
        if speech_prob is None:
            is_active = rms >= self.min_rms
        else:
            is_active = speech_prob >= self.prob_threshold and rms >= self.min_rms
        if is_active:
            self.active_ms += self.frame_ms
        else:
            self.active_ms = max(0, self.active_ms - self.frame_ms)
        return self.active_ms >= self.min_speech_ms


def pcm16_rms(frame: bytes) -> float:
    """Return normalized RMS for little-endian 16-bit PCM bytes."""
    if not frame:
        return 0.0
    samples = array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % SAMPLE_WIDTH)])
    if not samples:
        return 0.0
    total = sum(int(sample) * int(sample) for sample in samples)
    return min(1.0, math.sqrt(total / len(samples)) / 32768.0)


def pcm16_wav_bytes(frames: list[bytes]) -> bytes:
    """Wrap raw mono PCM frames as an in-memory 16 kHz WAV."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"".join(frames))
    return buffer.getvalue()


def sounddevice_index(device_id: str) -> int | None:
    value = str(device_id or "").strip()
    if not value or value in {"default", "browser_default"}:
        return None
    if value.startswith("sounddevice:"):
        value = value.split(":", 1)[1]
    try:
        return int(value)
    except ValueError:
        return None


# Generic words that appear in almost every Windows mic name and carry no identity.
_DEVICE_STOPWORDS = {"microphone", "mic", "input", "audio", "device", "sound", "realtek", "default"}


def _device_name_tokens(label: str) -> set[str]:
    """Distinctive lowercased tokens from a device label (e.g. {'fifine'})."""
    import re as _re

    raw = _re.findall(r"[a-z0-9]+", str(label or "").lower())
    return {tok for tok in raw if len(tok) >= 3 and tok not in _DEVICE_STOPWORDS}


def resolve_input_device(device_id: str, label: str = "") -> int | None:
    """Resolve the mic to a sounddevice index, self-correcting a stale index by name.

    The stored device is a raw numeric index. On Windows that index DRIFTS when the
    device list reorders (host-API churn MME/WASAPI, plugging gear, toggling a
    modifier). A drifted index still opens *some* device without error and that device
    delivers pure silence (rms=0.0) — the mic looks "dead for no reason". So we verify
    the stored index still points at a device matching the saved label; if not, we hunt
    for an input-capable device whose name carries the same distinctive token (e.g.
    'fifine') and use that instead. Index stays authoritative when it's still valid.
    """
    idx = sounddevice_index(device_id)
    tokens = _device_name_tokens(label)
    if not tokens:
        return idx  # no name to match against — trust the stored index

    try:
        import sounddevice as sd  # type: ignore[import-not-found]

        devices = sd.query_devices()
    except Exception:
        return idx  # can't enumerate — fall back to the stored index

    def is_input(dev: Any) -> bool:
        try:
            return int(dev.get("max_input_channels") or 0) > 0
        except Exception:
            return False

    # 1) Is the stored index still the right device? Then nothing changed — keep it.
    if idx is not None and 0 <= idx < len(devices):
        dev = devices[idx]
        if is_input(dev) and tokens & _device_name_tokens(str(dev.get("name") or "")):
            return idx

    # 2) Index drifted (or points at a silent device): find the mic by name.
    for i, dev in enumerate(devices):
        if is_input(dev) and tokens & _device_name_tokens(str(dev.get("name") or "")):
            logger.warning(
                "[VOICE RUNTIME] Indice de mic %s nao bate com '%s'; usando device %s ('%s') por nome.",
                idx, label, i, dev.get("name"),
            )
            return i

    return idx  # no name match anywhere — last resort, stored index


def resolve_output_device(device_id: str, label: str = "") -> int | None:
    """Resolve the second-output device index, self-correcting a stale index by name.

    Same drift problem as the mic (Windows reorders the device list), so the stored
    index for the virtual cable can point at the wrong endpoint. We verify it still
    matches the saved label and otherwise hunt for an output-capable device by name.
    """
    idx = sounddevice_index(device_id)
    tokens = _device_name_tokens(label)
    if not tokens:
        return idx

    try:
        import sounddevice as sd  # type: ignore[import-not-found]

        devices = sd.query_devices()
    except Exception:
        return idx

    def is_output(dev: Any) -> bool:
        try:
            return int(dev.get("max_output_channels") or 0) > 0
        except Exception:
            return False

    if idx is not None and 0 <= idx < len(devices):
        dev = devices[idx]
        if is_output(dev) and tokens & _device_name_tokens(str(dev.get("name") or "")):
            return idx

    for i, dev in enumerate(devices):
        if is_output(dev) and tokens & _device_name_tokens(str(dev.get("name") or "")):
            logger.warning(
                "[VOICE RUNTIME] Indice da 2a saida %s nao bate com '%s'; usando device %s ('%s') por nome.",
                idx, label, i, dev.get("name"),
            )
            return i

    return idx


def open_input_stream(device: int | None):
    """Open a mic RawInputStream, falling back to the system default on PortAudio errors.

    The Windows device list has many duplicates of the same mic across host APIs
    (MME/WASAPI/DirectSound). A stored index can go stale ("device ID out of range",
    PaError -9999) or a given host variant may reject mono ("invalid number of
    channels", -9998). Instead of crashing the whole voice runtime, we retry with
    device=None so PortAudio negotiates a valid default — voice keeps working even
    when the exact selected endpoint is broken.
    """
    import sounddevice as sd

    try:
        return sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, channels=CHANNELS, dtype="int16", device=device
        )
    except Exception as exc:
        if device is None:
            raise
        logger.warning(
            "[VOICE RUNTIME] Falha ao abrir mic device=%s (%s); caindo pro device padrao do sistema.",
            device, exc,
        )
        return sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, channels=CHANNELS, dtype="int16", device=None
        )


def ptt_audio_is_usable(stats: dict[str, Any], *, vad_threshold: float) -> bool:
    """Return whether a PTT capture has intentional speech, including short words."""
    duration_ms = int(stats.get("durationMs") or 0)
    active_ms = int(stats.get("activeMs") or 0)
    try:
        max_rms = float(stats.get("maxRms") or 0.0)
    except (TypeError, ValueError):
        max_rms = 0.0
    min_peak_rms = max(PTT_MIN_PEAK_RMS, float(vad_threshold) * PTT_THRESHOLD_SCALE)
    return (
        duration_ms >= PTT_MIN_RECORDING_MS
        and active_ms >= PTT_MIN_ACTIVE_VOICE_MS
        and max_rms >= min_peak_rms
    )


_XML_BLOCK_RE = re.compile(
    r"<(gerar_imagem|editar_imagem|salvar_memoria)\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_XML_TAG_RE = re.compile(r"<[^>]+>")
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?…]+(?=\s|$)|\n+")


def clamp_tts_text(text: str, max_chars: int) -> str:
    """Trim spoken text to ~max_chars at a sentence boundary (protects TTS credit)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    window = text[:max_chars]
    # Prefer cutting at the last sentence end within the window.
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "), window.rfind("\n"))
    if cut < max_chars * 0.5:
        cut = window.rfind(" ")  # senao corta na ultima palavra inteira
    if cut <= 0:
        cut = max_chars
    return text[: cut + 1].strip()


def strip_xml_for_tts(text: str) -> str:
    """Remove action/memory XML (e.g. <gerar_imagem>...) so it is never spoken."""
    text = _XML_BLOCK_RE.sub(" ", text)
    text = _XML_TAG_RE.sub(" ", text)
    return text


def extract_speakable_chunks(buffer: str, *, flush: bool = False) -> tuple[list[str], str]:
    """Split a growing LLM buffer into complete sentences ready to speak.

    Returns (chunks, remaining). XML-safe: while streaming, never emits past the
    first ``<`` (a tag may be opening) so action/memory blocks are not voiced;
    on ``flush`` the tail is emitted (with XML stripped by the caller).
    """
    if not flush:
        lt = buffer.find("<")
        safe, held = (buffer[:lt], buffer[lt:]) if lt != -1 else (buffer, "")
    else:
        safe, held = buffer, ""

    chunks: list[str] = []
    last = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(safe):
        end = match.end()
        sentence = safe[last:end].strip()
        if len(sentence) >= 2:
            chunks.append(sentence)
            last = end
    remaining = safe[last:] + held
    if flush:
        tail = remaining.strip()
        if tail:
            chunks.append(tail)
        remaining = ""
    return chunks, remaining


class _VoiceSentenceSpeaker:
    """Speak LLM output sentence-by-sentence AS it streams, instead of waiting.

    Fed token deltas via :meth:`feed`; completed sentences are queued and a
    consumer task plays them in order while the model keeps writing — so the
    Hana starts talking the first sentence while the rest is still generated.
    Cuts time-to-first-audio (the whole point of "streamer mode" on voice).
    """

    def __init__(self, runtime: "VoiceRuntime", config: VoiceRuntimeConfig, generation: int) -> None:
        self.rt = runtime
        self.config = config
        self.generation = generation
        self.buffer = ""
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.provider: Any = None
        self.spoke = False
        self.spoken_chars = 0
        self.capped = False
        self.started = False
        self.consumer: asyncio.Task[None] | None = None
        self.barge_thread = None
        self.barge_stop = None

    async def feed(self, token: str) -> None:
        if not self.rt._speech_is_current(self.generation):
            return
        self.buffer += token or ""
        chunks, self.buffer = extract_speakable_chunks(self.buffer)
        for chunk in chunks:
            await self._enqueue(chunk)

    async def _enqueue(self, sentence: str) -> None:
        if self.capped:
            return
        clean = sanitize_tts_text(strip_xml_for_tts(sentence))
        if not clean:
            return
        # Teto de custo: para de falar depois do limite (protege credito de TTS).
        cap = self.config.tts_max_chars
        if cap > 0 and self.spoken_chars + len(clean) > cap:
            clean = clamp_tts_text(clean, max(0, cap - self.spoken_chars))
            self.capped = True
            if not clean:
                return
        self.spoken_chars += len(clean)
        if not self.started:
            self._start()
        await self.queue.put(clean)

    def _start(self) -> None:
        self.started = True
        self.rt._set_state("speaking")
        audio_control.reset_stop_state()
        self.provider = self.rt._build_tts_provider(self.config)
        self.barge_thread, self.barge_stop = self.rt._start_barge_in_monitor(self.generation)
        self.consumer = asyncio.create_task(self._consume())
        self.rt._event(
            "speaking",
            "tts",
            "Gerando voz em streaming (LLM -> TTS frase a frase).",
            status="starting",
            metadata={"tts": False, "provider": self.config.tts_provider, "voice": self.config.tts_voice},
        )

    async def _consume(self) -> None:
        while True:
            sentence = await self.queue.get()
            try:
                if sentence is None:
                    return
                if not self.rt._speech_is_current(self.generation):
                    return
                if await self.rt._play_one(self.provider, self.config, sentence, self.generation):
                    self.spoke = True
            except Exception as exc:  # pragma: no cover - playback guard
                logger.debug("[VOICE RUNTIME] streaming sentence playback error: %s", exc)
            finally:
                self.queue.task_done()

    async def finish(self) -> None:
        chunks, self.buffer = extract_speakable_chunks(self.buffer, flush=True)
        for chunk in chunks:
            await self._enqueue(chunk)
        if not self.started:
            return
        await self.queue.put(None)
        if self.consumer is not None:
            await self.consumer
        if self.barge_stop is not None:
            self.barge_stop.set()
        if self.barge_thread is not None and self.barge_thread.is_alive():
            self.barge_thread.join(timeout=0.3)
        set_speaking(False)
        audio_control.reset_stop_state()
        if self.spoke and self.rt._speech_is_current(self.generation):
            self.rt._event(
                "speaking",
                "tts",
                "TTS finalizada (streaming). Runtime voltou para escuta.",
                status="stopped",
                metadata={"tts": False},
            )


class VoiceRuntime:
    """Backend voice loop that owns microphone capture, STT, LLM response and TTS playback."""

    def __init__(
        self,
        *,
        memory: MemoryStore,
        core: Any,
        stt_factory: Callable[[], GroqWhisperSTTProvider] | None = None,
        tts_factory: Callable[..., EdgeTTSProvider] | None = None,
        tts_player: EdgeTTSPlayer | None = None,
        text_runner: Callable[..., Any] | None = None,
    ) -> None:
        self.memory = memory
        self.core = core
        self.stt_factory = stt_factory or GroqWhisperSTTProvider
        self.tts_factory = tts_factory or EdgeTTSProvider
        self.tts_player = tts_player or EdgeTTSPlayer()
        self.text_runner = text_runner or run_text_turn
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = VoiceRuntimeStatus()
        self._config = VoiceRuntimeConfig.from_payload({})
        self._hotkey_handles: list[Any] = []
        self._hotkey_error_logged = False
        self._ptt_stop_event = threading.Event()
        self._ptt_thread: threading.Thread | None = None
        self._ptt_pressed = False
        self._last_stop_hotkey_at = 0.0
        self._last_interrupt_event_at = 0.0
        self._speech_generation = 0

    @staticmethod
    def _auto_listen_enabled(config: VoiceRuntimeConfig) -> bool:
        return bool(config.stt_enabled and config.stt_provider and config.vad_enabled and not config.ptt_enabled)

    def start(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        self.apply_config(config)
        should_auto_listen = self._auto_listen_enabled(self._config)
        if not should_auto_listen:
            self._stop_recording_thread()
            with self._lock:
                self._status.running = True
                self._status.state = "standby"
                self._status.error = ""
                self._status.started_at = self._status.started_at or time.time()
                self._status.updated_at = time.time()
            self._event(
                "listening",
                "microphone",
                "Runtime de voz em espera. VAD desligado ou PTT ativo; aguardando PTT/teste manual.",
                status="standby",
                metadata={"tts": False, "vad": self._config.vad_enabled, "ptt": self._config.ptt_enabled},
            )
            return self.status()

        with self._lock:
            self._status.error = ""
            self._status.updated_at = time.time()
            if self._thread and self._thread.is_alive():
                self._status.running = True
                self._status.state = "listening"
                return self._status.to_dict()

            self._stop_event.clear()
            self._status.running = True
            self._status.state = "listening"
            self._status.started_at = time.time()
            self._status.updated_at = self._status.started_at
            self._start_recording_thread_locked()
            return self._status.to_dict()

    def stop(self, reason: str = "user_request") -> dict[str, Any]:
        self._stop_event.set()
        self.stop_ptt_recording(reason=reason)
        self.interrupt(reason=reason, append_event=False, restart_capture=False)
        self._stop_recording_thread()
        with self._lock:
            self._status.running = False
            self._status.state = "idle"
            self._status.updated_at = time.time()
        self._event("system", "voice_runtime", "Voice runtime stopped.", status="stopped", metadata={"tts": False, "reason": reason})
        return self.status()

    def apply_config(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        previous = self._config
        previous_tts_enabled = previous.tts_enabled
        with self._lock:
            self._config = VoiceRuntimeConfig.from_payload(config)
            self._status.config = self._config.to_dict()
            self._status.updated_at = time.time()

        if previous_tts_enabled and not self._config.tts_enabled:
            audio_control.request_global_stop("tts_disabled")
            self.tts_player.stop()
            set_speaking(False)
            audio_control.reset_stop_state()
            self._event("speaking", "tts", "TTS desativada. Fala atual interrompida.", status="stopped", metadata={"tts": False, "reason": "tts_disabled"})

        capture_settings_changed = (
            previous.input_device_id != self._config.input_device_id
            or previous.vad_threshold != self._config.vad_threshold
            or previous.vad_mode != self._config.vad_mode
            or previous.vad_prob_threshold != self._config.vad_prob_threshold
            or previous.silence_timeout_ms != self._config.silence_timeout_ms
            or previous.vad_enabled != self._config.vad_enabled
            or previous.ptt_enabled != self._config.ptt_enabled
        )

        if self._status.running and not self._auto_listen_enabled(self._config):
            self._stop_recording_thread()
            self._set_state("standby")
        elif self._status.running and self._auto_listen_enabled(self._config):
            if capture_settings_changed and self._thread and self._thread.is_alive():
                self._stop_recording_thread()
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            with self._lock:
                self._status.state = "listening"
            with self._lock:
                self._start_recording_thread_locked()

        return self.status()

    def refresh_from_memory(self) -> dict[str, Any]:
        return self.apply_config(voice_config_with_connections(self.memory))

    def _start_recording_thread_locked(self) -> None:
        """Start the VAD capture thread while the runtime lock is held."""
        stop_event = threading.Event()
        self._stop_event = stop_event
        self._thread = threading.Thread(target=self._recording_main, args=(stop_event,), name="hana-voice-runtime", daemon=True)
        self._thread.start()

    def _ensure_auto_listening_thread(self, *, force_restart: bool = False) -> None:
        """Restart backend VAD capture if an interruption left the runtime armed without a thread."""
        with self._lock:
            should_auto_listen = self._status.running and self._auto_listen_enabled(self._config)
        if not should_auto_listen:
            return
        if force_restart:
            self._stop_recording_thread(join_timeout=0.15)
        with self._lock:
            self._status.state = "listening"
            self._status.updated_at = time.time()
            if self._thread and self._thread.is_alive():
                return
            self._start_recording_thread_locked()

    def _stop_recording_thread(self, *, join_timeout: float = 2.0) -> None:
        thread = self._thread
        stop_event = self._stop_event
        stop_event.set()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=join_timeout)
        if thread and thread.is_alive():
            with self._lock:
                if self._thread is thread:
                    self._thread = None
                    self._stop_event = threading.Event()
            return
        if not (thread and thread.is_alive()):
            self._thread = None
            self._stop_event = threading.Event()

    def configure_hotkeys(self, connections: dict[str, Any]) -> dict[str, Any]:
        for handle in self._hotkey_handles:
            try:
                import keyboard  # type: ignore[import-not-found]

                keyboard.unhook(handle)
            except Exception:
                pass
        self._hotkey_handles = []
        with self._lock:
            self._ptt_pressed = False

        try:
            import keyboard  # type: ignore[import-not-found]
        except Exception as exc:
            if not self._hotkey_error_logged:
                self._hotkey_error_logged = True
                self._event("error", "hotkey", f"Hotkeys globais indisponiveis: {exc}", status="failed", metadata={"tts": False})
            return self.status()

        try:
            if bool(connections.get("stopHotkey")):
                stop_key = str(connections.get("stopKey") or "F4")
                self._hotkey_handles.append(keyboard.add_hotkey(stop_key, self._handle_stop_hotkey, suppress=False))
            if bool(connections.get("ptt")) and bool(connections.get("stt")):
                ptt_key = str(connections.get("pttKey") or "F2")
                self._hotkey_handles.append(keyboard.on_press_key(ptt_key, lambda _event: self._handle_ptt_press(reason="ptt_hotkey"), suppress=False))
                self._hotkey_handles.append(keyboard.on_release_key(ptt_key, lambda _event: self._handle_ptt_release(reason="ptt_hotkey"), suppress=False))
        except Exception as exc:
            self._event("error", "hotkey", f"Falha ao registrar hotkey global: {exc}", status="failed", metadata={"tts": False})
        return self.status()

    def _handle_ptt_press(self, reason: str = "ptt_hotkey") -> dict[str, Any]:
        """Ignore repeated key-down events while one PTT capture is already active."""
        with self._lock:
            if self._ptt_pressed:
                return self._status.to_dict()
            self._ptt_pressed = True
        return self.start_ptt_recording(reason=reason)

    def _handle_ptt_release(self, reason: str = "ptt_hotkey") -> dict[str, Any]:
        """Release the PTT latch and close the active capture."""
        with self._lock:
            self._ptt_pressed = False
        return self.stop_ptt_recording(reason=reason)

    def _handle_stop_hotkey(self) -> dict[str, Any]:
        """Debounce repeated stop-key events emitted while a key is held."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_stop_hotkey_at < INTERRUPT_DEBOUNCE_SECONDS:
                return self._status.to_dict()
            self._last_stop_hotkey_at = now
        return self.interrupt(reason="stop_hotkey")

    def interrupt(self, reason: str = "user_request", *, append_event: bool = True, restart_capture: bool = True) -> dict[str, Any]:
        audio_control.request_global_stop(reason)
        self.tts_player.stop()
        set_speaking(False)
        with self._lock:
            self._speech_generation += 1
            if self._status.running:
                self._status.state = self._resting_state_locked()
            self._status.updated_at = time.time()
            should_emit_event = append_event and (time.monotonic() - self._last_interrupt_event_at >= INTERRUPT_DEBOUNCE_SECONDS)
            if should_emit_event:
                self._last_interrupt_event_at = time.monotonic()
        if should_emit_event:
            self._event("speaking", "tts", "TTS interrompida pelo usuario.", status="stopped", metadata={"tts": False, "reason": reason})
        audio_control.reset_stop_state()
        if restart_capture:
            self._ensure_auto_listening_thread(force_restart=True)
        return self.status()

    def _resting_state_locked(self) -> str:
        """Return the idle state for the current runtime mode while the lock is held."""
        if self._config.ptt_enabled or not self._config.vad_enabled:
            return "standby"
        return "listening"

    def start_ptt_recording(self, reason: str = "ptt") -> dict[str, Any]:
        self.refresh_from_memory()
        with self._lock:
            if not self._config.stt_provider:
                return self._status.to_dict()
            if not self._config.stt_enabled:
                return self._status.to_dict()
            if self._ptt_thread and self._ptt_thread.is_alive():
                return self._status.to_dict()
            self._stop_event.clear()
            self._ptt_stop_event.clear()
            self._status.running = True
            self._status.state = "recording"
            self._status.updated_at = time.time()
            self._ptt_thread = threading.Thread(target=self._ptt_recording_main, args=(reason,), name="hana-voice-ptt", daemon=True)
            self._ptt_thread.start()
            return self._status.to_dict()

    def stop_ptt_recording(self, reason: str = "ptt") -> dict[str, Any]:
        self._ptt_stop_event.set()
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status.to_dict()

    def _set_state(self, state: str, *, error: str = "") -> None:
        with self._lock:
            self._status.state = state
            self._status.error = error
            self._status.updated_at = time.time()

    def _event(
        self,
        kind: str,
        source: str,
        display_text: str,
        *,
        status: str = "",
        tool_name: str = "",
        speech_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        append_terminal_event(
            self.memory,
            {
                "kind": kind,
                "source": source,
                "displayText": display_text,
                "speechText": speech_text,
                "status": status,
                "toolName": tool_name,
                "metadata": metadata or {"tts": False},
            },
        )

    def _recording_main(self, stop_event: threading.Event | None = None) -> None:
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
        except Exception as exc:
            self._fail(f"sounddevice indisponivel: {exc}")
            return
        capture_stop_event = stop_event or self._stop_event

        device = resolve_input_device(self._config.input_device_id, self._config.input_device_label)
        pre_roll_blocks = max(1, int(PRE_ROLL_MS / BLOCK_MS))
        pre_roll: deque[bytes] = deque(maxlen=pre_roll_blocks)
        gate = RmsVoiceGate(
            threshold=self._config.vad_threshold,
            silence_timeout_ms=self._config.silence_timeout_ms,
            prob_threshold=self._config.vad_prob_threshold,
        )
        # Optional neural gate (Silero). None -> transparent RMS fallback.
        detector = None
        if self._config.vad_mode == "silero":
            from hana_agent_oss.modules.voice.vad_silero import SileroSpeechDetector, SileroVADConfig

            detector = SileroSpeechDetector.create(
                SileroVADConfig(prob_threshold=self._config.vad_prob_threshold)
            )
        vad_mode_active = "silero" if detector is not None else "rms"
        frames: list[bytes] = []
        diag_peak_rms = 0.0
        diag_peak_prob = 0.0
        diag_last_at = time.monotonic()

        self._event(
            "listening",
            "microphone",
            f"Backend ouvindo microfone (VAD: {vad_mode_active}). Aguardando voz real.",
            status="listening",
            metadata={"tts": False, "deviceId": self._config.input_device_id or "default", "model": self._config.stt_model, "vadMode": vad_mode_active},
        )

        try:
            with open_input_stream(device) as stream:
                while not capture_stop_event.is_set():
                    raw, _overflowed = stream.read(BLOCK_SIZE)
                    frame = bytes(raw)

                    if is_speaking():
                        gate.reset()
                        if detector is not None:
                            detector.reset()
                        frames = []
                        pre_roll.clear()
                        continue

                    rms = pcm16_rms(frame)
                    # Cheap RMS pre-filter: skip neural inference on dead silence
                    # (saves CPU on the weak machine). Run Silero whenever there is
                    # any audible energy, or while already recording.
                    speech_prob: float | None = None
                    if detector is not None and (gate.recording or rms >= SILERO_PREFILTER_RMS):
                        speech_prob = detector.probability(frame)
                    elif detector is not None:
                        detector.reset()
                    action = gate.push(rms, speech_prob=speech_prob)

                    # Live calibration: while idle, surface the peak rms/prob seen so
                    # the user can tune "Sensibilidade Silero" if speech never fires.
                    if action == "idle":
                        if rms > diag_peak_rms:
                            diag_peak_rms = rms
                        if speech_prob is not None and speech_prob > diag_peak_prob:
                            diag_peak_prob = speech_prob
                        now = time.monotonic()
                        if now - diag_last_at >= VAD_DIAG_INTERVAL_SECONDS:
                            if detector is not None and diag_peak_rms >= SILERO_PREFILTER_RMS:
                                self._event(
                                    "system",
                                    "stt",
                                    f"Calibragem VAD: pico rms={diag_peak_rms:.3f} prob={diag_peak_prob:.2f} "
                                    f"(precisa prob>={gate.prob_threshold:.2f} e rms>={gate.min_rms:.3f} pra gravar).",
                                    status="listening",
                                    tool_name="stt.vad",
                                    metadata={"tts": False, "peakRms": round(diag_peak_rms, 4), "peakProb": round(diag_peak_prob, 3)},
                                )
                            diag_last_at = now
                            diag_peak_rms = 0.0
                            diag_peak_prob = 0.0
                        pre_roll.append(frame)
                        continue
                    if action == "start":
                        frames = list(pre_roll) + [frame]
                        pre_roll.clear()
                        self._set_state("recording")
                        vad_desc = (
                            "Voz detectada na call (cabo virtual). Gravando fala do grupo."
                            if self._config.call_mode
                            else f"Voz detectada. Gravando do microfone ({self._config.input_device_label or 'dispositivo padrão'})."
                        )
                        self._event(
                            "user_speech",
                            "microphone",
                            vad_desc,
                            status="recording",
                            metadata={"tts": False, "rms": round(rms, 5), "model": self._config.stt_model},
                        )
                        continue
                    if gate.recording:
                        frames.append(frame)
                    if action in {"end", "discard"}:
                        utterance_frames = frames
                        stats = {"durationMs": gate.duration_ms, "activeMs": gate.active_ms, "maxRms": round(gate.max_rms, 5)}
                        frames = []
                        gate.reset()
                        if detector is not None:
                            detector.reset()
                        self._set_state("listening")
                        if action == "discard":
                            self._event(
                                "system",
                                "stt",
                                f"Audio descartado: pouca voz ativa (active={stats['activeMs']}ms rms={stats['maxRms']}).",
                                status="ignored",
                                tool_name="stt.vad",
                                metadata={"tts": False, **stats},
                            )
                            continue
                        asyncio.run(self._process_utterance(utterance_frames, stats))
        except Exception as exc:
            logger.exception("[VOICE RUNTIME] Microphone loop failed.")
            self._fail(f"Falha no runtime de voz: {exc}")
        finally:
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _ptt_recording_main(self, reason: str) -> None:
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
        except Exception as exc:
            self._fail(f"sounddevice indisponivel para PTT: {exc}")
            return

        device = resolve_input_device(self._config.input_device_id, self._config.input_device_label)
        frames: list[bytes] = []
        started_at = time.time()
        active_ms = 0
        max_rms = 0.0
        threshold = max(0.001, self._config.vad_threshold * PTT_THRESHOLD_SCALE)

        source_label = self._config.input_device_label or "dispositivo padrão"
        capture_desc = (
            f"Gravando fala da call (cabo virtual: {source_label})."
            if self._config.call_mode
            else f"Gravando do microfone ({source_label})."
        )
        self._event(
            "user_speech",
            "microphone",
            f"PTT pressionado. {capture_desc}",
            status="recording",
            metadata={"tts": False, "mode": "ptt", "reason": reason, "model": self._config.stt_model},
        )
        try:
            with open_input_stream(device) as stream:
                while not self._ptt_stop_event.is_set():
                    if is_speaking():
                        self.interrupt(reason="ptt_started", append_event=False, restart_capture=False)
                    raw, _overflowed = stream.read(BLOCK_SIZE)
                    frame = bytes(raw)
                    frames.append(frame)
                    rms = pcm16_rms(frame)
                    max_rms = max(max_rms, rms)
                    if rms >= threshold:
                        active_ms += BLOCK_MS
        except Exception as exc:
            logger.exception("[VOICE RUNTIME] PTT microphone loop failed.")
            self._fail(f"Falha no PTT de voz: {exc}")
            return

        duration_ms = max(int((time.time() - started_at) * 1000), len(frames) * BLOCK_MS)
        stats = {"durationMs": duration_ms, "activeMs": active_ms, "maxRms": round(max_rms, 5), "mode": "ptt"}
        self._set_state("standby" if self._config.ptt_enabled else "listening")
        if not ptt_audio_is_usable(stats, vad_threshold=self._config.vad_threshold):
            # Distinguish a DEAD/silent device (pure-zero capture over a real hold) from
            # the user simply speaking too quietly. rms~0 over a non-trivial duration means
            # the stream delivered silence — wrong/stale mic endpoint, not low volume.
            dead_capture = max_rms < 0.0005 and duration_ms >= 400
            if dead_capture:
                message = (
                    f"Microfone nao capturou nada (rms={stats['maxRms']} em {duration_ms}ms) — "
                    f"o device '{source_label}' veio mudo. Reabra o microfone no painel ou reconecte; "
                    "nao foi o Whisper, foi a captura."
                )
            else:
                message = f"Audio PTT descartado: sem voz util (active={active_ms}ms rms={stats['maxRms']})."
            self._event(
                "system",
                "stt",
                message,
                status="ignored",
                tool_name="stt.vad",
                metadata={"tts": False, "deadCapture": dead_capture, **stats},
            )
            return
        asyncio.run(self._process_utterance(frames, stats))

    async def _process_utterance(self, frames: list[bytes], stats: dict[str, Any]) -> None:
        self.refresh_from_memory()
        wav_audio = pcm16_wav_bytes(frames)
        self._set_state("transcribing")
        self._event(
            "processing",
            "stt",
            "Audio finalizado. Enviando para Groq Whisper.",
            status="transcribing",
            tool_name="stt.transcribe",
            metadata={"tts": False, "model": self._config.stt_model, **stats},
        )

        try:
            # Call mode = ouvindo a call (cabo virtual), várias pessoas podem falar.
            # O STT então NÃO assume que quem fala é a Operador (melhora a transcrição
            # de outras vozes e evita viés pro nome dela).
            stt_prompt = build_stt_prompt(group_call=self._config.call_mode)
            result = self.stt_factory().transcribe_bytes(
                wav_audio,
                filename="hana-runtime.wav",
                model=self._config.stt_model,
                language=self._config.stt_language,
                prompt=stt_prompt,
            )
        except STTConfigurationError as exc:
            self._fail(str(exc), source="stt", tool_name="stt.transcribe")
            return
        except Exception as exc:
            logger.exception("[VOICE RUNTIME] STT failed.")
            self._fail(f"Falha ao transcrever audio: {exc}", source="stt", tool_name="stt.transcribe")
            return

        if not result.text:
            self._set_state("listening")
            self._event(
                "system",
                "stt",
                "Groq Whisper nao retornou transcricao util.",
                status="filtered" if result.filtered else "empty",
                tool_name="stt.transcribe",
                metadata={"tts": False, "rawText": result.raw_text, "model": result.model, "language": result.language},
            )
            return

        with self._lock:
            self._status.turns += 1
            self._status.last_transcript = result.text

        self._event(
            "user_text",
            "stt",
            result.text,
            status="transcribed",
            metadata={"tts": False, "provider": result.provider, "model": result.model, "language": result.language},
        )
        self._set_state("thinking")
        self._event("assistant_thought", "agent_core", "Mensagem recebida. Gerando resposta em texto.", status="planning", metadata={"tts": False})

        # Streaming LLM -> TTS: fala frase a frase enquanto o modelo escreve, em vez
        # de esperar a resposta inteira. Só no OpenRouter (único com stream de token)
        # e com o toggle de streaming ligado; senão cai no caminho bloqueante.
        payload = self._voice_llm_payload(result.text)
        speaker: _VoiceSentenceSpeaker | None = None
        on_delta = None
        if self._config.tts_enabled and self._config.tts_streaming and payload.get("provider") in STREAMING_PROVIDERS:
            with self._lock:
                self._speech_generation += 1
                stream_generation = self._speech_generation
            speaker = _VoiceSentenceSpeaker(self, self._config, stream_generation)
            on_delta = speaker.feed

        try:
            assistant_payload = await self.text_runner(
                payload,
                core=self.core,
                memory=self.memory,
                on_delta=on_delta,
            )
        except Exception as exc:
            logger.exception("[VOICE RUNTIME] Text turn failed.")
            if speaker is not None:
                await speaker.finish()
            self._fail(f"Falha ao gerar resposta da Hana: {exc}", source="agent_core")
            return

        if speaker is not None:
            await speaker.finish()

        assistant_text = str(assistant_payload.get("text") or "").strip()
        with self._lock:
            self._status.last_response = assistant_text

        meta = assistant_payload.get("meta", {})
        if isinstance(meta, dict) and "grounding" in meta:
            grounding = meta["grounding"]
            queries = grounding.get("queries", [])
            sources = grounding.get("sources", [])
            if queries or sources:
                lines = ["🔍 GOOGLE NATIVE SEARCH GROUNDING"]
                if queries:
                    lines.append(f"Queries: {', '.join(f'\"{q}\"' for q in queries)}")
                if sources:
                    lines.append("\nFontes indexadas pelo Gemini:")
                    for s in sources:
                        title = s.get("title") or "Fonte"
                        uri = s.get("uri")
                        if uri:
                            lines.append(f"• {title}\n  {uri}")
                
                self._event(
                    "tool_result",
                    "google_search",
                    "\n".join(lines),
                    status="success",
                    tool_name="google_search",
                    metadata={"tts": False, "grounding": grounding}
                )

        if isinstance(meta, dict) and meta.get("media") and not meta.get("imageActions"):
            self._event(
                "tool_result",
                "image_generation",
                "Imagem gerada e aberta na tela.",
                status=str(assistant_payload.get("status", {}).get("stage", "success")),
                tool_name=str(assistant_payload.get("status", {}).get("tool_name") or "image.generate"),
                metadata={"tts": False, "media": meta.get("media")},
            )

        self._event(
            "assistant_text",
            "hana",
            assistant_text,
            status=str(assistant_payload.get("status", {}).get("stage", "success")),
            metadata={
                "tts": False,
                "provider": assistant_payload.get("meta", {}).get("provider"),
                "model": assistant_payload.get("meta", {}).get("model"),
            },
        )

        self.refresh_from_memory()
        # Se o streaming ja falou as frases, nao repete pelo caminho bloqueante.
        already_spoke = speaker is not None and speaker.spoke
        if assistant_text and self._config.tts_enabled and not already_spoke:
            await self._speak(assistant_text)
        self._set_state("standby" if self._config.ptt_enabled or not self._config.vad_enabled else "listening")

    def _start_barge_in_monitor(self, speech_generation: int):
        """Spawn a parallel mic watcher so the user can talk over the TTS to stop it.

        Returns (thread, stop_event) or (None, None) when barge-in is off or the
        runtime is not in auto-listen mode (PTT/STT off). Opens its own input
        stream (two streams on one device is fine on this hardware).
        """
        cfg = self._config
        if not cfg.barge_in_enabled or cfg.ptt_enabled or not cfg.vad_enabled or not cfg.stt_enabled:
            return None, None
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_barge_in_monitor,
            args=(stop_event, speech_generation),
            name="hana-barge-in",
            daemon=True,
        )
        thread.start()
        return thread, stop_event

    def _run_barge_in_monitor(self, stop_event: threading.Event, speech_generation: int) -> None:
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
        except Exception:
            return
        device = resolve_input_device(self._config.input_device_id, self._config.input_device_label)
        detector = None
        if self._config.vad_mode == "silero":
            from hana_agent_oss.modules.voice.vad_silero import SileroSpeechDetector, SileroVADConfig

            detector = SileroSpeechDetector.create(SileroVADConfig(prob_threshold=BARGE_IN_PROB))
        gate = BargeInGate()
        try:
            with open_input_stream(device) as stream:
                while not stop_event.is_set():
                    if not self._speech_is_current(speech_generation):
                        return
                    raw, _overflowed = stream.read(BLOCK_SIZE)
                    frame = bytes(raw)
                    rms = pcm16_rms(frame)
                    prob = None
                    if detector is not None and rms >= SILERO_PREFILTER_RMS:
                        prob = detector.probability(frame)
                    if gate.push(rms, prob):
                        self._event(
                            "user_speech",
                            "microphone",
                            "Barge-in: voz por cima da fala detectada. Interrompendo a Hana.",
                            status="recording",
                            tool_name="stt.bargein",
                            metadata={"tts": False, "rms": round(rms, 4)},
                        )
                        self.interrupt(reason="barge_in", restart_capture=False)
                        return
        except Exception as exc:  # pragma: no cover - audio device guard
            logger.debug("[VOICE RUNTIME] barge-in monitor error: %s", exc)

    async def _play_one(self, provider: Any, config: VoiceRuntimeConfig, text: str, generation: int) -> bool:
        """Synthesize and play a single sentence with the configured provider.

        Shared by the streaming speaker; mirrors the provider/streaming choices of
        :meth:`_speak` but for one chunk, honoring interrupts via ``generation``.
        """
        if not self._speech_is_current(generation):
            return False
        use_audio_stream = (
            config.tts_streaming
            and hasattr(provider, "stream_audio_chunks")
            and hasattr(self.tts_player, "play_stream")
        )
        if config.tts_provider == "edge" and hasattr(self.tts_player, "play_edge_streaming"):
            try:
                if await self.tts_player.play_edge_streaming(provider, text, volume=config.tts_volume):
                    return True
            except TTSConfigurationError:
                pass
        elif use_audio_stream:
            try:
                if await self.tts_player.play_stream(provider, text, volume=config.tts_volume):
                    return True
            except TTSConfigurationError:
                pass
        if not self._speech_is_current(generation):
            return False
        result = await provider.synthesize(text)
        if result.audio and self._speech_is_current(generation):
            await asyncio.to_thread(
                self.tts_player.play_blocking,
                result.audio,
                mime_type=result.mime_type,
                volume=config.tts_volume,
            )
            return True
        return False

    async def _speak(self, text: str) -> bool:
        self.refresh_from_memory()
        with self._lock:
            config = self._config
            self._speech_generation += 1
            speech_generation = self._speech_generation
        if not config.tts_enabled:
            return False
        # Segunda saída (espelho): roteia a voz pra um device extra (cabo virtual) além
        # do alto-falante. Resolvido por nome a cada fala pra sobreviver ao drift de
        # índice do Windows. Desligado => limpa o mirror (volta ao normal).
        if hasattr(self.tts_player, "set_mirror"):
            mirror_index = (
                resolve_output_device(config.second_output_device_id, config.second_output_device_label)
                if config.second_output_enabled
                else None
            )
            self.tts_player.set_mirror(mirror_index, config.second_output_enabled)
        if config.tts_provider not in {"edge", "gemini_tts", "google_cloud_tts", "cartesia", "azure", "minimax", "elevenlabs"}:
            self._event(
                "error",
                "tts",
                f"Provider TTS nao suportado no runtime: {config.tts_provider}.",
                status="failed",
                metadata={"tts": False, "provider": config.tts_provider},
            )
            return False

        clean_text = clamp_tts_text(sanitize_tts_text(text), config.tts_max_chars)
        if not clean_text:
            return False
        self._set_state("speaking")
        audio_control.reset_stop_state()
        provider_label = {
            "gemini_tts": "Gemini TTS",
            "google_cloud_tts": "Google Cloud TTS",
            "cartesia": "Cartesia Sonic",
            "azure": "Azure Neural TTS",
            "minimax": "Minimax TTS",
            "elevenlabs": "Elevenlabs TTS",
        }.get(config.tts_provider, "Edge TTS")
        self._event(
            "speaking",
            "tts",
            f"Gerando voz com {provider_label}.",
            status="starting",
            metadata={"tts": False, "provider": config.tts_provider, "voice": config.tts_voice},
        )
        spoke = False
        # Barge-in: monitora o mic em paralelo durante a fala (falar por cima corta).
        barge_thread, barge_stop = self._start_barge_in_monitor(speech_generation)
        try:
            provider = self._build_tts_provider(config)
            if config.tts_provider == "edge":
                self._event(
                    "assistant_speech",
                    "tts",
                    f"TTS Edge streaming: {config.tts_voice}",
                    status="speaking",
                    speech_text=clean_text,
                    metadata={
                        "tts": False,
                        "provider": "edge",
                        "voice": config.tts_voice,
                        "mimeType": "audio/mpeg",
                        "streaming": True,
                        "volume": config.tts_volume,
                    },
                )
                if hasattr(self.tts_player, "play_edge_streaming"):
                    try:
                        spoke = await self.tts_player.play_edge_streaming(
                            provider,
                            clean_text,
                            volume=config.tts_volume,
                        )
                    except TTSConfigurationError as exc:
                        self._event(
                            "error",
                            "tts",
                            f"Streaming Edge indisponivel; usando playback por arquivo: {exc}",
                            status="stream_fallback",
                            tool_name="tts.edge",
                            metadata={"tts": False},
                        )
                if not self._speech_is_current(speech_generation):
                    return False
                if not spoke:
                    result = await provider.synthesize(clean_text)
                    if not self._speech_is_current(speech_generation):
                        return False
                    if result.audio:
                        await asyncio.to_thread(
                            self.tts_player.play_blocking,
                            result.audio,
                            mime_type=result.mime_type,
                            volume=config.tts_volume,
                        )
                        spoke = True
            else:
                # Streaming genérico para providers que expõem stream_audio_chunks
                # (ex.: ElevenLabs /stream): começa a falar enquanto o resto gera,
                # cortando a latência. Fallback automático para playback por arquivo.
                streamed = False
                if (
                    config.tts_streaming
                    and hasattr(provider, "stream_audio_chunks")
                    and hasattr(self.tts_player, "play_stream")
                ):
                    self._event(
                        "assistant_speech",
                        "tts",
                        f"TTS {provider_label} streaming: {config.tts_voice}",
                        status="speaking",
                        speech_text=clean_text,
                        metadata={
                            "tts": False,
                            "provider": config.tts_provider,
                            "voice": config.tts_voice,
                            "mimeType": "audio/mpeg",
                            "streaming": True,
                            "volume": config.tts_volume,
                        },
                    )
                    try:
                        streamed = await self.tts_player.play_stream(
                            provider, clean_text, volume=config.tts_volume
                        )
                    except TTSConfigurationError as exc:
                        self._event(
                            "error",
                            "tts",
                            f"Streaming {provider_label} indisponivel; usando playback por arquivo: {exc}",
                            status="stream_fallback",
                            tool_name=f"tts.{config.tts_provider}",
                            metadata={"tts": False},
                        )
                        streamed = False
                    if not self._speech_is_current(speech_generation):
                        return False
                    if streamed:
                        spoke = True

                if not streamed:
                    if config.tts_provider == "google_cloud_tts":
                        fallback_reason = provider.streaming_fallback_reason()
                        if fallback_reason:
                            self._event(
                                "error",
                                "tts",
                                fallback_reason,
                                status="stream_fallback",
                                tool_name="tts.google_cloud",
                                metadata={"tts": False, "provider": config.tts_provider},
                            )
                    result = await provider.synthesize(clean_text)
                    if not self._speech_is_current(speech_generation):
                        return False
                    if not result.audio:
                        return False
                    self._event(
                        "assistant_speech",
                        "tts",
                        f"TTS {provider_label} falando: {result.voice}",
                        status="speaking",
                        speech_text=clean_text,
                        metadata={
                            "tts": False,
                            "provider": result.provider,
                            "model": config.tts_model or (DEFAULT_GEMINI_TTS_MODEL if config.tts_provider == "gemini_tts" else ""),
                            "voice": result.voice,
                            "rate": result.rate,
                            "pitch": result.pitch,
                            "bytes": len(result.audio),
                            "mimeType": result.mime_type,
                            "streaming": config.tts_streaming,
                            "volume": config.tts_volume,
                        },
                    )
                    await asyncio.to_thread(
                        self.tts_player.play_blocking,
                        result.audio,
                        mime_type=result.mime_type,
                        volume=config.tts_volume,
                    )
                    spoke = True
        except TTSConfigurationError as exc:
            self._fail(str(exc), source="tts", tool_name=f"tts.{config.tts_provider}")
        except Exception as exc:
            logger.exception("[VOICE RUNTIME] TTS playback failed.")
            self._fail(f"Falha no TTS {provider_label}: {exc}", source="tts", tool_name=f"tts.{config.tts_provider}")
        finally:
            if barge_stop is not None:
                barge_stop.set()
            if barge_thread is not None and barge_thread.is_alive():
                barge_thread.join(timeout=0.3)
            set_speaking(False)
            audio_control.reset_stop_state()
            speech_is_current = self._speech_is_current(speech_generation)
            if spoke and speech_is_current:
                self._event("speaking", "tts", "TTS finalizada. Runtime voltou para escuta.", status="stopped", metadata={"tts": False})
            if speech_is_current:
                with self._lock:
                    self._status.state = self._resting_state_locked() if self._status.running else "idle"
                    self._status.updated_at = time.time()
        return spoke

    def _build_tts_provider(self, config: VoiceRuntimeConfig):
        """Create the selected backend TTS provider from the latest voice config."""
        if config.tts_provider == "gemini_tts":
            return GeminiTTSProvider(
                model=config.tts_model or DEFAULT_GEMINI_TTS_MODEL,
                voice=config.tts_voice or DEFAULT_GEMINI_TTS_VOICE,
                language=config.tts_language or "pt-BR",
                style_prompt=config.tts_prompt,
            )
        if config.tts_provider == "google_cloud_tts":
            return GoogleCloudTTSProvider(
                voice=config.tts_voice or DEFAULT_GOOGLE_CLOUD_TTS_VOICE,
                language=config.tts_language or "pt-BR",
                speaking_rate=config.tts_speed,
                pitch=config.tts_pitch,
                streaming=config.tts_streaming,
            )
        if config.tts_provider == "cartesia":
            # Cartesia Sonic: ultra-low latency (target <100ms TTFA), high quality.
            # For authentic Brazilian Portuguese (no American accent bleed): use native pt-BR
            # voices from catalog (Luana, Ana Paula, Beatriz, Isabella etc.) + language="pt".
            # Get more at play.cartesia.ai filter Portuguese (Brazil) + Female.
            # Separate provider (CARTESIA_API_KEY), independent of LLM/STT.
            return CartesiaTTSProvider(
                voice=config.tts_voice or "",
                model=config.tts_model or DEFAULT_CARTESIA_MODEL,
                language=config.tts_language or "pt",
                speed=config.tts_speed,
            )
        if config.tts_provider == "azure":
            # Azure Neural TTS: excellent native pt-BR voices (Francisca, Thalita etc. are
            # top-tier authentic Brazilian, same family as Edge but full cloud control).
            # Very natural prosody for Brazilian Portuguese. Requires AZURE_SPEECH_KEY + AZURE_REGION.
            # Good quality/latency, many female voices.
            return AzureTTSProvider(
                voice=config.tts_voice or "pt-BR-FranciscaNeural",
                language=config.tts_language or "pt-BR",
                speed=config.tts_speed,
                pitch=config.tts_pitch,
            )
        if config.tts_provider == "minimax":
            # Minimax T2A (speech-2.8-turbo etc.): good quality multilingual TTS.
            # Strong Portuguese support with many female voices (Portuguese_ConfidentWoman etc.).
            # Use language_boost="Portuguese" for native pt-BR prosody.
            # Low latency on turbo models. Key: MINIMAX_API_KEY (Bearer).
            # Browse voices at https://www.minimax.io/audio/voices
            return MinimaxTTSProvider(
                voice=config.tts_voice or "Portuguese_ConfidentWoman",
                model=config.tts_model or "speech-2.8-turbo",
                speed=config.tts_speed,
                volume=1.0,
                pitch=0,
                language_boost="Portuguese",
            )
        if config.tts_provider == "elevenlabs":
            # Elevenlabs TTS: ultra-realistic, high quality multilingual TTS.
            # Excellent pt-BR support with many voices. Low latency on turbo models.
            # Requires ELEVENLABS_API_KEY.
            # Browse voices at https://elevenlabs.io/app/voice-library
            return ElevenlabsTTSProvider(
                voice=config.tts_voice or DEFAULT_ELEVENLABS_VOICE,
                model=config.tts_model or DEFAULT_ELEVENLABS_MODEL,
                language=config.tts_language or "pt",
                speed=config.tts_speed,
                stability=config.tts_stability,
                similarity_boost=config.tts_similarity,
                style=config.tts_style,
                speaker_boost=config.tts_speaker_boost,
            )
        return self.tts_factory(
            voice=config.tts_voice,
            speed=config.tts_speed,
            pitch=config.tts_pitch,
        )

    def _speech_is_current(self, generation: int) -> bool:
        """Return false when an interrupt invalidated the in-flight TTS operation."""
        with self._lock:
            return generation == self._speech_generation

    async def speak_text(self, text: str, *, require_enabled: bool = True) -> bool:
        self.refresh_from_memory()
        if require_enabled and not self._config.tts_enabled:
            return False
        return await self._speak(text)

    def _voice_llm_payload(self, text: str) -> dict[str, Any]:
        """Build the LLM payload for a voice turn with unified cross-channel history."""
        config = self.memory.get_setting("llm_config", dict(DEFAULT_LLM_CONFIG))
        if not isinstance(config, dict):
            config = dict(DEFAULT_LLM_CONFIG)
        agent_settings = self.memory.get_setting("agent_settings", {"safety_mode": "safe"})
        if not isinstance(agent_settings, dict):
            agent_settings = {"safety_mode": "safe"}
        provider = str(config.get("llmProvider") or "gemini_api").strip().lower()
        provider = {
            "open_router": "openrouter",
            "openrouters": "openrouter",
            "groq_cloud": "groq",
            "groqcloud": "groq",
            "glock": "groq",
        }.get(provider, provider)
        # Fetch real history from memory, merging both chat and voice channels
        unified = build_unified_history(self.memory, channel="voice")
        # Call mode: a fala transcrita pode ser de QUALQUER pessoa da call, não só da
        # Operador. Marcamos o turno atual para a Hana parar de tratar todo mundo como
        # a criadora (e o style hint vira o de grupo).
        turn_text = text
        if self._config.call_mode:
            turn_text = (
                "[ÁUDIO DA CALL — pode ser a Operador OU outra pessoa do grupo. "
                "NÃO assuma que é a Operador; trate como participante da call] " + text
            )
        return {
            "text": turn_text,
            "call_mode": self._config.call_mode,
            "provider": provider,
            "model": str(config.get("llmModel") or "structured-planner"),
            "temperature": config.get("llmTemperature", 0.7),
            "native_search_mode": "auto" if provider == "gemini_api" else "off",
            "safety_mode": str(agent_settings.get("safety_mode") or "safe"),
            "channel": "voice",
            "history": unified,
            "openrouter_routing": (
                config.get("openrouterRoutingByModel", {}).get(str(config.get("llmModel") or ""), {})
                if provider == "openrouter" and isinstance(config.get("openrouterRoutingByModel"), dict)
                else {}
            ),
        }

    def _fail(self, message: str, *, source: str = "voice_runtime", tool_name: str = "") -> None:
        with self._lock:
            self._status.running = False
            self._status.state = "error"
            self._status.error = message
            self._status.updated_at = time.time()
        self._stop_event.set()
        self._event("error", source, message, status="failed", tool_name=tool_name, metadata={"tts": False})


def voice_config_with_connections(memory: MemoryStore) -> dict[str, Any]:
    """Merge voice options and Connections toggles for runtime startup."""
    voice = memory.get_setting("voice_config", dict(DEFAULT_VOICE_CONFIG))
    if not isinstance(voice, dict):
        voice = dict(DEFAULT_VOICE_CONFIG)
    connections = memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
    if not isinstance(connections, dict):
        connections = dict(DEFAULT_CONNECTIONS)
    merged = dict(DEFAULT_VOICE_CONFIG)
    merged.update(voice)
    merged["sttEnabled"] = bool(connections.get("stt"))
    merged["ttsEnabled"] = bool(connections.get("tts"))
    merged["vadEnabled"] = bool(connections.get("vad", True))
    merged["pttEnabled"] = bool(connections.get("ptt"))
    return merged
