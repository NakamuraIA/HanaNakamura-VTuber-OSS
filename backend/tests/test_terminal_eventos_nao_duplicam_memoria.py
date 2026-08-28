"""Garante que eventos visuais do Terminal não virem falas duplicadas."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from backend.api.services.terminal_agent import append_terminal_event
from backend.api.services.unified_history import build_unified_history
from backend.memory.long_term.sleep import collect_transcript
from backend.memory.store import MemoryStore


def _store(tmp: str) -> MemoryStore:
    return MemoryStore(str(Path(tmp) / "m.db"), events_path=str(Path(tmp) / "e.jsonl"))


def _messages(memory: MemoryStore) -> list[tuple[str, str, str]]:
    # ``sqlite3.Connection.__exit__`` não fecha o arquivo no Windows.
    with closing(sqlite3.connect(memory.db_path)) as connection:
        return connection.execute(
            "SELECT role, channel, content FROM messages ORDER BY id"
        ).fetchall()


def test_evento_visual_continua_no_terminal_sem_entrar_em_messages() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        memory = _store(tmp)
        append_terminal_event(memory, {
            "kind": "assistant_text",
            "source": "hana",
            "displayText": "resposta visível",
            "metadata": {"tts": False},
        })

        events = memory.recent_events(channel="terminal_agent")
        assert len(events) == 1
        assert events[0]["metadata"]["conversation"] is False
        assert _messages(memory) == []


def test_turno_real_aparece_uma_vez_no_contexto_e_no_sono() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        memory = _store(tmp)
        question = "PERGUNTA_CANONICA"
        answer = "RESPOSTA_CANONICA"

        append_terminal_event(memory, {
            "kind": "user_text", "source": "stt", "displayText": question,
            "metadata": {"tts": False},
        })
        memory.append_event("user", question, channel="voice")
        memory.append_event("hana", answer, channel="voice")
        append_terminal_event(memory, {
            "kind": "assistant_text", "source": "hana", "displayText": answer,
            "metadata": {"tts": False},
        })

        context = json.dumps(build_unified_history(memory, channel="voice"), ensure_ascii=False)
        transcript = collect_transcript(memory, None)
        assert context.count(question) == 1
        assert context.count(answer) == 1
        assert transcript.count(question) == 1
        assert transcript.count(answer) == 1
        assert _messages(memory) == [
            ("user", "voice", question),
            ("assistant", "voice", answer),
        ]


def test_monitoramento_do_discord_nao_vaza_para_voz() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        memory = _store(tmp)
        append_terminal_event(memory, {
            "kind": "user_text", "source": "discord", "displayText": "SEGREDO_DISCORD",
            "metadata": {"tts": False},
        })

        context = json.dumps(build_unified_history(memory, channel="voice"), ensure_ascii=False)
        assert "SEGREDO_DISCORD" not in context
