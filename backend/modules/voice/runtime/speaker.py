"""Fila de frases que liga streaming da LLM à reprodução TTS."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from backend.modules.voice import audio_control
from backend.modules.voice.audio_helpers import clamp_tts_text, extract_speakable_chunks, strip_xml_for_tts
from backend.modules.voice.speech_state import set_speaking
from backend.modules.voice.tts_readable import sanitize_tts_text

if TYPE_CHECKING:
    from backend.modules.voice.runtime.coordinator import VoiceRuntime, VoiceRuntimeConfig

logger = logging.getLogger(__name__)


class VoiceSentenceSpeaker:
    """Fala frases completas enquanto o modelo continua gerando o restante."""

    def __init__(self, runtime: "VoiceRuntime", config: "VoiceRuntimeConfig", generation: int) -> None:
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
                if sentence is None or not self.rt._speech_is_current(self.generation):
                    return
                if await self.rt._play_one(self.provider, self.config, sentence, self.generation):
                    self.spoke = True
            except Exception as exc:  # pragma: no cover - depende do hardware
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


__all__ = ["VoiceSentenceSpeaker"]
