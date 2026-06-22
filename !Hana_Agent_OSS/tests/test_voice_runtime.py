from __future__ import annotations

import asyncio
import sys
import time

from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.voice import audio_control, runtime as voice_runtime_module
from hana_agent_oss.modules.voice.runtime import RmsVoiceGate, VoiceRuntime, VoiceRuntimeConfig, pcm16_wav_bytes, ptt_audio_is_usable
from hana_agent_oss.modules.voice.speech_state import set_speaking
from hana_agent_oss.modules.voice.stt_whisper import STTTranscriptionResult
from hana_agent_oss.modules.voice.tts_edge import EdgeTTSPlayer, EdgeTTSResult


def test_voice_runtime_config_preserves_elevenlabs_controls() -> None:
    """Terminal runtime config should retain all persisted ElevenLabs controls."""
    config = VoiceRuntimeConfig.from_payload(
        {
            "ttsProvider": "elevenlabs",
            "ttsModel": "eleven_v3",
            "ttsVoice": "custom-voice-id",
            "ttsLanguage": "pt-BR",
            "ttsVolume": 1.4,
            "ttsStability": 0.4,
            "ttsSimilarity": 0.8,
            "ttsStyle": 0.2,
            "ttsSpeakerBoost": False,
        }
    )

    assert config.tts_provider == "elevenlabs"
    assert config.tts_model == "eleven_v3"
    assert config.tts_voice == "custom-voice-id"
    assert config.tts_volume == 1.0
    assert config.tts_stability == 0.4
    assert config.tts_similarity == 0.8
    assert config.tts_style == 0.2
    assert config.tts_speaker_boost is False
    assert config.to_dict()["ttsSpeakerBoost"] is False


def test_voice_runtime_routes_elevenlabs_to_complete_audio_playback(tmp_path) -> None:
    """ElevenLabs must not be sent through the Edge-only chunk streaming contract."""
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    synthesized: list[str] = []
    played: list[tuple[bytes, str, float]] = []

    class _FakeElevenLabs:
        async def synthesize(self, text: str) -> EdgeTTSResult:
            synthesized.append(text)
            return EdgeTTSResult(
                provider="elevenlabs",
                voice="custom-voice-id",
                rate="1.00",
                pitch="0",
                volume="1.00",
                text=text,
                audio=b"elevenlabs-mp3",
                mime_type="audio/mpeg",
            )

    class _FakePlayer:
        def play_blocking(self, audio: bytes, *, mime_type: str = "audio/mpeg", volume: float = 1.0) -> None:
            played.append((audio, mime_type, volume))

        async def play_edge_streaming(self, provider, text: str, *, volume: float = 1.0) -> bool:
            raise AssertionError("ElevenLabs was incorrectly routed to Edge streaming.")

        def stop(self) -> None:
            return None

    memory.set_setting("connections_config", {"tts": True, "stt": False, "vad": True, "ptt": False})
    memory.set_setting(
        "voice_config",
        {
            "ttsProvider": "elevenlabs",
            "ttsModel": "eleven_turbo_v2_5",
            "ttsVoice": "custom-voice-id",
            "ttsVolume": 0.42,
        },
    )
    runtime = VoiceRuntime(memory=memory, core=object(), tts_player=_FakePlayer())  # type: ignore[arg-type]
    runtime._build_tts_provider = lambda config: _FakeElevenLabs()  # type: ignore[method-assign]

    assert asyncio.run(runtime._speak("Oi pelo ElevenLabs.")) is True
    assert synthesized == ["Oi pelo ElevenLabs."]
    assert played == [(b"elevenlabs-mp3", "audio/mpeg", 0.42)]
    speech_event = next(
        event
        for event in memory.recent_events(channel="terminal_agent", limit=10)
        if event["metadata"]["kind"] == "assistant_speech"
    )
    assert speech_event["metadata"]["provider"] == "elevenlabs"
    assert speech_event["metadata"]["volume"] == 0.42


def test_rms_voice_gate_ignores_silence_and_finishes_speech() -> None:
    gate = RmsVoiceGate(threshold=0.1, silence_timeout_ms=120, frame_ms=40, min_active_ms=80, min_recording_ms=120)

    assert [gate.push(0.0) for _ in range(3)] == ["idle", "idle", "idle"]
    assert gate.push(0.2) == "start"
    assert gate.push(0.2) == "recording"
    assert gate.push(0.0) == "recording"
    assert gate.push(0.0) == "recording"
    assert gate.push(0.0) == "end"


def test_rms_voice_gate_discards_short_noise() -> None:
    gate = RmsVoiceGate(threshold=0.1, silence_timeout_ms=80, frame_ms=40, min_active_ms=120, min_recording_ms=120)

    assert gate.push(0.2) == "start"
    assert gate.push(0.0) == "recording"
    assert gate.push(0.0) == "discard"


def test_ptt_gate_accepts_short_intentional_speech() -> None:
    assert ptt_audio_is_usable(
        {"durationMs": 128, "activeMs": 64, "maxRms": 0.04},
        vad_threshold=0.035,
    )


def test_ptt_gate_rejects_silence_or_tap_noise() -> None:
    assert not ptt_audio_is_usable(
        {"durationMs": 128, "activeMs": 0, "maxRms": 0.0},
        vad_threshold=0.035,
    )
    assert not ptt_audio_is_usable(
        {"durationMs": 64, "activeMs": 64, "maxRms": 0.04},
        vad_threshold=0.035,
    )


def test_voice_runtime_start_stop_status(monkeypatch, tmp_path) -> None:
    class _FakeStream:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self, block_size: int):
            time.sleep(0.01)
            return b"\x00\x00" * block_size, False

    class _FakeSoundDevice:
        RawInputStream = _FakeStream

    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSoundDevice())
    runtime = VoiceRuntime(memory=MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl"), core=object())

    status = runtime.start({"sttEnabled": True, "sttModel": "whisper-large-v3", "inputDeviceId": "sounddevice:2"})
    assert status["running"] is True
    stopped = runtime.stop(reason="test")
    assert stopped["running"] is False
    assert stopped["state"] == "idle"


def test_voice_runtime_processes_mocked_turn_and_tts(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    played: list[bytes] = []

    class _FakeStt:
        def transcribe_bytes(self, audio: bytes, *, filename: str, model: str | None, language: str | None, prompt: str | None):
            assert filename == "hana-runtime.wav"
            assert audio.startswith(b"RIFF")
            return STTTranscriptionResult(
                provider="groq_whisper",
                model=model or "whisper-large-v3",
                language=language or "pt",
                text="oi hana",
                raw_text="oi hana",
                filtered=False,
            )

    class _FakeTts:
        def __init__(self, *, voice: str, speed, pitch) -> None:
            self.voice = voice

        async def synthesize(self, text: str) -> EdgeTTSResult:
            return EdgeTTSResult(
                provider="edge",
                voice=self.voice,
                rate="+0%",
                pitch="+0Hz",
                volume="+0%",
                text=text,
                audio=b"mp3",
            )

    class _FakePlayer:
        def play_blocking(self, audio: bytes, *, mime_type: str = "audio/mpeg", volume: float = 1.0) -> None:
            played.append(audio)

        def stop(self) -> None:
            played.append(b"stop")

    async def _fake_text_runner(payload, *, core, memory, on_delta=None, on_activity=None):
        assert payload["text"] == "oi hana"
        assert payload.get("channel") == "voice"
        return {
            "ok": True,
            "text": "Oi, Operador.",
            "meta": {"provider": payload["provider"], "model": payload["model"]},
            "status": {"stage": "success"},
        }

    runtime = VoiceRuntime(
        memory=memory,
        core=object(),
        stt_factory=lambda: _FakeStt(),
        tts_factory=_FakeTts,
        tts_player=_FakePlayer(),  # type: ignore[arg-type]
        text_runner=_fake_text_runner,
    )
    memory.set_setting("connections_config", {"tts": True, "stt": True, "vad": True, "ptt": False})
    memory.set_setting("voice_config", {"ttsProvider": "edge", "ttsVoice": "pt-BR-FranciscaNeural"})
    runtime._config = VoiceRuntimeConfig.from_payload({"ttsEnabled": True, "ttsVoice": "pt-BR-FranciscaNeural", "sttEnabled": True})

    frames = [b"\x00\x20" * 1024, b"\x00\x10" * 1024]
    asyncio.run(runtime._process_utterance(frames, {"durationMs": 500, "activeMs": 320, "maxRms": 0.3}))

    assert played == [b"mp3"]
    events = memory.recent_events(channel="terminal_agent", limit=20)
    assert [event["metadata"]["kind"] for event in events] == [
        "processing",
        "user_text",
        "assistant_thought",
        "assistant_text",
        "speaking",
        "assistant_speech",
        "speaking",
    ]


def test_voice_runtime_apply_config_stops_tts_when_disabled(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    stopped: list[bytes] = []

    class _FakePlayer:
        def play_blocking(self, audio: bytes, *, mime_type: str = "audio/mpeg", volume: float = 1.0) -> None:
            pass

        def stop(self) -> None:
            stopped.append(b"stop")

    runtime = VoiceRuntime(memory=memory, core=object(), tts_player=_FakePlayer())  # type: ignore[arg-type]
    runtime.apply_config({"ttsEnabled": True})
    runtime.apply_config({"ttsEnabled": False})

    assert stopped == [b"stop"]
    events = memory.recent_events(channel="terminal_agent", limit=5)
    assert events[-1]["metadata"]["status"] == "stopped"


def test_pcm16_wav_bytes_wraps_frames() -> None:
    assert pcm16_wav_bytes([b"\x00\x00" * 4]).startswith(b"RIFF")
def test_stop_hotkey_debounce_only_interrupts_once(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    stopped: list[str] = []

    class _FakePlayer:
        def play_blocking(self, audio: bytes, *, mime_type: str = "audio/mpeg", volume: float = 1.0) -> None:
            pass

        def stop(self) -> None:
            stopped.append("stop")

    runtime = VoiceRuntime(memory=memory, core=object(), tts_player=_FakePlayer())  # type: ignore[arg-type]

    runtime._handle_stop_hotkey()
    runtime._handle_stop_hotkey()

    assert stopped == ["stop"]


def test_interrupt_rearms_listening_without_leaving_global_stop(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    stopped: list[str] = []
    restarted: list[str] = []

    class _FakePlayer:
        def play_blocking(self, audio: bytes, *, mime_type: str = "audio/mpeg", volume: float = 1.0) -> None:
            pass

        def stop(self) -> None:
            stopped.append("stop")

    runtime = VoiceRuntime(memory=memory, core=object(), tts_player=_FakePlayer())  # type: ignore[arg-type]
    runtime._config = VoiceRuntimeConfig.from_payload({"sttEnabled": True, "vadEnabled": True, "pttEnabled": False})
    runtime._status.running = True
    runtime._status.state = "speaking"

    def _fake_start_recording_thread_locked() -> None:
        restarted.append("start")

    runtime._start_recording_thread_locked = _fake_start_recording_thread_locked  # type: ignore[method-assign]
    set_speaking(False)
    runtime.interrupt(reason="test")

    assert stopped == ["stop"]
    assert restarted == ["start"]
    assert runtime.status()["state"] == "listening"
    assert audio_control.stop_requested() is False


def test_interrupt_replaces_stale_capture_thread(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    stopped_capture: list[str] = []
    restarted: list[str] = []

    class _FakePlayer:
        def play_blocking(self, audio: bytes, *, mime_type: str = "audio/mpeg", volume: float = 1.0) -> None:
            pass

        def stop(self) -> None:
            pass

    runtime = VoiceRuntime(memory=memory, core=object(), tts_player=_FakePlayer())  # type: ignore[arg-type]
    runtime._config = VoiceRuntimeConfig.from_payload({"sttEnabled": True, "vadEnabled": True, "pttEnabled": False})
    runtime._status.running = True

    class _AliveThread:
        def is_alive(self) -> bool:
            return True

    runtime._thread = _AliveThread()  # type: ignore[assignment]

    def _fake_stop_recording_thread(*, join_timeout: float = 2.0) -> None:
        stopped_capture.append(f"stop:{join_timeout}")
        runtime._thread = None

    runtime._stop_recording_thread = _fake_stop_recording_thread  # type: ignore[method-assign]
    runtime._start_recording_thread_locked = lambda: restarted.append("start")  # type: ignore[method-assign]

    runtime.interrupt(reason="stop_hotkey")

    assert stopped_capture == ["stop:0.15"]
    assert restarted == ["start"]
    assert runtime.status()["state"] == "listening"


def test_interrupt_can_skip_capture_restart_for_ptt_paths(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    restarts: list[str] = []

    class _FakePlayer:
        def play_blocking(self, audio: bytes, *, mime_type: str = "audio/mpeg", volume: float = 1.0) -> None:
            pass

        def stop(self) -> None:
            pass

    runtime = VoiceRuntime(memory=memory, core=object(), tts_player=_FakePlayer())  # type: ignore[arg-type]
    runtime._config = VoiceRuntimeConfig.from_payload({"sttEnabled": True, "vadEnabled": True, "pttEnabled": False})
    runtime._status.running = True
    runtime._start_recording_thread_locked = lambda: restarts.append("start")  # type: ignore[method-assign]

    runtime.interrupt(reason="ptt_started", append_event=False, restart_capture=False)

    assert restarts == []
    assert runtime.status()["state"] == "listening"


def test_start_ptt_clears_stale_runtime_stop_event(monkeypatch, tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    runtime = VoiceRuntime(memory=memory, core=object())
    memory.set_setting("connections_config", {"stt": True, "tts": True, "vad": False, "ptt": True})
    memory.set_setting("voice_config", {"sttProvider": "groq_whisper", "sttModel": "whisper-large-v3"})
    runtime._stop_event.set()
    monkeypatch.setattr(runtime, "_ptt_recording_main", lambda reason: None)

    status = runtime.start_ptt_recording(reason="test")
    runtime.stop_ptt_recording(reason="test")

    assert status["state"] == "recording"
    assert runtime._stop_event.is_set() is False


def test_interrupt_invalidates_in_flight_tts_generation(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    runtime = VoiceRuntime(memory=memory, core=object())

    runtime._speech_generation = 10
    assert runtime._speech_is_current(10)
    runtime.interrupt(reason="test", append_event=False, restart_capture=False)

    assert not runtime._speech_is_current(10)


def test_edge_player_stop_sets_stream_stop_event() -> None:
    player = EdgeTTSPlayer()

    assert not player._stream_stop_event.is_set()
    player.stop()

    assert player._stream_stop_event.is_set()


def test_ptt_hotkey_press_is_latched_until_release(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    runtime = VoiceRuntime(memory=memory, core=object())
    starts: list[str] = []
    stops: list[str] = []

    def _fake_start(reason: str = "ptt") -> dict:
        starts.append(reason)
        return {"ok": True}

    def _fake_stop(reason: str = "ptt") -> dict:
        stops.append(reason)
        return {"ok": True}

    runtime.start_ptt_recording = _fake_start  # type: ignore[method-assign]
    runtime.stop_ptt_recording = _fake_stop  # type: ignore[method-assign]

    runtime._handle_ptt_press(reason="ptt_hotkey")
    runtime._handle_ptt_press(reason="ptt_hotkey")
    runtime._handle_ptt_release(reason="ptt_hotkey")
    runtime._handle_ptt_press(reason="ptt_hotkey")

    assert starts == ["ptt_hotkey", "ptt_hotkey"]
    assert stops == ["ptt_hotkey"]


def test_voice_llm_payload_includes_unified_history(tmp_path) -> None:
    """_voice_llm_payload should return real history from memory, not an empty list."""
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    memory.append_event("user", "Me fala sobre Python", channel="control_center")
    memory.append_event("hana", "Python e uma linguagem incrivel.", channel="control_center")

    runtime = VoiceRuntime(memory=memory, core=object())
    payload = runtime._voice_llm_payload("o que eu perguntei?")

    assert payload["channel"] == "voice"
    assert isinstance(payload["history"], list)
    assert len(payload["history"]) >= 2
    assert any("Python" in msg["content"] for msg in payload["history"])


def test_voice_llm_payload_empty_memory_returns_empty_history(tmp_path) -> None:
    """_voice_llm_payload with no events should return an empty history list."""
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    runtime = VoiceRuntime(memory=memory, core=object())
    payload = runtime._voice_llm_payload("oi")

    assert payload["channel"] == "voice"
    assert payload["history"] == []
