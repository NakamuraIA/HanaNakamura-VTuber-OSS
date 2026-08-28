from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.memory.long_term.semantic import (
    cosine_similarity,
    embed_query,
    get_embedding_provider,
    is_semantic_enabled,
    semantic_memory_status,
)
from backend.memory.sqlite import SQLiteStore
from backend.memory.events.store import EventMemory
from backend.memory.long_term.maintenance import LongTermMaintenance
from backend.memory.long_term.search import LongTermSearch
from backend.memory.long_term.store import LongTermStore

logger = logging.getLogger(__name__)


from backend.paths import MEMORY_DB as DEFAULT_MEMORY_DB, MEMORY_EVENTS as DEFAULT_EVENTS_PATH

MEMORY_STATUS_ACTIVE = "active"
MEMORY_STATUS_ARCHIVED = "archived"
MEMORY_STATUS_DELETED = "deleted"
MEMORY_STATUSES = {MEMORY_STATUS_ACTIVE, MEMORY_STATUS_ARCHIVED, MEMORY_STATUS_DELETED}

IMPORTANCE_SCORES = {
    "low": 0.25,
    "medium": 0.55,
    "high": 0.85,
    "critical": 1.0,
}

# Categories that describe the USER (Hana's owner). These are always-on profile
# context: they must reach the prompt every turn so Hana respects likes/dislikes
# and personal facts even when the current message does not mention them.
PROFILE_CATEGORIES = ("preference_like", "preference_dislike", "personal_fact")

MEMORY_ITEM_V2_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "category": "TEXT NOT NULL DEFAULT 'general'",
    "importance": "TEXT NOT NULL DEFAULT 'medium'",
    "importance_score": "REAL NOT NULL DEFAULT 0.55",
    "tags_json": "TEXT NOT NULL DEFAULT '[]'",
    "use_count": "INTEGER NOT NULL DEFAULT 0",
    "last_accessed_at": "TEXT",
    "pinned": "INTEGER NOT NULL DEFAULT 0",
    "archived_at": "TEXT",
    "deleted_at": "TEXT",
    "decay_score": "REAL NOT NULL DEFAULT 0",
    "embedding_state": "TEXT NOT NULL DEFAULT 'pending'",
}

# Marca persistente da migração v1->v2. O backfill varre TODAS as linhas de
# memory_items e regrava memory_items + memory_fts (3 escritas por linha), então
# ele só pode rodar UMA vez por banco — não em toda criação de MemoryStore.
# Sem a marca: executa o backfill e grava a marca na mesma transação. Com a
# marca: pula o backfill; os caminhos de escrita normais já mantêm as colunas
# v2 e o FTS sozinhos (add/update/delete/restore/pin/compact/merge/manutenção).
MEMORY_BACKFILL_V2_MARKER_KEY = "memory.backfill_v2.done"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    """Serialize local memory metadata without losing non-ASCII user text."""
    return json.dumps(value, ensure_ascii=False, default=str)


def _safe_json_loads(value: str, default: Any) -> Any:
    """Parse JSON from legacy rows without letting one bad row break startup."""
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return default


def _parse_datetime(value: Any) -> datetime | None:
    """Parse ISO timestamps stored by the memory layer."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _days_since(value: Any) -> float:
    """Return age in days for recency/decay scoring."""
    parsed = _parse_datetime(value)
    if parsed is None:
        return 9999.0
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400)


def _normalize_status(value: Any, default: str = MEMORY_STATUS_ACTIVE) -> str:
    status = str(value or default).strip().lower()
    return status if status in MEMORY_STATUSES else default


def _normalize_importance(value: Any) -> tuple[str, float]:
    label = str(value or "medium").strip().lower()
    if label not in IMPORTANCE_SCORES:
        label = "medium"
    return label, IMPORTANCE_SCORES[label]


def _normalize_tags(value: Any) -> list[str]:
    """Normalize tags from JSON, comma text, or arbitrary frontend payloads."""
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            parsed = _safe_json_loads(stripped, [])
            raw_items = parsed if isinstance(parsed, list) else []
        else:
            raw_items = [part.strip() for part in re.split(r"[,#]", value) if part.strip()]
    else:
        raw_items = []
    tags: list[str] = []
    for item in raw_items:
        tag = str(item or "").strip().lower()
        if tag and tag not in tags:
            tags.append(tag[:40])
    return tags[:12]


def _normalize_search_status(value: Any) -> str:
    status = str(value or MEMORY_STATUS_ACTIVE).strip().lower()
    if status in MEMORY_STATUSES or status in {"all", "long", "pinned"}:
        return status
    return MEMORY_STATUS_ACTIVE


def _compact_text(text: str, *, limit: int = 1200) -> str:
    """Keep compacted memory summaries useful without bloating prompts."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _query_terms(query: str, *, limit: int = 10) -> list[str]:
    """Extract safe lexical terms for FTS and fallback LIKE searches."""
    terms = re.findall(r"[\wÀ-ÿ]{2,}", str(query or "").lower(), flags=re.UNICODE)
    unique_terms = [term for term in dict.fromkeys(terms) if term not in {"que", "com", "para", "uma", "por", "dos", "das"}]
    return unique_terms[:limit]


def _fts_query(query: str) -> str:
    """Build a conservative FTS query from natural speech text."""
    terms = _query_terms(query)
    if not terms:
        return str(query or "").strip()
    return " OR ".join(f'"{term}"' for term in terms)


class MemoryStore(EventMemory, LongTermStore, LongTermSearch, LongTermMaintenance, SQLiteStore):
    """Lightweight runtime memory with SQLite, FTS, soft-delete, and decay metadata."""

    def __init__(self, db_path: str | Path | None = None, events_path: str | Path | None = None) -> None:
        selected_path = db_path or os.environ.get("HANA_MEMORY_DB") or DEFAULT_MEMORY_DB
        super().__init__(selected_path)
        self.events_path = Path(events_path or os.environ.get("HANA_MEMORY_EVENTS") or DEFAULT_EVENTS_PATH).resolve()
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                  id TEXT PRIMARY KEY,
                  text TEXT NOT NULL,
                  kind TEXT NOT NULL DEFAULT 'note',
                  source TEXT NOT NULL DEFAULT 'manual',
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(id UNINDEXED, text);

                DROP TABLE IF EXISTS browser_sessions;
                DROP TABLE IF EXISTS project_assets;
                DROP TABLE IF EXISTS projects;
                DROP TABLE IF EXISTS graph_facts;
                DROP TABLE IF EXISTS facts;
                DROP TABLE IF EXISTS facts_fts;

                CREATE TABLE IF NOT EXISTS settings (
                  key TEXT PRIMARY KEY,
                  value_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                  memory_id TEXT PRIMARY KEY,
                  provider TEXT NOT NULL,
                  model TEXT NOT NULL,
                  dimensions INTEGER NOT NULL,
                  vector_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS memory_links (
                  id TEXT PRIMARY KEY,
                  parent_id TEXT NOT NULL,
                  child_id TEXT NOT NULL,
                  relation TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            self._ensure_memory_item_v2_columns(conn)
            # A tabela settings já existe neste ponto (script acima). Sem a
            # marca: backfill + marca na MESMA transação — se o backfill
            # falhar, o rollback no fim do `with` descarta a marca também e a
            # próxima inicialização tenta de novo. Com a marca: nada é
            # regravado em memory_items/memory_fts durante a inicialização.
            if not conn.execute(
                "SELECT 1 FROM settings WHERE key = ?", (MEMORY_BACKFILL_V2_MARKER_KEY,)
            ).fetchone():
                self._backfill_memory_item_v2(conn)
                conn.execute(
                    """
                    INSERT INTO settings (key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (MEMORY_BACKFILL_V2_MARKER_KEY, _json_dumps({"version": 1}), now_iso()),
                )
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_items_status_updated
                ON memory_items(status, updated_at);

                CREATE INDEX IF NOT EXISTS idx_memory_items_category
                ON memory_items(category);

                CREATE INDEX IF NOT EXISTS idx_memory_items_pinned
                ON memory_items(pinned);

                CREATE INDEX IF NOT EXISTS idx_memory_links_parent
                ON memory_links(parent_id);

                CREATE INDEX IF NOT EXISTS idx_memory_links_child
                ON memory_links(child_id);
                """
            )
            conn.commit()

    def _ensure_memory_item_v2_columns(self, conn: sqlite3.Connection) -> None:
        """Add v2 memory columns to existing v1 SQLite databases."""
        rows = conn.execute("PRAGMA table_info(memory_items)").fetchall()
        existing = {str(row["name"]) for row in rows}
        for column, definition in MEMORY_ITEM_V2_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE memory_items ADD COLUMN {column} {definition}")

    def _backfill_memory_item_v2(self, conn: sqlite3.Connection) -> None:
        """Populate v2 columns and FTS rows for memories created before the migration."""
        rows = conn.execute("SELECT * FROM memory_items").fetchall()
        for row in rows:
            metadata = _safe_json_loads(row["metadata_json"], {})
            category = str(metadata.get("category") or row["category"] or "general").strip() or "general"
            importance, importance_score = _normalize_importance(metadata.get("importance") or row["importance"])
            status = _normalize_status(metadata.get("status") or row["status"])
            tags = _normalize_tags(metadata.get("tags") or row["tags_json"])
            last_accessed_at = row["last_accessed_at"] or row["updated_at"] or row["created_at"] or now_iso()
            pinned = 1 if bool(metadata.get("pinned") or row["pinned"]) else 0
            conn.execute(
                """
                UPDATE memory_items
                SET status = ?, category = ?, importance = ?, importance_score = ?,
                    tags_json = ?, last_accessed_at = ?, pinned = ?
                WHERE id = ?
                """,
                (status, category, importance, importance_score, _json_dumps(tags), last_accessed_at, pinned, row["id"]),
            )
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (row["id"],))
            if status != MEMORY_STATUS_DELETED:
                conn.execute("INSERT INTO memory_fts (id, text) VALUES (?, ?)", (row["id"], row["text"]))

    # Rotation: keep the active events file small (it is fully read on every
    # context build), but NEVER lose events — overflow goes to an archive file.
    EVENTS_ROTATE_BYTES = 5 * 1024 * 1024  # rotate when the active file passes ~5 MB
    EVENTS_KEEP_LINES = 4000               # newest lines kept in the active file


    # Mapa canal antigo -> canal novo. O jsonl usa nomes historicos; a tabela
    # `messages` usa quatro nomes fechados por CHECK.
    _CHANNEL_MAP = {
        "control_center": "chat",
        "chat": "chat",
        "terminal_agent": "terminal",
        "terminal": "terminal",
        "cli": "terminal",
        "discord": "discord",
        "voice": "voice",
    }
    _ROLE_MAP = {"user": "user", "nakamura": "user", "hana": "assistant", "assistant": "assistant"}
























    # Tudo que guarda dado da usuaria. Se uma tabela nova entrar no banco e
    # esquecerem de listar aqui, o "apagar tudo" mente — e alguem pode publicar
    # um banco achando que estava limpo.
    # `skills` fica de FORA de proposito: sao manuais de como fazer as coisas,
    # nao lembranca. Apagar reset de memoria nao devia desaprender a usar yt-dlp.
    TABELAS_DE_DADO_PESSOAL = (
        # antigas (MemoryStore)
        "memory_items", "memory_fts", "memory_embeddings", "memory_links",
        # novas (HanaMemory) — mesmo arquivo sqlite
        "messages", "pinned", "chat_log",
    )

    def clear_runtime(self) -> dict[str, Any]:
        """Apaga TODA memoria da usuaria: as tabelas antigas E as novas.

        Antes so limpava as antigas. Quem chamasse isto pra sanitizar o banco
        antes de publicar continuava com conversa, fatos e regras pessoais
        gravados nas tabelas novas — sem nenhum aviso de que sobrou coisa.

        Devolve a contagem por tabela pra dar pra CONFERIR o que saiu, em vez
        de confiar num "ok: true".
        """
        apagados: dict[str, int] = {}
        with self._connect() as conn:
            existentes = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table in self.TABELAS_DE_DADO_PESSOAL:
                if table not in existentes:
                    continue  # banco antigo/novo pode nao ter todas
                apagados[table] = conn.execute(f'DELETE FROM "{table}"').rowcount
            conn.commit()
        if self.events_path.exists():
            self.events_path.write_text("", encoding="utf-8")
            apagados["hana_events.jsonl"] = -1  # arquivo zerado, sem contagem
        return {"ok": True, "apagados": apagados, "total": sum(v for v in apagados.values() if v > 0)}

    def get_setting(self, key: str, default: Any) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: Any) -> Any:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (key, _json_dumps(value), now_iso()),
            )
            conn.commit()
        return value
