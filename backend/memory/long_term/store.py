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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    """Responsabilidade extraída durante a fase 9"""
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




class LongTermStore:
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


    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        """Fetch one memory by id regardless of status, or None if it doesn't exist."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (str(memory_id or "").strip(),)).fetchone()
        return self._row_to_memory(row) if row else None


    def list_memories(
        self,
        *,
        limit: int = 200,
        status: str = MEMORY_STATUS_ACTIVE,
        exclude_attachments: bool = False,
    ) -> list[dict[str, Any]]:
        """List memories by lifecycle status for the Control Panel and tools.

        ``exclude_attachments`` filtra no SQL (nao em Python) de proposito: o
        LIMIT roda no banco, entao filtrar depois devolveria menos linhas que o
        pedido — ou NENHUMA, quando os anexos sao os mais recentes e ocupam o
        limite inteiro. Padrao False pra nao mudar quem depende dos anexos
        (AttachmentStore.recent, painel de memoria).
        """
        status = _normalize_search_status(status)
        query, params = self._status_filter_sql(status)
        if exclude_attachments:
            # kind/source ficam no topo (v2) e tambem no metadata JSON (linhas
            # antigas migradas) — os dois precisam ser cobertos.
            query += (
                " AND COALESCE(kind, '') != 'attachment'"
                " AND COALESCE(source, '') != 'chat_attachment'"
                " AND COALESCE(metadata_json, '') NOT LIKE '%\"kind\": \"attachment\"%'"
                " AND COALESCE(metadata_json, '') NOT LIKE '%\"source\": \"chat_attachment\"%'"
            )
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
            # embedding_state volta pra 'pending': soft_delete marca 'skipped' pra
            # tirar a memoria do indice semantico, e o restore precisa desfazer isso.
            # Sem esta linha a memoria voltava viva e indexada no FTS, mas ficava
            # FORA da busca semantica pra sempre — so era achada por palavra exata.
            # (No banco real da Nakamura isso deixou 12 memorias ativas orfas.)
            conn.execute(
                """
                UPDATE memory_items
                SET status = ?, archived_at = NULL, deleted_at = NULL, updated_at = ?,
                    embedding_state = CASE WHEN embedding_state = 'skipped' THEN 'pending' ELSE embedding_state END
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

