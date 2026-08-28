"""Coordena captura, turno e fala no runtime de voz."""

from __future__ import annotations

import asyncio
import concurrent.futures
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
from uuid import uuid4

from backend.api.services.catalog import (
    DEFAULT_CONNECTIONS,
    DEFAULT_LLM_CONFIG,
    DEFAULT_VOICE_CONFIG,
    model_supports_vision,
    normalize_tts_streaming_mode,
    resolve_vision_target,
)
from backend.api.services.chat import STREAMING_PROVIDERS, run_text_turn
from backend.api.services.terminal_agent import append_terminal_event, publish_terminal_stream
from backend.api.services.unified_history import build_unified_history
from backend.memory.store import MemoryStore
from backend.modules.voice import audio_control
from backend.modules.voice.audio_helpers import (
    clamp_tts_text,
    open_input_stream,
    pcm16_rms,
    ptt_audio_is_usable,
    resolve_input_device,
    resolve_output_device,
    sounddevice_index,
)
from backend.modules.voice.speech_state import is_speaking, set_speaking
from backend.providers.stt.registry import STTConfigurationError
from backend.providers.stt import registry as stt_registry
from backend.providers.tts import registry as tts_registry
from backend.providers.tts.edge import EdgeTTSProvider, TTSConfigurationError
from backend.modules.voice.playback import EdgeTTSPlayer
from backend.modules.voice.runtime.capture import BargeInGate, RmsVoiceGate, capture_screen, vision_attachment
from backend.modules.voice.runtime.speaker import VoiceSentenceSpeaker
from backend.modules.voice.runtime.turn import transcribe_frames
from backend.modules.voice.tts_readable import sanitize_tts_text

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
    tts_streaming_mode: str = "off"
    tts_stability: float = 0.5
    tts_similarity: float = 0.75
    tts_style: float = 0.0
    tts_speaker_boost: bool = True
    tts_max_chars: int = DEFAULT_TTS_MAX_CHARS

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "VoiceRuntimeConfig":
        raw_payload = payload or {}
        source = dict(DEFAULT_VOICE_CONFIG)
        source.update(raw_payload)
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
        tts_streaming_mode = normalize_tts_streaming_mode(
            raw_payload.get("ttsStreamingMode"),
            legacy_streaming=bool(raw_payload.get("ttsStreaming", DEFAULT_VOICE_CONFIG["ttsStreaming"])),
        )

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
            tts_streaming=tts_streaming_mode != "off",
            tts_streaming_mode=tts_streaming_mode,
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
            "ttsStreamingMode": self.tts_streaming_mode,
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


class VoiceRuntime:
    """Backend voice loop that owns microphone capture, STT, LLM response and TTS playback."""

    def __init__(
        self,
        *,
        memory: MemoryStore,
        core: Any,
        stt_factory: Callable[[], Any] | None = None,
        tts_factory: Callable[..., EdgeTTSProvider] | None = None,
        tts_player: EdgeTTSPlayer | None = None,
        text_runner: Callable[..., Any] | None = None,
    ) -> None:
        self.memory = memory
        self.core = core
        self.stt_factory = stt_factory
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
        self._ptt_turn_id = 0
        self._vision_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hana-vision")
        self._pending_vision: dict[int, concurrent.futures.Future[dict[str, Any]]] = {}
        self._ptt_started_at: dict[int, float] = {}
        self._active_latency_marks: dict[str, float] | None = None

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
        if reason in {"user_request", "stop_hotkey", "runtime_stop", "tts_disabled"}:
            with self._lock:
                pending_turns = list(self._pending_vision)
            for turn_id in pending_turns:
                self._discard_early_vision(turn_id)
        audio_control.request_global_stop(reason)
        self.tts_player.stop()
        set_speaking(False)
        with self._lock:
            if reason == "stop_hotkey":
                self._ptt_pressed = False
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
            if (
                self._ptt_thread
                and self._ptt_thread.is_alive()
                and self._status.state == "recording"
            ):
                return self._status.to_dict()
            self._stop_event.clear()
            self._ptt_stop_event.clear()
            self._status.running = True
            self._status.state = "recording"
            self._status.updated_at = time.time()
            self._ptt_turn_id += 1
            turn_id = self._ptt_turn_id
            self._ptt_started_at[turn_id] = time.monotonic()
            self._start_early_vision_locked(turn_id)
            self._ptt_thread = threading.Thread(
                target=self._ptt_recording_main,
                args=(reason, turn_id),
                name="hana-voice-ptt",
                daemon=True,
            )
            self._ptt_thread.start()
            return self._status.to_dict()

    def _start_early_vision_locked(self, turn_id: int) -> None:
        """Inicia a captura no F2 se o modelo principal ou fallback aceitar imagem."""
        connections = self.memory.get_setting("connections_config", dict(DEFAULT_CONNECTIONS))
        if not isinstance(connections, dict) or not connections.get("visao"):
            return
        config = self.memory.get_setting("llm_config", dict(DEFAULT_LLM_CONFIG))
        if not isinstance(config, dict):
            config = dict(DEFAULT_LLM_CONFIG)
        provider = str(config.get("llmProvider") or "gemini_api").strip().lower()
        model = str(config.get("llmModel") or "").strip()
        vision_provider, vision_model = resolve_vision_target(config, self.memory)
        if not (
            (model and model_supports_vision(provider, model, self.memory))
            or (vision_model and model_supports_vision(vision_provider, vision_model, self.memory))
        ):
            return
        self._pending_vision[turn_id] = self._vision_executor.submit(capture_screen, self.memory)

    def _discard_early_vision(self, turn_id: int) -> None:
        with self._lock:
            future = self._pending_vision.pop(turn_id, None)
            self._ptt_started_at.pop(turn_id, None)
        if future is not None:
            future.cancel()

    async def _consume_early_vision(self, turn_id: int) -> tuple[dict[str, Any] | None, dict[str, float]]:
        with self._lock:
            future = self._pending_vision.pop(turn_id, None)
            started_at = self._ptt_started_at.pop(turn_id, None)
        marks = {"pttStarted": started_at} if started_at is not None else {}
        if future is None:
            return None, marks
        try:
            result = await asyncio.wrap_future(future)
            marks["captureFinished"] = time.monotonic()
            attachment = vision_attachment(result)
            if attachment is None:
                self._event(
                    "system",
                    "vision",
                    f"Captura antecipada falhou: {result.get('erro') or 'sem imagem'}.",
                    status="failed",
                    tool_name="screen_capture",
                    metadata={"tts": False, "turnId": turn_id},
                )
            else:
                self._event(
                    "tool_result",
                    "vision",
                    "Captura iniciada no F2 ficou pronta para este turno.",
                    status="success",
                    tool_name="screen_capture",
                    metadata={
                        "tts": False,
                        "turnId": turn_id,
                        "mimeType": attachment["type"],
                        "profile": result.get("profile"),
                        "width": result.get("width"),
                        "height": result.get("height"),
                    },
                )
            return attachment, marks
        except Exception as exc:
            marks["captureFinished"] = time.monotonic()
            self._event(
                "system",
                "vision",
                f"Captura antecipada falhou: {exc}.",
                status="failed",
                tool_name="screen_capture",
                metadata={"tts": False, "turnId": turn_id},
            )
            return None, marks

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
            from backend.modules.voice.vad_silero import SileroSpeechDetector, SileroVADConfig

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

    def _ptt_recording_main(self, reason: str, turn_id: int) -> None:
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
            self._discard_early_vision(turn_id)
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
            self._discard_early_vision(turn_id)
            return
        stats["visionTurnId"] = turn_id
        asyncio.run(self._process_utterance(frames, stats))

    async def _process_utterance(self, frames: list[bytes], stats: dict[str, Any]) -> None:
        turn_id = int(stats.get("visionTurnId") or 0)
        self.refresh_from_memory()
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
            stt_client = self.stt_factory() if self.stt_factory is not None else self._build_stt_provider(self._config)
            result = transcribe_frames(frames, config=self._config, provider=stt_client)
        except STTConfigurationError as exc:
            if turn_id:
                self._discard_early_vision(turn_id)
            self._fail(str(exc), source="stt", tool_name="stt.transcribe")
            return
        except Exception as exc:
            if turn_id:
                self._discard_early_vision(turn_id)
            logger.exception("[VOICE RUNTIME] STT failed.")
            self._fail(f"Falha ao transcrever audio: {exc}", source="stt", tool_name="stt.transcribe")
            return

        if not result.text:
            if turn_id:
                self._discard_early_vision(turn_id)
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

        early_attachment, latency_marks = await self._consume_early_vision(turn_id) if turn_id else (None, {})
        latency_marks["sttFinished"] = time.monotonic()
        self._active_latency_marks = latency_marks

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
        if early_attachment is not None:
            payload["attachments"] = [early_attachment]
        if "captureFinished" in latency_marks:
            payload["vision_pre_captured"] = True
        latency_marks["llmStarted"] = time.monotonic()
        speaker: VoiceSentenceSpeaker | None = None
        on_delta = None
        stream_id = uuid4().hex
        if (
            self._config.tts_enabled
            and self._config.tts_streaming_mode == "sentences"
            and payload.get("provider") in STREAMING_PROVIDERS
        ):
            with self._lock:
                self._speech_generation += 1
                stream_generation = self._speech_generation
            speaker = VoiceSentenceSpeaker(self, self._config, stream_generation)

        if payload.get("provider") in STREAMING_PROVIDERS:
            async def on_delta(token: str) -> None:
                latency_marks.setdefault("firstToken", time.monotonic())
                publish_terminal_stream({"type": "delta", "streamId": stream_id, "delta": token})
                if speaker is not None:
                    await speaker.feed(token)

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
            publish_terminal_stream({"type": "done", "streamId": stream_id})
            self._fail(f"Falha ao gerar resposta da Hana: {exc}", source="agent_core")
            self._active_latency_marks = None
            return

        if speaker is not None:
            await speaker.finish()

        assistant_text = str(assistant_payload.get("text") or "").strip()
        latency_marks["responseAvailable"] = time.monotonic()
        latency_marks["responseFinished"] = time.monotonic()
        with self._lock:
            self._status.last_response = assistant_text

        meta = assistant_payload.get("meta", {})
        if isinstance(meta, dict) and "grounding" in meta:
            grounding = meta["grounding"]
            queries = grounding.get("queries", [])
            sources = grounding.get("sources", [])
            if queries or sources:
                is_gemini_native = grounding.get("source") == "gemini_native"
                title_line = "🔍 GOOGLE NATIVE SEARCH GROUNDING" if is_gemini_native else "🔍 PESQUISA WEB"
                lines = [title_line]
                if queries:
                    lines.append(f"Queries: {', '.join(f'\"{q}\"' for q in queries)}")
                if sources:
                    lines.append(f"\nFontes indexadas{' pelo Gemini' if is_gemini_native else ''}:")
                    for s in sources:
                        title = s.get("title") or "Fonte"
                        uri = s.get("uri")
                        if uri:
                            lines.append(f"• {title}\n  {uri}")

                tool_name = "google_search" if is_gemini_native else "web_search"
                self._event(
                    "tool_result",
                    tool_name,
                    "\n".join(lines),
                    status="success",
                    tool_name=tool_name,
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
                "streamId": stream_id,
            },
        )
        publish_terminal_stream({"type": "done", "streamId": stream_id})

        self.refresh_from_memory()
        # Se o streaming ja falou as frases, nao repete pelo caminho bloqueante.
        already_spoke = speaker is not None and speaker.spoke
        if assistant_text and self._config.tts_enabled and not already_spoke:
            await self._speak(assistant_text)
        self._emit_latency_report(latency_marks, had_vision=early_attachment is not None)
        self._active_latency_marks = None
        self._set_state("standby" if self._config.ptt_enabled or not self._config.vad_enabled else "listening")

    def _mark_voice_latency(self, name: str) -> None:
        if self._active_latency_marks is not None:
            self._active_latency_marks.setdefault(name, time.monotonic())

    def _emit_latency_report(self, marks: dict[str, float], *, had_vision: bool) -> None:
        start = marks.get("pttStarted")
        if start is None:
            return
        durations = {
            key: round((value - start) * 1000)
            for key, value in marks.items()
            if key != "pttStarted"
        }
        self._event(
            "system",
            "latency",
            "Latência do turno medida.",
            status="success",
            metadata={"tts": False, "vision": had_vision, "milliseconds": durations},
        )

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
            from backend.modules.voice.vad_silero import SileroSpeechDetector, SileroVADConfig

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
        if use_audio_stream:
            try:
                if await self.tts_player.play_stream(
                    provider,
                    text,
                    volume=config.tts_volume,
                    on_first_audio=lambda: self._mark_voice_latency("firstAudioStarted"),
                ):
                    return True
            except TTSConfigurationError as exc:
                if getattr(exc, "audio_started", False):
                    logger.warning(
                        "[VOICE RUNTIME] streaming TTS falhou depois de iniciar; "
                        "fallback completo ignorado para não repetir áudio: %s",
                        exc,
                    )
                    return True
        if not self._speech_is_current(generation):
            return False
        result = await provider.synthesize(text)
        if result.audio and self._speech_is_current(generation):
            await asyncio.to_thread(
                self.tts_player.play_blocking,
                result.audio,
                mime_type=result.mime_type,
                volume=config.tts_volume,
                on_first_audio=lambda: self._mark_voice_latency("firstAudioStarted"),
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
        if config.tts_provider not in tts_registry.SUPPORTED_TTS_PROVIDERS:
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
        provider_label = tts_registry.provider_label(config.tts_provider)
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
            # Edge sempre tenta streaming (e local/gratis, sem motivo pra desligar);
            # os outros quando o modo escolhido permite áudio progressivo. Mecanica de
            # playback é a mesma pra todos — play_stream() só existe pra generalizar
            # o antigo play_edge_streaming() pra qualquer provider com stream_audio_chunks.
            should_try_streaming = (
                config.tts_provider == "edge" or config.tts_streaming
            ) and hasattr(provider, "stream_audio_chunks") and hasattr(self.tts_player, "play_stream")

            streamed = False
            if should_try_streaming:
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
                        provider,
                        clean_text,
                        volume=config.tts_volume,
                        on_first_audio=lambda: self._mark_voice_latency("firstAudioStarted"),
                    )
                except TTSConfigurationError as exc:
                    if getattr(exc, "audio_started", False):
                        self._event(
                            "error",
                            "tts",
                            f"Streaming {provider_label} interrompido depois de iniciar; áudio não repetido.",
                            status="stream_partial",
                            tool_name=f"tts.{config.tts_provider}",
                            metadata={"tts": False},
                        )
                        streamed = True
                    else:
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

            if not spoke:
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
                        "model": config.tts_model or "",
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
                    on_first_audio=lambda: self._mark_voice_latency("firstAudioStarted"),
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
        if config.tts_provider not in tts_registry.SUPPORTED_TTS_PROVIDERS:
            return self.tts_factory(voice=config.tts_voice, speed=config.tts_speed, pitch=config.tts_pitch)
        return tts_registry.build_tts_provider(
            config.tts_provider,
            voice=config.tts_voice,
            model=config.tts_model,
            language=config.tts_language,
            speed=config.tts_speed,
            pitch=config.tts_pitch,
            stability=config.tts_stability,
            similarity=config.tts_similarity,
            style=config.tts_style,
            speaker_boost=config.tts_speaker_boost,
        )

    def _build_stt_provider(self, config: VoiceRuntimeConfig):
        """Create the selected backend STT provider from the latest voice config.

        Model/language/prompt vao por chamada em transcribe_bytes, nao aqui —
        ver docstring de stt_registry.build_stt_provider.
        """
        return stt_registry.build_stt_provider(config.stt_provider or stt_registry.DEFAULT_STT_PROVIDER)

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
        # Nakamura. Marcamos o turno atual para a Hana parar de tratar todo mundo como
        # a criadora (e o style hint vira o de grupo).
        turn_text = text
        if self._config.call_mode:
            turn_text = (
                "[ÁUDIO DA CALL — pode ser a Nakamura OU outra pessoa do grupo. "
                "NÃO assuma que é a Nakamura; trate como participante da call] " + text
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
    streaming_mode = normalize_tts_streaming_mode(
        voice.get("ttsStreamingMode"),
        legacy_streaming=bool(voice.get("ttsStreaming", False)),
    )
    merged["ttsStreamingMode"] = streaming_mode
    merged["ttsStreaming"] = streaming_mode != "off"
    merged["sttEnabled"] = bool(connections.get("stt"))
    merged["ttsEnabled"] = bool(connections.get("tts"))
    merged["vadEnabled"] = bool(connections.get("vad", True))
    merged["pttEnabled"] = bool(connections.get("ptt"))
    return merged
