from __future__ import annotations

from fastapi.testclient import TestClient

from hana_agent_oss.api import routers
from hana_agent_oss.api.server import create_app
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.voice.stt_whisper import (
    DEFAULT_STT_MODEL,
    GroqWhisperSTTProvider,
    STTTranscriptionResult,
    is_ghost_stt_phrase,
    normalize_stt_prompt,
    normalize_stt_language,
)


class _FakeTranscriptions:
    def __init__(self, response: str) -> None:
        self.response = response
        self.last_call = {}

    def create(self, **kwargs):
        self.last_call = kwargs
        return self.response


class _FakeAudio:
    def __init__(self, response: str) -> None:
        self.transcriptions = _FakeTranscriptions(response)


class _FakeGroqClient:
    def __init__(self, response: str) -> None:
        self.audio = _FakeAudio(response)


def test_groq_whisper_transcribes_with_defaults_and_corrections() -> None:
    client = _FakeGroqClient("hannah abriu o arquivo")
    provider = GroqWhisperSTTProvider(api_key="test", client=client)

    result = provider.transcribe_bytes(b"0" * 1024, filename="fala.wav")

    assert result.provider == "groq_whisper"
    assert result.model == DEFAULT_STT_MODEL
    assert result.language == "pt"
    assert result.raw_text == "hannah abriu o arquivo"
    assert result.text == "Hana abriu o arquivo"
    assert result.filtered is False
    assert client.audio.transcriptions.last_call["file"][0] == "fala.wav"
    assert client.audio.transcriptions.last_call["response_format"] == "text"
    assert client.audio.transcriptions.last_call["temperature"] == 0.0


def test_groq_whisper_filters_ghost_phrases_and_too_short_noise() -> None:
    assert is_ghost_stt_phrase("Legendas por Sonia Ruberti.")

    ghost_client = _FakeGroqClient("Legendas por Sonia Ruberti.")
    ghost_provider = GroqWhisperSTTProvider(api_key="test", client=ghost_client)
    assert ghost_provider.transcribe_bytes(b"0" * 1024).text == ""

    noise_client = _FakeGroqClient("a")
    noise_provider = GroqWhisperSTTProvider(api_key="test", client=noise_client)
    assert noise_provider.transcribe_bytes(b"0" * 1024).filtered is True


def test_groq_whisper_filters_too_small_audio_before_api_call() -> None:
    client = _FakeGroqClient("nao deve chamar")
    provider = GroqWhisperSTTProvider(api_key="test", client=client)

    result = provider.transcribe_bytes(b"tiny", filename="fala.webm")

    assert result.filtered is True
    assert result.text == ""
    assert client.audio.transcriptions.last_call == {}


def test_stt_prompt_is_limited_to_160_words() -> None:
    prompt = " ".join(f"w{i}" for i in range(170))

    normalized = normalize_stt_prompt(prompt)

    assert len(normalized.split()) == 160
    assert normalized.endswith("w159")


def test_stt_language_normalizes_pt_br_for_groq() -> None:
    assert normalize_stt_language("pt-BR") == "pt"
    assert normalize_stt_language("pt_br") == "pt"


def test_voice_stt_transcribe_accepts_multipart_upload(monkeypatch) -> None:
    class _FakeProvider:
        def transcribe_bytes(self, audio: bytes, *, filename: str, model: str | None, language: str | None, prompt: str | None):
            assert audio == b"audio-bytes"
            assert filename == "fala.wav"
            assert model == "whisper-large-v3"
            assert language == "pt"
            assert prompt == "contexto curto"
            return STTTranscriptionResult(
                provider="groq_whisper",
                model=model or DEFAULT_STT_MODEL,
                language=language or "pt",
                text="Hana respondeu",
                raw_text="hannah respondeu",
                filtered=False,
            )

    monkeypatch.setattr(routers.voice, "build_groq_whisper_provider", lambda: _FakeProvider())

    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/api/voice/stt/transcribe",
        data={"model": "whisper-large-v3", "language": "pt", "prompt": "contexto curto"},
        files={"file": ("fala.wav", b"audio-bytes", "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "groq_whisper"
    assert payload["text"] == "Hana respondeu"
    assert payload["rawText"] == "hannah respondeu"
    assert payload["filtered"] is False
    assert payload["filename"] == "fala.wav"


def test_voice_stt_transcribe_can_trigger_text_response(monkeypatch, tmp_path) -> None:
    class _FakeProvider:
        def transcribe_bytes(self, audio: bytes, *, filename: str, model: str | None, language: str | None, prompt: str | None):
            return STTTranscriptionResult(
                provider="groq_whisper",
                model=model or DEFAULT_STT_MODEL,
                language=language or "pt",
                text="abre o terminal",
                raw_text="abre o terminal",
                filtered=False,
            )

    async def _fake_run_text_turn(payload, *, core, memory):
        assert payload["text"] == "abre o terminal"
        return {
            "ok": True,
            "text": "Terminal aberto em texto.",
            "plan": {"intent": "test", "steps": []},
            "meta": {"provider": payload["provider"], "model": payload["model"]},
            "status": {"stage": "success", "detail": "test"},
        }

    monkeypatch.setattr(routers.voice, "build_groq_whisper_provider", lambda: _FakeProvider())
    monkeypatch.setattr(routers.voice, "run_text_turn", _fake_run_text_turn)

    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)
    response = client.post(
        "/api/voice/stt/transcribe",
        data={"respond": "true"},
        files={"file": ("fala.wav", b"audio-bytes", "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["responded"] is True
    assert payload["assistantText"] == "Terminal aberto em texto."

    events = client.get("/api/terminal-agent/events").json()["events"]
    assert [event["kind"] for event in events] == ["user_text", "assistant_thought", "assistant_text"]


def test_voice_text_respond_routes_manual_terminal_command(monkeypatch, tmp_path) -> None:
    async def _fake_run_text_turn(payload, *, core, memory):
        assert payload["text"] == "oi"
        return {
            "ok": True,
            "text": "Oi, Nakamura.",
            "plan": {"intent": "test", "steps": []},
            "meta": {"provider": payload["provider"], "model": payload["model"]},
            "status": {"stage": "success", "detail": "test"},
        }

    monkeypatch.setattr(routers.voice, "run_text_turn", _fake_run_text_turn)

    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)
    response = client.post("/api/voice/text/respond", json={"text": "oi"})

    assert response.status_code == 200
    assert response.json()["assistantText"] == "Oi, Nakamura."
    events = client.get("/api/terminal-agent/events").json()["events"]
    assert [event["kind"] for event in events] == ["user_text", "assistant_thought", "assistant_text"]
