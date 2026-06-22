from __future__ import annotations

from fastapi.testclient import TestClient

from hana_agent_oss.api import routers
from hana_agent_oss.api.routers.config import normalize_connections_config
from hana_agent_oss.api.server import create_app
from hana_agent_oss.memory.store import MemoryStore


# --- Conexões (sem flags de voz da call) ----------------------------------- #

def test_connections_normalize_has_discord_no_voice_flags() -> None:
    config = normalize_connections_config({"discord": True})
    assert config["discord"] is True
    # flags de call foram removidas (Discord agora é chatbot de texto)
    assert "discordSpeak" not in config
    assert "discordListen" not in config


# --- /api/discord/message (texto) ------------------------------------------ #

def test_discord_message_routes_through_hana(monkeypatch, tmp_path) -> None:
    async def _fake_run_text_turn(payload, *, core, memory):
        assert payload["channel"] == "discord"
        assert "Operador" in payload["text"]
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
    app.state.memory.set_setting("connections_config", {"discord": True})
    client = TestClient(app)
    response = client.post(
        "/api/discord/message",
        json={"text": "oi", "userId": "123", "displayName": "Operador"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "Resposta no Discord."
    assert "audio" not in payload  # voz removida


def test_discord_message_forwards_attachments(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}

    async def _fake_run_text_turn(payload, *, core, memory):
        seen["attachments"] = payload.get("attachments")
        return {"ok": True, "text": "ok", "meta": {}, "status": {"stage": "success"}, "media": []}

    monkeypatch.setattr(routers.discord, "run_text_turn", _fake_run_text_turn)
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    app.state.memory.set_setting("connections_config", {"discord": True})
    client = TestClient(app)
    response = client.post(
        "/api/discord/message",
        json={"text": "olha isso", "userId": "1", "attachments": [{"type": "image/png", "data": "data:image/png;base64,AAAA", "name": "x.png"}]},
    )
    assert response.status_code == 200
    assert isinstance(seen["attachments"], list) and seen["attachments"][0]["name"] == "x.png"


def test_discord_message_requires_discord_enabled(tmp_path) -> None:
    app = create_app()
    app.state.memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    app.state.memory.set_setting("connections_config", {"discord": False})
    client = TestClient(app)
    response = client.post("/api/discord/message", json={"text": "oi", "userId": "1"})
    assert response.status_code == 409


# --- Trava de dono (bot privado) ------------------------------------------- #

def test_owner_default_is_nakamura(monkeypatch) -> None:
    from hana_agent_oss.discord_bot import owner

    monkeypatch.delenv("HANA_OWNER_ID", raising=False)
    monkeypatch.delenv("HANA_OWNER_IDS", raising=False)
    assert owner.is_owner("0") is True
    assert owner.is_owner("999999999999999999") is False
    assert owner.is_owner(None) is False


def test_owner_overridable_by_env(monkeypatch) -> None:
    from hana_agent_oss.discord_bot import owner

    monkeypatch.setenv("HANA_OWNER_IDS", "111, 222 333")
    assert owner.is_owner("111") is True
    assert owner.is_owner("333") is True
    assert owner.is_owner("0") is False  # default substituído


# --- Split de mensagem (limite do Discord) --------------------------------- #

def test_split_text_respects_limit() -> None:
    from hana_agent_oss.discord_bot.delivery import split_text_safely

    text = "\n\n".join("paragrafo " + str(i) * 50 for i in range(200))
    chunks = split_text_safely(text, limit=1900)
    assert len(chunks) > 1
    assert all(len(c) <= 1900 for c in chunks)
    # nada se perde (aprox): junta de volta sem espaços extras significativos
    assert "paragrafo" in chunks[0]


def test_split_short_text_single_chunk() -> None:
    from hana_agent_oss.discord_bot.delivery import split_text_safely

    assert split_text_safely("oi", limit=1900) == ["oi"]
    assert split_text_safely("", limit=1900) == [""]


def test_big_code_block_becomes_file() -> None:
    from hana_agent_oss.discord_bot.delivery import build_payloads

    code = "x = 1\n" * 400  # > 1500 chars
    text = f"Aqui vai:\n```python\n{code}```\nPronto."
    chunks, code_file = build_payloads(text)
    assert code_file is not None
    filename, data, lang = code_file
    assert filename.endswith(".py") and lang == "python"
    assert b"x = 1" in data
    # o texto inline aponta para o anexo em vez do bloco gigante
    assert any("anexo" in c for c in chunks)


def test_collapse_exact_duplicate_response() -> None:
    from hana_agent_oss.discord_bot.delivery import build_payloads, collapse_exact_duplicate

    original = "Pão? Tá com fome ou é código pra alguma coisa que eu não sei? Mando um yakisoba."
    doubled = original + " " + original
    assert collapse_exact_duplicate(doubled) == original
    chunks, _ = build_payloads(doubled)
    assert chunks == [original]
    # não colapsa repetições curtas legítimas
    assert collapse_exact_duplicate("pão pão") == "pão pão"


def test_small_code_stays_inline() -> None:
    from hana_agent_oss.discord_bot.delivery import build_payloads

    text = "veja:\n```py\nprint('oi')\n```"
    chunks, code_file = build_payloads(text)
    assert code_file is None
    assert "```" in chunks[0]


# --- Auto-start do bot via toggle de conexão -------------------------------- #

def test_discord_bot_manager_lifecycle(monkeypatch) -> None:
    """start/stop/apply são idempotentes e não sobem processo real no teste."""
    from hana_agent_oss.discord_bot import manager as mgr_mod

    class _FakeProc:
        def __init__(self) -> None:
            self.pid = 4242
            self._alive = True
            self.terminated = False

        def poll(self):
            return None if self._alive else 0

        def terminate(self):
            self.terminated = True
            self._alive = False

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self._alive = False

    spawned = []

    def _fake_popen(args, **kwargs):
        spawned.append(args)
        return _FakeProc()

    monkeypatch.setattr(mgr_mod.subprocess, "Popen", _fake_popen)
    monkeypatch.setenv("DISCORD_TOKEN", "fake-token-123")

    manager = mgr_mod.DiscordBotManager()
    assert manager.status() == {"running": False, "tokenPresent": True}

    first = manager.start()
    assert first["started"] is True and manager.is_running()
    # idempotente: segundo start não cria outro processo
    assert manager.start()["started"] is False
    assert len(spawned) == 1

    stopped = manager.stop()
    assert stopped["stopped"] is True and not manager.is_running()
    # idempotente: stop de novo é no-op
    assert manager.stop()["stopped"] is False

    # apply liga e desliga
    assert manager.apply(enabled=True)["running"] is True
    assert manager.apply(enabled=False)["running"] is False


def test_discord_bot_manager_requires_token(monkeypatch) -> None:
    from hana_agent_oss.discord_bot import manager as mgr_mod

    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    manager = mgr_mod.DiscordBotManager()
    result = manager.start()
    assert result["ok"] is False and result["error"] == "missing_token"
