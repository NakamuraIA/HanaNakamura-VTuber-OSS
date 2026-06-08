from __future__ import annotations

import asyncio
import io
import logging
import math
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
from hana_agent_oss.api.services.chat import run_text_turn
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


@dataclass
class VoiceRuntimeConfig:
    """Runtime-ready voice config derived from persisted UI settings."""

    stt_provider: str = "groq_whisper"
    stt_model: str = "whisper-large-v3"
    stt_language: str = "pt"
    stt_enabled: bool = False
    input_device_id: str = ""
    input_device_label: str = ""
    vad_enabled: bool = True
    ptt_enabled: bool = False
    vad_threshold: float = 0.035
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

        return cls(
            stt_provider=str(source.get("sttProvider") or "groq_whisper"),
            stt_model=str(source.get("sttModel") or "whisper-large-v3"),
            stt_language=str(source.get("sttLanguage") or "pt"),
            stt_enabled=bool(source.get("sttEnabled", False)),
            input_device_id=str(source.get("inputDeviceId") or ""),
            input_device_label=str(source.get("inputDeviceLabel") or ""),
            vad_enabled=bool(source.get("vadEnabled", True)),
            ptt_enabled=bool(source.get("pttEnabled", False)),
            vad_threshold=max(0.001, vad_threshold),
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
            tts_streaming=bool(source.get("ttsStreaming", False)),
            tts_stability=max(0.0, min(1.0, tts_stability)),
            tts_similarity=max(0.0, min(1.0, tts_similarity)),
            tts_style=max(0.0, min(1.0, tts_style)),
            tts_speaker_boost=bool(source.get("ttsSpeakerBoost", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sttProvider": self.stt_provider,
            "sttModel": self.stt_model,
            "sttLanguage": self.stt_language,
            "sttEnabled": self.stt_enabled,
            "inputDeviceId": self.input_device_id,
            "inputDeviceLabel": self.input_device_label,
            "vadEnabled": self.vad_enabled,
            "pttEnabled": self.ptt_enabled,
            "vadThreshold": self.vad_threshold,
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
    """Small deterministic RMS gate used before expensive STT calls."""

    def __init__(
        self,
        *,
        threshold: float,
        silence_timeout_ms: int,
        frame_ms: int = BLOCK_MS,
        min_active_ms: int = MIN_ACTIVE_VOICE_MS,
        min_recording_ms: int = MIN_RECORDING_MS,
        max_recording_ms: int = MAX_RECORDING_MS,
    ) -> None:
        self.threshold = max(0.001, float(threshold))
        self.silence_timeout_ms = max(frame_ms, int(silence_timeout_ms))
        self.frame_ms = max(1, int(frame_ms))
        self.min_active_ms = int(min_active_ms)
        self.min_recording_ms = int(min_recording_ms)
        self.max_recording_ms = int(max_recording_ms)
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

    def push(self, rms: float) -> str:
        self.max_rms = max(self.max_rms, rms)
        is_active = rms >= self.threshold

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

        device = sounddevice_index(self._config.input_device_id)
        pre_roll_blocks = max(1, int(PRE_ROLL_MS / BLOCK_MS))
        pre_roll: deque[bytes] = deque(maxlen=pre_roll_blocks)
        gate = RmsVoiceGate(threshold=self._config.vad_threshold, silence_timeout_ms=self._config.silence_timeout_ms)
        frames: list[bytes] = []

        self._event(
            "listening",
            "microphone",
            "Backend ouvindo microfone. Aguardando voz real.",
            status="listening",
            metadata={"tts": False, "deviceId": self._config.input_device_id or "default", "model": self._config.stt_model},
        )

        try:
            with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, channels=CHANNELS, dtype="int16", device=device) as stream:
                while not capture_stop_event.is_set():
                    raw, _overflowed = stream.read(BLOCK_SIZE)
                    frame = bytes(raw)

                    if is_speaking():
                        gate.reset()
                        frames = []
                        pre_roll.clear()
                        continue

                    rms = pcm16_rms(frame)
                    action = gate.push(rms)

                    if action == "idle":
                        pre_roll.append(frame)
                        continue
                    if action == "start":
                        frames = list(pre_roll) + [frame]
                        pre_roll.clear()
                        self._set_state("recording")
                        self._event(
                            "user_speech",
                            "microphone",
                            "Voz detectada na call (cabo virtual). Gravando fala do grupo.",
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

        device = sounddevice_index(self._config.input_device_id)
        frames: list[bytes] = []
        started_at = time.time()
        active_ms = 0
        max_rms = 0.0
        threshold = max(0.001, self._config.vad_threshold * PTT_THRESHOLD_SCALE)

        self._event(
            "user_speech",
            "microphone",
            "PTT pressionado. Gravando fala da call (cabo virtual).",
            status="recording",
            metadata={"tts": False, "mode": "ptt", "reason": reason, "model": self._config.stt_model},
        )
        try:
            with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, channels=CHANNELS, dtype="int16", device=device) as stream:
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
            self._event(
                "system",
                "stt",
                f"Audio PTT descartado: sem voz util (active={active_ms}ms rms={stats['maxRms']}).",
                status="ignored",
                tool_name="stt.vad",
                metadata={"tts": False, **stats},
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
            # Use normal STT prompt (Nakamura is now awake and in command).
            # The bias helps Whisper transcribe her voice more accurately.
            stt_prompt = build_stt_prompt(group_call=False)
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

        try:
            assistant_payload = await self.text_runner(
                self._voice_llm_payload(result.text),
                core=self.core,
                memory=self.memory,
            )
        except Exception as exc:
            logger.exception("[VOICE RUNTIME] Text turn failed.")
            self._fail(f"Falha ao gerar resposta da Hana: {exc}", source="agent_core")
            return

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
        if assistant_text and self._config.tts_enabled:
            await self._speak(assistant_text)
        self._set_state("standby" if self._config.ptt_enabled or not self._config.vad_enabled else "listening")

    async def _speak(self, text: str) -> bool:
        self.refresh_from_memory()
        with self._lock:
            config = self._config
            self._speech_generation += 1
            speech_generation = self._speech_generation
        if not config.tts_enabled:
            return False
        if config.tts_provider not in {"edge", "gemini_tts", "google_cloud_tts", "cartesia", "azure", "minimax", "elevenlabs"}:
            self._event(
                "error",
                "tts",
                f"Provider TTS nao suportado no runtime: {config.tts_provider}.",
                status="failed",
                metadata={"tts": False, "provider": config.tts_provider},
            )
            return False

        clean_text = sanitize_tts_text(text)
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
        return {
            "text": text,
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
