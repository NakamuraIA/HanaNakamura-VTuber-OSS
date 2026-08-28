"""Regressões do fallback e da métrica do streaming TTS."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Callable

from backend.api.routers.config import normalize_voice_config
from backend.modules.voice.runtime import VoiceRuntime, VoiceRuntimeConfig, voice_config_with_connections
from backend.modules.voice.runtime import coordinator
from backend.modules.voice.runtime.speaker import VoiceSentenceSpeaker
from backend.providers.tts.edge import TTSStreamingError
from backend.providers.tts.fishaudio import FishAudioTTSProvider


class _Provider:
    def __init__(self) -> None:
        self.synthesize_calls = 0

    async def synthesize(self, text: str) -> Any:
        self.synthesize_calls += 1
        return SimpleNamespace(audio=b"audio", mime_type="audio/mpeg")

    async def stream_audio_chunks(self, text: str):
        yield b"audio"


class _Memory:
    def __init__(self, voice_config: dict[str, Any]) -> None:
        self.voice_config = voice_config

    def get_setting(self, key: str, default: Any) -> Any:
        if key == "voice_config":
            return self.voice_config
        return default


class _Player:
    def __init__(self, *, audio_started: bool) -> None:
        self.audio_started = audio_started
        self.blocking_calls = 0

    async def play_stream(
        self,
        provider: Any,
        text: str,
        *,
        volume: float,
        on_first_audio: Callable[[], None],
    ) -> bool:
        if self.audio_started:
            on_first_audio()
        raise TTSStreamingError("falha simulada", audio_started=self.audio_started)

    def play_blocking(
        self,
        audio: bytes,
        *,
        mime_type: str,
        volume: float,
        on_first_audio: Callable[[], None],
    ) -> None:
        self.blocking_calls += 1
        on_first_audio()


class _SuccessfulPlayer:
    def __init__(self) -> None:
        self.streamed_texts: list[str] = []
        self.blocking_calls = 0

    async def play_stream(
        self,
        provider: Any,
        text: str,
        *,
        volume: float,
        on_first_audio: Callable[[], None],
    ) -> bool:
        self.streamed_texts.append(text)
        on_first_audio()
        return True

    def play_blocking(self, *args: Any, **kwargs: Any) -> None:
        self.blocking_calls += 1


class _InterruptingPlayer(_SuccessfulPlayer):
    def __init__(self) -> None:
        super().__init__()
        self.runtime: VoiceRuntime | None = None
        self.stop_calls = 0

    async def play_stream(
        self,
        provider: Any,
        text: str,
        *,
        volume: float,
        on_first_audio: Callable[[], None],
    ) -> bool:
        self.streamed_texts.append(text)
        on_first_audio()
        assert self.runtime is not None
        self.runtime.interrupt(append_event=False, restart_capture=False)
        return True

    def stop(self) -> None:
        self.stop_calls += 1


def _runtime(player: Any) -> VoiceRuntime:
    runtime = VoiceRuntime(memory=object(), core=object(), tts_player=player)
    runtime._active_latency_marks = {}
    return runtime


def _config() -> VoiceRuntimeConfig:
    return VoiceRuntimeConfig.from_payload(
        {"ttsEnabled": True, "ttsProvider": "edge", "ttsStreaming": True}
    )


def test_stop_hotkey_permite_novo_ptt_enquanto_turno_antigo_termina(monkeypatch) -> None:
    memory = _Memory(
        {
            "sttEnabled": True,
            "sttProvider": "groq_whisper",
            "pttEnabled": True,
        }
    )
    runtime = VoiceRuntime(memory=memory, core=object(), tts_player=_InterruptingPlayer())
    runtime._config = VoiceRuntimeConfig.from_payload(
        {"sttEnabled": True, "sttProvider": "groq_whisper", "pttEnabled": True}
    )
    monkeypatch.setattr(runtime, "refresh_from_memory", lambda: runtime.status())
    runtime._status.running = True
    runtime._status.state = "speaking"
    runtime._ptt_pressed = True
    runtime._ptt_thread = SimpleNamespace(is_alive=lambda: True)

    created_threads: list[Any] = []

    class _FakeThread:
        def __init__(self, **_kwargs: Any) -> None:
            self.started = False
            created_threads.append(self)

        def start(self) -> None:
            self.started = True

        def is_alive(self) -> bool:
            return self.started

    monkeypatch.setattr(coordinator.threading, "Thread", _FakeThread)

    runtime.interrupt(reason="stop_hotkey", append_event=False, restart_capture=False)
    runtime._handle_ptt_press()

    assert runtime._ptt_pressed is True
    assert runtime.status()["state"] == "recording"
    assert len(created_threads) == 1
    assert created_threads[0].started is True


def test_partial_stream_failure_does_not_repeat_full_sentence() -> None:
    player = _Player(audio_started=True)
    provider = _Provider()
    runtime = _runtime(player)

    spoke = asyncio.run(runtime._play_one(provider, _config(), "Uma frase.", 0))

    assert spoke is True
    assert provider.synthesize_calls == 0
    assert player.blocking_calls == 0
    assert "firstAudioStarted" in runtime._active_latency_marks


def test_stream_failure_before_audio_uses_safe_full_fallback() -> None:
    player = _Player(audio_started=False)
    provider = _Provider()
    runtime = _runtime(player)

    spoke = asyncio.run(runtime._play_one(provider, _config(), "Uma frase.", 0))

    assert spoke is True
    assert provider.synthesize_calls == 1
    assert player.blocking_calls == 1
    assert "firstAudioStarted" in runtime._active_latency_marks


def test_streaming_mode_migrates_legacy_boolean_and_preserves_explicit_mode() -> None:
    assert VoiceRuntimeConfig.from_payload({"ttsStreaming": True}).tts_streaming_mode == "sentences"
    assert VoiceRuntimeConfig.from_payload({"ttsStreaming": False}).tts_streaming_mode == "off"
    assert normalize_voice_config({"ttsStreaming": True})["ttsStreamingMode"] == "sentences"
    assert normalize_voice_config({"ttsStreaming": False})["ttsStreamingMode"] == "off"

    config = VoiceRuntimeConfig.from_payload({"ttsStreaming": False, "ttsStreamingMode": "audio"})

    assert config.tts_streaming_mode == "audio"
    assert config.tts_streaming is True
    assert normalize_voice_config({"ttsStreamingMode": "audio"})["ttsStreaming"] is True

    legacy_runtime_payload = voice_config_with_connections(_Memory({"ttsStreaming": True}))  # type: ignore[arg-type]
    assert legacy_runtime_payload["ttsStreamingMode"] == "sentences"


def test_audio_only_mode_streams_full_response_once() -> None:
    player = _SuccessfulPlayer()
    provider = _Provider()
    runtime = _runtime(player)
    runtime._config = VoiceRuntimeConfig.from_payload(
        {
            "ttsEnabled": True,
            "ttsProvider": "fishaudio",
            "ttsStreamingMode": "audio",
            "ttsMaxChars": 0,
        }
    )
    runtime.refresh_from_memory = lambda: {}  # type: ignore[method-assign]
    runtime._build_tts_provider = lambda _config: provider  # type: ignore[method-assign]
    runtime._event = lambda *args, **kwargs: None  # type: ignore[method-assign]

    spoke = asyncio.run(runtime._speak("Primeira frase. Segunda frase."))

    assert spoke is True
    assert player.streamed_texts == ["Primeira frase. Segunda frase."]
    assert provider.synthesize_calls == 0
    assert player.blocking_calls == 0


def test_sentence_mode_keeps_one_tts_stream_per_sentence() -> None:
    player = _SuccessfulPlayer()
    provider = _Provider()
    runtime = _runtime(player)
    config = VoiceRuntimeConfig.from_payload(
        {
            "ttsEnabled": True,
            "ttsProvider": "fishaudio",
            "ttsStreamingMode": "sentences",
            "ttsMaxChars": 0,
        }
    )
    runtime._build_tts_provider = lambda _config: provider  # type: ignore[method-assign]
    runtime._event = lambda *args, **kwargs: None  # type: ignore[method-assign]
    speaker = VoiceSentenceSpeaker(runtime, config, 0)

    async def run() -> None:
        await speaker.feed("Primeira frase. Segunda frase.")
        await speaker.finish()

    asyncio.run(run())

    assert player.streamed_texts == ["Primeira frase.", "Segunda frase."]


def test_audio_only_mode_honors_interruption_without_fallback() -> None:
    player = _InterruptingPlayer()
    provider = _Provider()
    runtime = _runtime(player)
    player.runtime = runtime
    runtime._config = VoiceRuntimeConfig.from_payload(
        {
            "ttsEnabled": True,
            "ttsProvider": "fishaudio",
            "ttsStreamingMode": "audio",
            "ttsMaxChars": 0,
        }
    )
    runtime.refresh_from_memory = lambda: {}  # type: ignore[method-assign]
    runtime._build_tts_provider = lambda _config: provider  # type: ignore[method-assign]
    runtime._event = lambda *args, **kwargs: None  # type: ignore[method-assign]

    spoke = asyncio.run(runtime._speak("Texto completo para interromper."))

    assert spoke is False
    assert player.stop_calls == 1
    assert provider.synthesize_calls == 0


def test_fish_websocket_sends_full_text_in_one_event() -> None:
    events = FishAudioTTSProvider(voice="voice-test")._ws_events("Primeira frase. Segunda frase.")
    text_events = [event for event in events if event["event"] == "text"]

    assert text_events == [{"event": "text", "text": "Primeira frase. Segunda frase."}]
