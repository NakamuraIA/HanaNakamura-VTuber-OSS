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

from hana_agent_oss.memory.semantic import (
    cosine_similarity,
    embed_query,
    get_embedding_provider,
    is_semantic_enabled,
    semantic_memory_status,
)
from hana_agent_oss.memory.sqlite import SQLiteStore

logger = logging.getLogger(__name__)


from hana_agent_oss.paths import MEMORY_DB as DEFAULT_MEMORY_DB, MEMORY_EVENTS as DEFAULT_EVENTS_PATH

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


class MemoryStore(SQLiteStore):
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

                CREATE TABLE IF NOT EXISTS graph_facts (
                  id TEXT PRIMARY KEY,
                  subject TEXT NOT NULL,
                  relation TEXT NOT NULL,
                  object TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(subject, relation, object)
                );

                DROP TABLE IF EXISTS browser_sessions;
                DROP TABLE IF EXISTS project_assets;
                DROP TABLE IF EXISTS projects;

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
            self._backfill_memory_item_v2(conn)
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

    def append_event(self, role: str, content: str, *, channel: str = "control_center", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "channel": channel,
            "metadata": metadata or {},
            "created_at": now_iso(),
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(_json_dumps(event) + "\n")
        self._rotate_events_if_needed()
        return event

    def _rotate_events_if_needed(self) -> None:
        """Move the oldest events to the archive when the active file grows too big.

        Without this, hana_events.jsonl grows forever and every context build
        re-reads the whole file, slowing Hana down over time. Nothing is deleted:
        old events are appended to `<name>.archive.jsonl` in original order.
        """
        try:
            if not self.events_path.exists() or self.events_path.stat().st_size < self.EVENTS_ROTATE_BYTES:
                return
            lines = [line for line in self.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(lines) <= self.EVENTS_KEEP_LINES:
                return
            overflow = lines[: -self.EVENTS_KEEP_LINES]
            kept = lines[-self.EVENTS_KEEP_LINES:]
            archive_path = self.events_path.with_suffix(".archive.jsonl")
            with archive_path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(overflow) + "\n")
            self.events_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        except Exception:
            # Rotation must never break event logging itself.
            return

    def recent_events(self, *, limit: int = 50, channel: str | None = None) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        lines = self.events_path.read_text(encoding="utf-8").splitlines()
        items: list[dict[str, Any]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if channel and event.get("channel") != channel:
                continue
            items.append(event)
            if len(items) >= limit:
                break
        return list(reversed(items))

    def clear_events(self, *, channel: str | None = None) -> dict[str, Any]:
        if not self.events_path.exists():
            return {"ok": True, "deleted": 0}
        if channel is None:
            lines = [line for line in self.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            deleted = len(lines)
            self.events_path.write_text("", encoding="utf-8")
            return {"ok": True, "deleted": deleted}

        kept: list[str] = []
        deleted = 0
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if event.get("channel") == channel:
                deleted += 1
                continue
            kept.append(line)
        suffix = "\n" if kept else ""
        self.events_path.write_text("\n".join(kept) + suffix, encoding="utf-8")
        return {"ok": True, "deleted": deleted}

    def add_memory(
        self,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
        kind: str = "note",
        source: str = "manual",
        memory_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Create or update one persistent memory and keep FTS in sync."""
        clean_text = str(text or "").strip()
        if not clean_text:
            raise ValueError("memory_text_empty")

        item_id = memory_id or str(uuid.uuid4())
        timestamp = now_iso()
        metadata = dict(metadata or {})
        with self._connect() as conn:
            existing = conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
            existing_metadata = _safe_json_loads(existing["metadata_json"], {}) if existing else {}
            merged_metadata = {**existing_metadata, **metadata}
            memory_status = _normalize_status(status or merged_metadata.get("status") or (existing["status"] if existing else MEMORY_STATUS_ACTIVE))
            category = str(merged_metadata.get("category") or (existing["category"] if existing else "general")).strip() or "general"
            importance, importance_score = _normalize_importance(merged_metadata.get("importance") or (existing["importance"] if existing else "medium"))
            tags = _normalize_tags(merged_metadata.get("tags") or (existing["tags_json"] if existing else []))
            pinned = 1 if bool(merged_metadata.get("pinned") if "pinned" in merged_metadata else (existing["pinned"] if existing else 0)) else 0
            created_at = existing["created_at"] if existing else timestamp
            last_accessed_at = existing["last_accessed_at"] if existing else timestamp
            archived_at = timestamp if memory_status == MEMORY_STATUS_ARCHIVED and not (existing and existing["archived_at"]) else (existing["archived_at"] if existing else None)
            deleted_at = timestamp if memory_status == MEMORY_STATUS_DELETED and not (existing and existing["deleted_at"]) else (existing["deleted_at"] if existing else None)
            merged_metadata.update(
                {
                    "kind": kind,
                    "source": source,
                    "status": memory_status,
                    "category": category,
                    "importance": importance,
                    "tags": tags,
                    "pinned": bool(pinned),
                }
            )
            conn.execute(
                """
                INSERT INTO memory_items (
                  id, text, kind, source, metadata_json, created_at, updated_at,
                  status, category, importance, importance_score, tags_json,
                  use_count, last_accessed_at, pinned, archived_at, deleted_at,
                  decay_score, embedding_state
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  text = excluded.text,
                  kind = excluded.kind,
                  source = excluded.source,
                  metadata_json = excluded.metadata_json,
                  updated_at = excluded.updated_at,
                  status = excluded.status,
                  category = excluded.category,
                  importance = excluded.importance,
                  importance_score = excluded.importance_score,
                  tags_json = excluded.tags_json,
                  last_accessed_at = COALESCE(memory_items.last_accessed_at, excluded.last_accessed_at),
                  pinned = excluded.pinned,
                  archived_at = excluded.archived_at,
                  deleted_at = excluded.deleted_at,
                  embedding_state = 'pending'
                """,
                (
                    item_id,
                    clean_text,
                    str(kind or "note"),
                    str(source or "manual"),
                    _json_dumps(merged_metadata),
                    created_at,
                    timestamp,
                    memory_status,
                    category,
                    importance,
                    importance_score,
                    _json_dumps(tags),
                    int(existing["use_count"]) if existing else 0,
                    last_accessed_at,
                    pinned,
                    archived_at,
                    deleted_at,
                    float(existing["decay_score"]) if existing else 0.0,
                    "pending",
                ),
            )
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (item_id,))
            if memory_status != MEMORY_STATUS_DELETED:
                conn.execute("INSERT INTO memory_fts (id, text) VALUES (?, ?)", (item_id, clean_text))
            conn.execute("DELETE FROM memory_embeddings WHERE memory_id = ?", (item_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_memory(row)

    def list_memories(self, *, limit: int = 200, status: str = MEMORY_STATUS_ACTIVE) -> list[dict[str, Any]]:
        """List memories by lifecycle status for the Control Panel and tools."""
        status = _normalize_search_status(status)
        query, params = self._status_filter_sql(status)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM memory_items
                WHERE {query}
                ORDER BY pinned DESC, updated_at DESC
                LIMIT ?
                """,
                (*params, max(1, int(limit or 200))),
            ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def profile_memories(self, *, per_category: int = 12) -> list[dict[str, Any]]:
        """Return always-on user-profile memories (likes, dislikes, personal facts).

        These are injected into every prompt so Hana keeps respecting the user's
        preferences even when the current message does not mention them. Ordered
        by importance then recency, capped per category to stay cheap on tokens.
        Never raises: profile retrieval must not break a turn.
        """
        cap = max(1, int(per_category or 12))
        results: list[dict[str, Any]] = []
        try:
            with self._connect() as conn:
                for category in PROFILE_CATEGORIES:
                    rows = conn.execute(
                        f"""
                        SELECT *
                        FROM memory_items
                        WHERE status = ? AND category = ?
                        ORDER BY pinned DESC, importance_score DESC, updated_at DESC
                        LIMIT ?
                        """,
                        (MEMORY_STATUS_ACTIVE, category, cap),
                    ).fetchall()
                    results.extend(self._row_to_memory(row) for row in rows)
        except sqlite3.OperationalError:
            return []
        return results

    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        status: str = MEMORY_STATUS_ACTIVE,
        touch: bool = True,
    ) -> list[dict[str, Any]]:
        """Search persistent memory using FTS/BM25 plus recency, usage and importance."""
        query = (query or "").strip()
        safe_limit = max(1, int(limit or 12))
        status = _normalize_search_status(status)
        if not query:
            memories = self.list_memories(limit=safe_limit, status=status)
            return self._rank_memories(memories, {}, touch=touch)[:safe_limit]

        text_scores: dict[str, float] = {}
        rows: list[sqlite3.Row] = []
        filter_sql, filter_params = self._status_filter_sql(status, alias="m")
        fts_query = _fts_query(query)
        with self._connect() as conn:
            try:
                fts_rows = conn.execute(
                    f"""
                    SELECT m.*, bm25(memory_fts) AS bm25_score
                    FROM memory_fts
                    JOIN memory_items m ON m.id = memory_fts.id
                    WHERE memory_fts MATCH ? AND {filter_sql}
                    LIMIT ?
                    """,
                    (fts_query, *filter_params, safe_limit * 4),
                ).fetchall()
                rows = fts_rows
                for row in fts_rows:
                    bm25_score = abs(float(row["bm25_score"] or 0.0))
                    text_scores[str(row["id"])] = 1.0 / (1.0 + bm25_score)
            except sqlite3.OperationalError:
                terms = _query_terms(query, limit=8)
                filter_sql, filter_params = self._status_filter_sql(status)
                if terms:
                    like_sql = " OR ".join("text LIKE ?" for _ in terms)
                    like_params = tuple(f"%{term}%" for term in terms)
                else:
                    like_sql = "text LIKE ?"
                    like_params = (f"%{query}%",)
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM memory_items
                    WHERE ({like_sql}) AND {filter_sql}
                    ORDER BY pinned DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (*like_params, *filter_params, safe_limit * 4),
                ).fetchall()
                text_scores = {str(row["id"]): 0.35 for row in rows}

        # Semantic layer (optional, env-gated): blend vector similarity into the
        # text scores so Hana finds memories by meaning, not just exact words.
        # Adds candidates FTS missed and boosts the ones both agree on. Degrades
        # to pure FTS when disabled or on any failure — never breaks a search.
        if is_semantic_enabled():
            vec_scores = self._vector_scores(query, limit=safe_limit * 4, status=status)
            if vec_scores:
                missing_ids = [mid for mid in vec_scores if mid not in text_scores]
                if missing_ids:
                    rows = list(rows) + self._rows_by_ids(missing_ids, status=status)
                for mid, vscore in vec_scores.items():
                    # Keep the stronger of FTS vs vector so either signal can surface it.
                    text_scores[mid] = max(text_scores.get(mid, 0.0), vscore)

        if not rows:
            return []
        memories = [self._row_to_memory(row) for row in rows]
        return self._rank_memories(memories, text_scores, touch=touch)[:safe_limit]

    def _rows_by_ids(self, memory_ids: list[str], *, status: str) -> list[sqlite3.Row]:
        """Fetch raw rows for the given ids honoring the lifecycle status filter."""
        ids = [item for item in dict.fromkeys(str(mid).strip() for mid in memory_ids) if item]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        filter_sql, filter_params = self._status_filter_sql(status)
        with self._connect() as conn:
            return conn.execute(
                f"SELECT * FROM memory_items WHERE id IN ({placeholders}) AND {filter_sql}",
                (*ids, *filter_params),
            ).fetchall()

    def _vector_scores(self, query: str, *, limit: int, status: str) -> dict[str, float]:
        """Cosine-rank stored embeddings against the query. {} when off/empty.

        Brute-force in Python: for a personal store (thousands of vectors) this is
        instant and avoids the sqlite-vec native dependency. Returns normalized
        scores in [0, 1] for the top `limit` matches. Never raises.
        """
        clean = (query or "").strip()
        if not clean:
            return {}
        try:
            query_vec = embed_query(clean)
            if not query_vec:
                return {}
            # So compara com vetores do MESMO modelo: espacos diferentes (fastembed vs
            # openrouter, ou modelos distintos) nao sao comparaveis. Trocar de modelo
            # deixa os antigos invisiveis ate serem re-indexados — nunca da lixo.
            # Usa o provider local (patchavel em teste), igual o indexador.
            _provider = get_embedding_provider()
            active_model = getattr(_provider, "model", None) if _provider is not None else None
            if not active_model:
                return {}
            filter_sql, filter_params = self._status_filter_sql(status, alias="m")
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT e.memory_id AS id, e.vector_json AS vector_json
                    FROM memory_embeddings e
                    JOIN memory_items m ON m.id = e.memory_id
                    WHERE {filter_sql} AND e.model = ?
                    """,
                    (*filter_params, active_model),
                ).fetchall()
            scored: list[tuple[str, float]] = []
            for row in rows:
                vector = _safe_json_loads(row["vector_json"], None)
                if not isinstance(vector, list):
                    continue
                sim = cosine_similarity(query_vec, vector)
                if sim <= 0.0:
                    continue
                scored.append((str(row["id"]), (sim + 1.0) / 2.0))  # map [-1,1] -> [0,1]
            scored.sort(key=lambda item: item[1], reverse=True)
            return {mid: score for mid, score in scored[: max(1, int(limit))]}
        except sqlite3.OperationalError:
            return {}
        except Exception:
            # Busca semântica falhou: a Hana cai na busca por texto, mas se isso
            # acontece sempre a memória "esquece" sem motivo aparente. Registra.
            logger.warning("Falha na busca semântica de memória", exc_info=True)
            return {}

    def embed_pending_memories(self, *, max_items: int = 200, batch_size: int = 32) -> dict[str, Any]:
        """Index memories whose embedding_state='pending' (background only).

        Called by the sleep scheduler, never inline in a turn. Embeds in batches,
        upserts into memory_embeddings, and flips embedding_state to 'done'. No-op
        when semantic memory is disabled. Returns a small stats payload.
        """
        provider = get_embedding_provider()
        if provider is None:
            return {"ok": True, "skipped": "disabled", "embedded": 0}

        with self._connect() as conn:
            pending = conn.execute(
                """
                SELECT id, text FROM memory_items
                WHERE embedding_state = 'pending' AND status != ?
                ORDER BY pinned DESC, importance_score DESC, updated_at DESC
                LIMIT ?
                """,
                (MEMORY_STATUS_DELETED, max(1, int(max_items))),
            ).fetchall()
        if not pending:
            return {"ok": True, "embedded": 0, "remaining": 0}

        embedded = 0
        failed = 0
        for start in range(0, len(pending), max(1, int(batch_size))):
            chunk = pending[start : start + max(1, int(batch_size))]
            texts = [str(row["text"] or "") for row in chunk]
            try:
                vectors = provider.embed(texts)
            except Exception:
                failed += len(chunk)
                continue
            if len(vectors) != len(chunk):
                failed += len(chunk)
                continue
            timestamp = now_iso()
            with self._connect() as conn:
                for row, vector in zip(chunk, vectors):
                    conn.execute(
                        """
                        INSERT INTO memory_embeddings
                          (memory_id, provider, model, dimensions, vector_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(memory_id) DO UPDATE SET
                          provider = excluded.provider,
                          model = excluded.model,
                          dimensions = excluded.dimensions,
                          vector_json = excluded.vector_json,
                          updated_at = excluded.updated_at
                        """,
                        (str(row["id"]), getattr(provider, "backend", "fastembed"), provider.model, len(vector), _json_dumps(list(vector)), timestamp, timestamp),
                    )
                    conn.execute(
                        "UPDATE memory_items SET embedding_state = 'done' WHERE id = ?",
                        (str(row["id"]),),
                    )
                conn.commit()
            embedded += len(chunk)

        with self._connect() as conn:
            remaining = conn.execute(
                "SELECT COUNT(*) AS c FROM memory_items WHERE embedding_state = 'pending' AND status != ?",
                (MEMORY_STATUS_DELETED,),
            ).fetchone()["c"]
        return {"ok": failed == 0, "embedded": embedded, "failed": failed, "remaining": int(remaining)}

    def delete_memory(self, memory_id: str, *, hard: bool = False) -> bool:
        """Delete a memory using soft-delete by default."""
        item_id = str(memory_id or "").strip()
        if not item_id:
            return False
        with self._connect() as conn:
            if hard:
                cur = conn.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
                conn.execute("DELETE FROM memory_fts WHERE id = ?", (item_id,))
                conn.execute("DELETE FROM memory_embeddings WHERE memory_id = ?", (item_id,))
                conn.execute("DELETE FROM memory_links WHERE parent_id = ? OR child_id = ?", (item_id, item_id))
                conn.commit()
                return cur.rowcount > 0
            timestamp = now_iso()
            cur = conn.execute(
                """
                UPDATE memory_items
                SET status = ?, deleted_at = ?, updated_at = ?, embedding_state = 'skipped'
                WHERE id = ? AND status != ?
                """,
                (MEMORY_STATUS_DELETED, timestamp, timestamp, item_id, MEMORY_STATUS_DELETED),
            )
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (item_id,))
            conn.commit()
            return cur.rowcount > 0

    def restore_memory(self, memory_id: str) -> bool:
        """Restore an archived or soft-deleted memory back to active status."""
        item_id = str(memory_id or "").strip()
        if not item_id:
            return False
        timestamp = now_iso()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                return False
            conn.execute(
                """
                UPDATE memory_items
                SET status = ?, archived_at = NULL, deleted_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (MEMORY_STATUS_ACTIVE, timestamp, item_id),
            )
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (item_id,))
            conn.execute("INSERT INTO memory_fts (id, text) VALUES (?, ?)", (item_id, row["text"]))
            conn.commit()
            return True

    def archive_memory(self, memory_id: str) -> bool:
        """Archive a memory without deleting it from the local store."""
        return self._set_memory_status(memory_id, MEMORY_STATUS_ARCHIVED)

    def pin_memory(self, memory_id: str, *, pinned: bool = True) -> bool:
        """Pin or unpin one memory so it ranks higher and avoids maintenance decay."""
        item_id = str(memory_id or "").strip()
        if not item_id:
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE memory_items SET pinned = ?, updated_at = ? WHERE id = ? AND status != ?",
                (1 if pinned else 0, now_iso(), item_id, MEMORY_STATUS_DELETED),
            )
            conn.commit()
            return cur.rowcount > 0

    def short_context(self, query: str = "", *, channel: str = "control_center", event_limit: int = 12, memory_limit: int = 8) -> str:
        events = self.recent_events(limit=event_limit, channel=channel)
        memories = self.search(query, limit=memory_limit) if query else self.list_memories(limit=memory_limit)
        parts: list[str] = []
        if events:
            parts.append("Recent events:")
            parts.extend(f"- {item.get('role')}: {item.get('content')}" for item in events[-event_limit:])
        if memories:
            parts.append("Persistent memory:")
            parts.extend(f"- {item['text']}" for item in memories[:memory_limit])
        return "\n".join(parts)

    def compact(
        self,
        *,
        source_channel: str = "control_center",
        limit: int = 40,
        memory_ids: list[str] | None = None,
        archive_originals: bool = False,
    ) -> dict[str, Any]:
        """Compact recent events or selected memories into one summary memory."""
        if memory_ids:
            memories = self._memories_by_ids(memory_ids)
            if not memories:
                return {"created": False, "memory": None, "reason": "no_memories"}
            summary_lines = [f"- {_compact_text(item['text'], limit=320)}" for item in memories]
            summary = "Resumo compactado de memorias:\n" + "\n".join(summary_lines)
            memory = self.add_memory(
                summary,
                kind="summary",
                source="compactador",
                metadata={"category": "reflection", "importance": "medium", "compacted_from": memory_ids},
            )
            self._link_memories(memory["id"], memory_ids, relation="compacted_from")
            if archive_originals:
                for memory_id in memory_ids:
                    self.archive_memory(memory_id)
            return {"created": True, "memory": memory, "sourceCount": len(memories)}

        events = self.recent_events(limit=limit, channel=source_channel)
        if not events:
            return {"created": False, "memory": None, "reason": "no_events"}
        summary_lines = [f"{item.get('role')}: {_compact_text(str(item.get('content') or ''), limit=260)}" for item in events if item.get("content")]
        summary = "Resumo compactado:\n" + "\n".join(summary_lines[-limit:])
        memory = self.add_memory(
            summary,
            kind="summary",
            source="compactador",
            metadata={"channel": source_channel, "event_count": len(events), "category": "conversation_summary"},
        )
        return {"created": True, "memory": memory, "sourceCount": len(events)}

    def merge_memories(self, memory_ids: list[str], *, text: str | None = None, archive_originals: bool = True) -> dict[str, Any]:
        """Merge selected memories into one consolidated memory and optionally archive parents."""
        memories = self._memories_by_ids(memory_ids)
        if len(memories) < 2:
            return {"created": False, "memory": None, "reason": "need_at_least_two_memories"}
        merged_text = str(text or "").strip()
        if not merged_text:
            merged_text = "Memoria consolidada:\n" + "\n".join(f"- {_compact_text(item['text'], limit=280)}" for item in memories)
        memory = self.add_memory(
            merged_text,
            kind="summary",
            source="memory.merge",
            metadata={"category": "reflection", "importance": "medium", "merged_from": memory_ids},
        )
        self._link_memories(memory["id"], memory_ids, relation="merged_from")
        if archive_originals:
            for memory_id in memory_ids:
                self.archive_memory(memory_id)
        return {"created": True, "memory": memory, "sourceCount": len(memories)}

    def run_maintenance(self, *, channel: str = "control_center") -> dict[str, Any]:
        """Run the lightweight maintenance pass used as Hana's manual sleep cycle."""
        updated_decay = 0
        archived_old = 0
        archived_duplicates = 0
        timestamp = now_iso()
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM memory_items WHERE status = ?", (MEMORY_STATUS_ACTIVE,)).fetchall()
            seen_text: dict[str, str] = {}
            for row in rows:
                days = _days_since(row["last_accessed_at"] or row["updated_at"])
                decay = 0.0 if days <= 7 else min(1.0, ((days - 7) // 7 + 1) * 0.05)
                conn.execute("UPDATE memory_items SET decay_score = ? WHERE id = ?", (float(decay), row["id"]))
                updated_decay += 1

                normalized = re.sub(r"\s+", " ", str(row["text"]).lower()).strip()
                if normalized in seen_text and not row["pinned"]:
                    conn.execute(
                        """
                        UPDATE memory_items
                        SET status = ?, archived_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (MEMORY_STATUS_ARCHIVED, timestamp, timestamp, row["id"]),
                    )
                    conn.execute("DELETE FROM memory_fts WHERE id = ?", (row["id"],))
                    self._insert_link(conn, seen_text[normalized], row["id"], "duplicate_of", {"maintenance": True})
                    archived_duplicates += 1
                    continue
                seen_text[normalized] = row["id"]

                if days >= 30 and not row["pinned"] and int(row["use_count"] or 0) == 0 and str(row["importance"]) in {"low", "medium"}:
                    conn.execute(
                        """
                        UPDATE memory_items
                        SET status = ?, archived_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (MEMORY_STATUS_ARCHIVED, timestamp, timestamp, row["id"]),
                    )
                    conn.execute("DELETE FROM memory_fts WHERE id = ?", (row["id"],))
                    archived_old += 1
            conn.commit()
        return {
            "ok": True,
            "updatedDecay": updated_decay,
            "archivedOld": archived_old,
            "archivedDuplicates": archived_duplicates,
            "channel": channel,
            "semantic": self.semantic_status(),
        }

    def audit_memories(self) -> dict[str, Any]:
        """Return memory health counters for the Control Panel and Hana tools."""
        with self._connect() as conn:
            status_rows = conn.execute("SELECT status, COUNT(*) AS count FROM memory_items GROUP BY status").fetchall()
            category_rows = conn.execute("SELECT category, COUNT(*) AS count FROM memory_items GROUP BY category ORDER BY count DESC").fetchall()
            pinned = conn.execute("SELECT COUNT(*) AS count FROM memory_items WHERE pinned = 1 AND status != ?", (MEMORY_STATUS_DELETED,)).fetchone()
            embedding_rows = conn.execute("SELECT embedding_state, COUNT(*) AS count FROM memory_items GROUP BY embedding_state").fetchall()
        return {
            "status": {row["status"]: row["count"] for row in status_rows},
            "category": {row["category"]: row["count"] for row in category_rows},
            "pinned": int(pinned["count"] if pinned else 0),
            "embeddingState": {row["embedding_state"]: row["count"] for row in embedding_rows},
            "semantic": self.semantic_status(),
        }

    def semantic_status(self) -> dict[str, Any]:
        """Report optional semantic memory availability without loading heavy models."""
        return semantic_memory_status().to_dict()

    def clear_runtime(self) -> dict[str, Any]:
        with self._connect() as conn:
            for table in ["memory_items", "memory_fts", "graph_facts", "memory_embeddings", "memory_links"]:
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        if self.events_path.exists():
            self.events_path.write_text("", encoding="utf-8")
        return {"ok": True}

    def list_facts(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT subject, relation, object FROM graph_facts ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def add_fact(self, subject: str, relation: str, object_value: str) -> bool:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO graph_facts (id, subject, relation, object, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), subject, relation, object_value, now_iso()),
            )
            conn.commit()
        return True

    def delete_fact(self, subject: str, relation: str, object_value: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM graph_facts WHERE subject = ? AND relation = ? AND object = ?",
                (subject, relation, object_value),
            )
            conn.commit()
            return cur.rowcount > 0

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

    def _set_memory_status(self, memory_id: str, status: str) -> bool:
        item_id = str(memory_id or "").strip()
        status = _normalize_status(status)
        if not item_id:
            return False
        timestamp = now_iso()
        archived_at = timestamp if status == MEMORY_STATUS_ARCHIVED else None
        deleted_at = timestamp if status == MEMORY_STATUS_DELETED else None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                return False
            cur = conn.execute(
                """
                UPDATE memory_items
                SET status = ?, archived_at = ?, deleted_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, archived_at, deleted_at, timestamp, item_id),
            )
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (item_id,))
            if status != MEMORY_STATUS_DELETED:
                conn.execute("INSERT INTO memory_fts (id, text) VALUES (?, ?)", (item_id, row["text"]))
            conn.commit()
            return cur.rowcount > 0

    def _status_filter_sql(self, status: str, *, alias: str = "") -> tuple[str, tuple[Any, ...]]:
        prefix = f"{alias}." if alias else ""
        if status == "all":
            return f"{prefix}status != ?", (MEMORY_STATUS_DELETED,)
        if status == "long":
            return f"{prefix}status != ? AND length({prefix}text) > 420", (MEMORY_STATUS_DELETED,)
        if status == "pinned":
            return f"{prefix}status != ? AND {prefix}pinned = 1", (MEMORY_STATUS_DELETED,)
        return f"{prefix}status = ?", (status,)

    def _rank_memories(self, memories: list[dict[str, Any]], text_scores: dict[str, float], *, touch: bool) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        for memory in memories:
            metadata = memory.setdefault("metadata", {})
            text_score = float(text_scores.get(memory["id"], 0.0))
            importance = float(metadata.get("importanceScore") or 0.55)
            use_count = int(metadata.get("useCount") or 0)
            days = _days_since(metadata.get("lastAccessedAt") or metadata.get("updatedAt"))
            recency = 1.0 / (1.0 + days / 7.0)
            usage = min(use_count, 20) / 20.0
            pinned = 1.0 if metadata.get("pinned") else 0.0
            decay = float(metadata.get("decayScore") or 0.0)
            status_penalty = 0.2 if metadata.get("status") == MEMORY_STATUS_ARCHIVED else 0.0
            score = (text_score * 0.48) + (importance * 0.2) + (recency * 0.16) + (usage * 0.1) + (pinned * 0.2) - decay - status_penalty
            memory["score"] = round(score, 4)
            metadata["score"] = memory["score"]
            ranked.append(memory)
        ranked.sort(key=lambda item: (float(item.get("score") or 0), bool(item.get("metadata", {}).get("pinned"))), reverse=True)
        if touch:
            self.mark_memories_accessed([item["id"] for item in ranked])
        return ranked

    def mark_memories_accessed(self, memory_ids: list[str]) -> None:
        """Strengthen retrieved memories so useful ones stay high in ranking."""
        unique_ids = [item for item in dict.fromkeys(str(mid).strip() for mid in memory_ids) if item]
        if not unique_ids:
            return
        timestamp = now_iso()
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE memory_items
                SET use_count = use_count + 1, last_accessed_at = ?, decay_score = 0
                WHERE id = ? AND status != ?
                """,
                [(timestamp, memory_id, MEMORY_STATUS_DELETED) for memory_id in unique_ids],
            )
            conn.commit()

    def _memories_by_ids(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        ids = [item for item in dict.fromkeys(str(memory_id).strip() for memory_id in memory_ids) if item]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM memory_items WHERE id IN ({placeholders})", tuple(ids)).fetchall()
        by_id = {str(row["id"]): self._row_to_memory(row) for row in rows}
        return [by_id[item] for item in ids if item in by_id]

    def _link_memories(self, parent_id: str, child_ids: list[str], *, relation: str) -> None:
        with self._connect() as conn:
            for child_id in child_ids:
                self._insert_link(conn, parent_id, child_id, relation, {})
            conn.commit()

    def _insert_link(self, conn: sqlite3.Connection, parent_id: str, child_id: str, relation: str, metadata: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO memory_links (id, parent_id, child_id, relation, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), parent_id, child_id, relation, now_iso(), _json_dumps(metadata)),
        )

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> dict[str, Any]:
        metadata = _safe_json_loads(row["metadata_json"], {})
        tags = _normalize_tags(row["tags_json"])
        metadata.update(
            {
                "source": row["source"],
                "kind": row["kind"],
                "status": row["status"],
                "category": row["category"],
                "importance": row["importance"],
                "importanceScore": float(row["importance_score"]),
                "tags": tags,
                "useCount": int(row["use_count"]),
                "lastAccessedAt": row["last_accessed_at"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "pinned": bool(row["pinned"]),
                "archivedAt": row["archived_at"],
                "deletedAt": row["deleted_at"],
                "decayScore": float(row["decay_score"]),
                "embeddingState": row["embedding_state"],
            }
        )
        return {
            "id": row["id"],
            "text": row["text"],
            "kind": row["kind"],
            "source": row["source"],
            "status": row["status"],
            "category": row["category"],
            "importance": row["importance"],
            "tags": tags,
            "pinned": bool(row["pinned"]),
            "metadata": metadata,
        }
