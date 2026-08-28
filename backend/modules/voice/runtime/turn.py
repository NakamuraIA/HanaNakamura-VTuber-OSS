"""Processamento do áudio capturado no início de um turno de voz."""

from __future__ import annotations

from typing import Any

from backend.modules.voice.audio_helpers import pcm16_wav_bytes
from backend.persona import build_stt_prompt


def transcribe_frames(frames: list[bytes], *, config: Any, provider: Any) -> Any:
    """Converte PCM para WAV e chama o provider STT com o contrato do runtime."""
    return provider.transcribe_bytes(
        pcm16_wav_bytes(frames),
        filename="hana-runtime.wav",
        model=config.stt_model,
        language=config.stt_language,
        prompt=build_stt_prompt(group_call=config.call_mode),
    )


__all__ = ["transcribe_frames"]
