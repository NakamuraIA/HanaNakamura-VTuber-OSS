from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteStore:
    """Shared SQLite connection helper for local Agent OSS stores."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _executescript(self, script: str) -> None:
        with self._connect() as conn:
            conn.executescript(script)
            conn.commit()
