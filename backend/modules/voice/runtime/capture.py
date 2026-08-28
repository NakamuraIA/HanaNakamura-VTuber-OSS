"""Detecção de início, silêncio e interrupção durante a captura de voz."""

from __future__ import annotations

from typing import Any

from backend.modules.voice.audio_helpers import (
    BLOCK_MS,
)
from backend.modules.vision.periodic_vision import VisaoNyra

MIN_ACTIVE_VOICE_MS = 240
MIN_RECORDING_MS = 450
MAX_RECORDING_MS = 18_000
BARGE_IN_PROB = 0.70
BARGE_IN_MIN_RMS = 0.050
BARGE_IN_MIN_SPEECH_MS = 400


class RmsVoiceGate:
    """Controla início e fim da gravação antes da chamada cara de STT."""

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
    """Exige fala sustentada para interromper a TTS sem reagir ao próprio eco."""

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
        self.active_ms = self.active_ms + self.frame_ms if is_active else max(0, self.active_ms - self.frame_ms)
        return self.active_ms >= self.min_speech_ms


def capture_screen(memory: Any) -> dict[str, Any]:
    """Captura a tela para um turno efêmero; não grava conteúdo na memória."""
    return VisaoNyra(memory=memory).capturar()


def vision_attachment(result: dict[str, Any]) -> dict[str, Any] | None:
    """Converte uma captura bem-sucedida no contrato de anexo do chat."""
    if not result.get("sucesso") or not result.get("b64"):
        return None
    extension = str(result.get("extension") or ".png")
    return {
        "name": f"screen_capture{extension}",
        "type": str(result.get("mime_type") or "image/png"),
        "data": result["b64"],
        "path": result.get("caminho"),
    }


__all__ = ["BargeInGate", "RmsVoiceGate", "capture_screen", "vision_attachment"]
