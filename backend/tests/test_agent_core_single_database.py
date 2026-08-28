from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from backend.bd.agent_core import AGENT_CORE_TABLES
from backend.core.runtime import HanaAgentCore
from backend.memory.core import HanaMemory
from backend.memory.storage import RuntimeStore
from backend.providers.stt import whisper as stt_whisper
from backend.providers.tts import edge as tts_edge
from backend.paths import MEMORY_DB, RUNTIME_DB


def test_agent_core_uses_namespaced_tables_in_same_database() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "hana.sqlite3"
        canonical = HanaMemory(str(db_path))
        canonical.add_message(role="user", author="Naka", content="canonica", channel="chat")

        store = RuntimeStore(db_path)
        core = HanaAgentCore(store=store)
        assert core.run("tools").ok is True
        assert core.run(f'file.exists "{Path(__file__).resolve()}"').ok is True

        assert store.counts() == {
            "messages": 4,
            "events": 7,
            "tool_runs": 1,
            "working_context": 1,
        }
        assert canonical.recent_messages("chat")[-1]["content"] == "canonica"
        assert store.load_working_context().preferred_file() == str(Path(__file__).resolve())

        with closing(sqlite3.connect(db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            canonical_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
        assert set(AGENT_CORE_TABLES) <= tables
        assert "author" in canonical_columns
        assert "context_json" not in canonical_columns


def test_runtime_db_name_is_compatibility_alias_for_main_database() -> None:
    assert RUNTIME_DB == MEMORY_DB


def test_voice_ffmpeg_setting_comes_from_main_database(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "hana.sqlite3"
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.touch()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO settings VALUES (?, ?, datetime('now'))",
            ("portabilidade_config", json.dumps({"ffmpegPath": str(ffmpeg_path)})),
        )
        conn.commit()

    monkeypatch.setattr("backend.paths.MEMORY_DB", db_path)
    assert stt_whisper._ffmpeg_path() == str(ffmpeg_path)
    assert tts_edge._ffmpeg_path() == str(ffmpeg_path)
