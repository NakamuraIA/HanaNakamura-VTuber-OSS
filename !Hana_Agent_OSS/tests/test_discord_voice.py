from __future__ import annotations

from fastapi.testclient import TestClient

from hana_agent_oss.api import routers
from hana_agent_oss.api.routers.config import normalize_connections_config
from hana_agent_oss.api.server import create_app
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.voice.stt_whisper import STTTranscriptionResult


def test_connections_normalize_discord_voice_flags() -> None:
    config = normalize_connections_config({"discord": True, "discordSpeak": 1, "discordListen": "yes"})

    assert config["discord"] is True
    assert config["discordSpeak"] is True
    assert config["discordListen"] is True


def test_discord_message_routes_through_hana_without_tts(monkeypatch, tmp_path) -> None:
    async def _fake_run_text_turn(payload, *, core, memory):
        assert payload["channel"] == "discord"
        assert "Nakamura" in payload["text"]
        return {
            "ok": True,
            "text": "Resposta no Discord.",
            "plan": {"intent": "test", "steps": []},
            "meta": {"provider": payload["provider"], "model": payload["model"]},
            "status": {"stage": "success", "detail": "test"},
            "media": [],
        }

    monkeypatch.setattr(routers.discord, "run_text_turn", _fake_run_text_turn)

    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)
    response = client.post(
        "/api/discord/message",
        json={"text": "oi", "userId": "123", "displayName": "Nakamura"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "Resposta no Discord."
    assert payload["audio"] is None


def test_discord_audio_requires_listen_enabled(tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    app.state.memory.set_setting("connections_config", {"discord": True, "discordListen": False, "discordSpeak": False})
    client = TestClient(app)

    response = client.post("/api/discord/audio", files={"audio": ("fala.wav", b"audio-bytes", "audio/wav")})

    assert response.status_code == 409
    assert "listening is disabled" in response.json()["detail"]


def test_discord_audio_transcribes_and_can_return_tts(monkeypatch, tmp_path) -> None:
    class _FakeProvider:
        def transcribe_bytes(self, audio: bytes, *, filename: str, model: str | None, language: str | None, prompt: str | None = None):
            assert audio == b"audio-bytes"
            return STTTranscriptionResult(
                provider="groq_whisper",
                model=model or "whisper-large-v3",
                language=language or "pt",
                text="Oi Hana",
                raw_text="Oi Hana",
                filtered=False,
            )

    async def _fake_run_text_turn(payload, *, core, memory):
        assert payload["channel"] == "discord"
        assert "Oi Hana" in payload["text"]
        return {
            "ok": True,
            "text": "Oi pelo Discord.",
            "plan": {"intent": "test", "steps": []},
            "meta": {"provider": payload["provider"], "model": payload["model"]},
            "status": {"stage": "success", "detail": "test"},
            "media": [],
        }

    async def _fake_tts(request, text: str):
        assert text == "Oi pelo Discord."
        return {"provider": "edge", "voice": "pt-BR-FranciscaNeural", "mimeType": "audio/mpeg", "audioBase64": "YXVkaW8="}

    monkeypatch.setattr(routers.discord, "GroqWhisperSTTProvider", lambda: _FakeProvider())
    monkeypatch.setattr(routers.discord, "run_text_turn", _fake_run_text_turn)
    monkeypatch.setattr(routers.discord, "_synthesize_discord_tts", _fake_tts)

    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    app.state.memory.set_setting("connections_config", {"discord": True, "discordListen": True, "discordSpeak": True})
    client = TestClient(app)
    response = client.post(
        "/api/discord/audio",
        data={"userId": "123", "displayName": "Nakamura"},
        files={"audio": ("fala.wav", b"audio-bytes", "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcribed"] is True
    assert payload["text"] == "Oi Hana"
    assert payload["assistantText"] == "Oi pelo Discord."
    assert payload["audio"]["audioBase64"] == "YXVkaW8="
