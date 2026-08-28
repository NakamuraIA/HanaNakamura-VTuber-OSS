"""Cadastro compartilhado de nomes para vozes TTS customizadas."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from backend.api.routers.config import get_tts_voice_aliases, save_tts_voice_alias
from backend.memory.store import MemoryStore


class _Memory:
    def __init__(self) -> None:
        self.settings: dict[str, object] = {}

    def get_setting(self, key: str, default: object) -> object:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: object) -> object:
        self.settings[key] = value
        return value


def test_nome_da_voz_e_salvo_e_editado_no_banco_compartilhado(tmp_path: Path) -> None:
    db_path = tmp_path / "hana.sqlite3"
    memory = MemoryStore(db_path, events_path=tmp_path / "events.jsonl")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(memory=memory)))

    asyncio.run(save_tts_voice_alias(request, {
        "provider": "fishaudio",
        "voiceId": "voice-123",
        "name": "Hana principal",
    }))
    asyncio.run(save_tts_voice_alias(request, {
        "provider": "fishaudio",
        "voiceId": "voice-123",
        "name": "Hana atualizada",
    }))

    reopened = MemoryStore(db_path, events_path=tmp_path / "events.jsonl")
    aliases = asyncio.run(get_tts_voice_aliases(
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(memory=reopened)))
    ))
    assert aliases == {"fishaudio": {"voice-123": "Hana atualizada"}}


def test_fish_audio_e_elevenlabs_usam_o_mesmo_cadastro() -> None:
    memory = _Memory()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(memory=memory)))

    asyncio.run(save_tts_voice_alias(request, {
        "provider": "fishaudio",
        "voiceId": "fish-1",
        "name": "Hana Fish",
    }))
    aliases = asyncio.run(save_tts_voice_alias(request, {
        "provider": "elevenlabs",
        "voiceId": "eleven-1",
        "name": "Hana Eleven",
    }))

    assert aliases == {
        "fishaudio": {"fish-1": "Hana Fish"},
        "elevenlabs": {"eleven-1": "Hana Eleven"},
    }
