from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from hana_agent_oss.api.server import create_app
from hana_agent_oss.api import routers
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.voice.tts_edge import EdgeTTSResult, split_tts_text
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text


def test_tts_readable_sanitizes_markdown_code_links_and_punctuation() -> None:
    text = "Veja **isso**: [docs](https://example.test) ```python\nprint('x')\n``` ok!!! 😊"

    assert sanitize_tts_text(text) == "Veja isso. docs ok!"


def test_tts_readable_never_speaks_memory_save_blocks() -> None:
    text = (
        "Amei o seu guia, Nakamura!\n\n"
        '<salvar_memoria>{"text": "Nakamura criou um plano de baus", '
        '"importance": "high", "category": "game_state"}</salvar_memoria>'
    )
    verbalized = (
        'Amei o seu guia, Nakamura! salvar memoria "text": "Nakamura criou um plano de baus", '
        '"importance": "high", "category": "game_state" salvar memoria'
    )

    assert sanitize_tts_text(text) == "Amei o seu guia, Nakamura!"
    assert sanitize_tts_text(verbalized) == "Amei o seu guia, Nakamura!"


def test_edge_tts_text_is_split_for_lower_first_audio_latency() -> None:
    text = (
        "Primeira frase curta. "
        "Segunda frase um pouco maior para simular uma resposta falada da Hana. "
        "Terceira frase tambem deve virar outro bloco quando o limite for baixo."
    )

    chunks = split_tts_text(text, max_chars=70)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 90 for chunk in chunks)
    assert chunks[0].endswith(".")


def test_terminal_agent_events_are_channel_scoped(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    memory.append_event("user", "chat stays", channel="control_center")

    app = create_app()
    app.state.memory = memory
    client = TestClient(app)

    created = client.post(
        "/api/terminal-agent/events",
        json={"kind": "assistant_text", "text": "Resposta com `codigo` e https://example.test"},
    )
    assert created.status_code == 200
    event = created.json()["event"]
    assert event["kind"] == "assistant_text"
    assert event["tts"]["text"] == "Resposta com codigo e link"

    listed = client.get("/api/terminal-agent/events").json()
    assert [item["kind"] for item in listed["events"]] == ["assistant_text"]

    cleared = client.delete("/api/terminal-agent/events")
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] == 1
    assert memory.recent_events(channel="control_center")[0]["content"] == "chat stays"


def test_terminal_agent_event_can_disable_tts_text(tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)

    created = client.post(
        "/api/terminal-agent/events",
        json={
            "kind": "assistant_text",
            "text": "Resposta visivel sem voz.",
            "speechText": "",
            "metadata": {"tts": False},
        },
    )

    assert created.status_code == 200
    event = created.json()["event"]
    assert event["speechText"] == ""
    assert event["tts"]["speakable"] is False


def test_terminal_agent_sanitizes_explicit_tts_text(tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)

    created = client.post(
        "/api/terminal-agent/events",
        json={
            "kind": "assistant_text",
            "text": "Resposta visivel.",
            "speechText": 'Fala limpa <salvar_memoria>{"text":"segredo interno"}</salvar_memoria>',
        },
    )

    assert created.status_code == 200
    event = created.json()["event"]
    assert event["speechText"] == "Fala limpa"
    assert event["tts"]["text"] == "Fala limpa"


def test_voice_config_and_catalog_contract(tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")

    class _FakeRuntime:
        memory = app.state.memory

        def configure_hotkeys(self, connections):
            return {"running": False, "state": "idle"}

        def apply_config(self, config):
            return {"running": False, "state": "idle", "config": config}

        def start(self, config):
            return {"running": True, "state": "listening", "config": config}

        def stop(self, reason="user_request"):
            return {"running": False, "state": "idle", "reason": reason}

        def status(self):
            return {"running": False, "state": "idle"}

    app.state.voice_runtime = _FakeRuntime()
    client = TestClient(app)

    response = client.post(
        "/api/config/voice",
        json={
            "sttProvider": "groq_whisper",
            "ttsProvider": "google",
            "ttsEnabled": True,
            "ttsSpeed": "1.25",
            "inputDeviceId": "browser:abc",
        },
    )
    assert response.status_code == 200
    config = response.json()
    assert config["sttProvider"] == "groq_whisper"
    assert config["ttsProvider"] == "google_cloud_tts"
    assert config["ttsEnabled"] is False
    assert config["connectionState"]["owner"] == "connections"
    assert config["ttsSpeed"] == 1.25
    assert config["inputDeviceId"] == "browser:abc"

    elevenlabs = client.post(
        "/api/config/voice",
        json={
            "ttsProvider": "elevenlabs",
            "ttsVoice": "custom-voice-id",
            "ttsModel": "eleven_flash_v2_5",
            "ttsVolume": 1.4,
            "ttsStability": 1.4,
            "ttsSimilarity": "0.82",
            "ttsStyle": -0.5,
            "ttsSpeakerBoost": False,
        },
    ).json()
    assert elevenlabs["ttsProvider"] == "elevenlabs"
    assert elevenlabs["ttsVoice"] == "custom-voice-id"
    assert elevenlabs["ttsModel"] == "eleven_flash_v2_5"
    assert elevenlabs["ttsVolume"] == 1.0
    assert elevenlabs["ttsStability"] == 1.0
    assert elevenlabs["ttsSimilarity"] == 0.82
    assert elevenlabs["ttsStyle"] == 0.0
    assert elevenlabs["ttsSpeakerBoost"] is False

    connections = client.post("/api/config/conexoes", json={"tts": True, "stt": True}).json()
    assert connections["tts"] is True
    assert connections["stt"] is True
    assert connections["vad"] is True
    config = client.get("/api/config/voice").json()
    assert config["ttsEnabled"] is True
    assert config["sttEnabled"] is True

    catalog = client.get("/api/config/voice/catalog").json()
    assert {item["id"] for item in catalog["sttProviders"]} >= {"gemini_audio", "openai", "local", "groq_whisper"}
    assert {item["id"] for item in catalog["ttsProviders"]} >= {"google_cloud_tts", "azure", "cartesia", "minimax", "elevenlabs"}
    elevenlabs_catalog = next(item for item in catalog["ttsProviders"] if item["id"] == "elevenlabs")
    assert elevenlabs_catalog["defaultModel"] == "eleven_flash_v2_5"
    assert "eleven_multilingual_v2" in elevenlabs_catalog["models"]


def test_terminal_agent_supports_runtime_event_kinds_and_stop_contract(tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)

    created = client.post(
        "/api/terminal-agent/events",
        json={"kind": "ouvindo", "text": "Microfone ouvindo", "metadata": {"tts": False}},
    )
    assert created.status_code == 200
    assert created.json()["event"]["kind"] == "listening"

    stopped = client.post("/api/terminal-agent/tts/stop", json={"reason": "test"}).json()
    assert stopped["stopped"] is True
    assert stopped["event"]["kind"] == "speaking"
    assert stopped["event"]["status"] == "stopped"


def test_voice_runtime_api_contract(monkeypatch, tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)

    class _FakeRuntime:
        memory = app.state.memory
        applied = None
        hotkeys = None

        def start(self, config):
            return {"running": True, "state": "listening", "config": config}

        def apply_config(self, config):
            self.applied = config
            return {"running": True, "state": "listening", "config": config}

        def configure_hotkeys(self, connections):
            self.hotkeys = connections
            return {"running": True, "state": "listening"}

        def stop(self, reason="user_request"):
            return {"running": False, "state": "idle", "reason": reason}

        def status(self):
            return {"running": True, "state": "listening"}

        def interrupt(self, reason="user_request", append_event=True):
            return {"running": True, "state": "listening", "interrupted": reason, "append": append_event}

    app.state.voice_runtime = _FakeRuntime()
    client.post("/api/config/conexoes", json={"stt": True, "tts": True})

    started = client.post("/api/voice/runtime/start").json()
    assert started["runtime"]["running"] is True
    assert started["runtime"]["config"]["sttEnabled"] is True
    assert started["runtime"]["config"]["ttsEnabled"] is True
    assert started["runtime"]["config"]["vadEnabled"] is True

    assert client.get("/api/voice/runtime/status").json()["runtime"]["state"] == "listening"
    assert client.post("/api/voice/runtime/configure", json={"ttsSpeed": 1.23}).json()["runtime"]["config"]["ttsSpeed"] == 1.0
    client.post("/api/config/voice", json={"ttsSpeed": 1.23})
    assert client.post("/api/voice/runtime/configure").json()["runtime"]["config"]["ttsSpeed"] == 1.23
    assert client.post("/api/voice/runtime/interrupt", json={"reason": "test"}).json()["runtime"]["interrupted"] == "test"
    assert client.post("/api/voice/runtime/stop", json={"reason": "test"}).json()["runtime"]["running"] is False


def test_voice_input_devices_have_browser_contract(tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)

    payload = client.get("/api/config/voice/input-devices").json()

    assert payload["recommendedCapture"] == "sounddevice"
    assert payload["devices"][0]["id"] == "browser_default"
    assert payload["devices"][0]["source"] == "browser_media_recorder"


def test_edge_tts_synthesize_returns_audio_payload(monkeypatch, tmp_path) -> None:
    class _FakeEdgeProvider:
        def __init__(self, *, voice: str, speed, pitch) -> None:
            self.voice = voice
            self.speed = speed
            self.pitch = pitch

        async def synthesize(self, text: str) -> EdgeTTSResult:
            assert text == "Oi Hana"
            return EdgeTTSResult(
                provider="edge",
                voice=self.voice,
                rate="+10%",
                pitch="+5Hz",
                volume="+0%",
                text=text,
                audio=b"mp3-bytes",
            )

    monkeypatch.setattr(routers.voice, "build_edge_tts_provider", _FakeEdgeProvider)

    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    client = TestClient(app)
    client.post(
        "/api/config/voice",
        json={"ttsProvider": "edge", "ttsVoice": "pt-BR-AntonioNeural", "ttsSpeed": 1.1, "ttsPitch": 5},
    )

    response = client.post("/api/voice/tts/synthesize", json={"text": "Oi **Hana**"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "edge"
    assert payload["voice"] == "pt-BR-AntonioNeural"
    assert payload["audioBase64"] == "bXAzLWJ5dGVz"
    assert payload["text"] == "Oi Hana"


def test_voice_tts_speak_uses_runtime_and_requires_connections(tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    spoken: list[str] = []

    class _FakeRuntime:
        memory = app.state.memory

        def configure_hotkeys(self, connections):
            return {"running": False, "state": "idle"}

        def apply_config(self, config):
            return {"running": False, "state": "idle", "config": config}

        def status(self):
            return {"running": False, "state": "idle"}

        async def speak_text(self, text: str, *, require_enabled: bool = True) -> bool:
            spoken.append(text)
            return True

    app.state.voice_runtime = _FakeRuntime()
    client = TestClient(app)

    disabled = client.post("/api/voice/tts/speak", json={"text": "Oi **Hana** 😊"})
    assert disabled.status_code == 409

    client.post("/api/config/conexoes", json={"tts": True})
    response = client.post("/api/voice/tts/speak", json={"text": "Oi **Hana** 😊"})

    assert response.status_code == 200
    assert response.json()["text"] == "Oi Hana"
    assert spoken == ["Oi Hana"]
