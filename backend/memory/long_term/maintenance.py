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




class LongTermMaintenance:
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
        summary_lines = [
            f"{item.get('role')}: {_compact_text(str(item.get('content') or ''), limit=260)}"
            for item in events
            if item.get("content")
            and not (
                isinstance(item.get("metadata"), dict)
                and item["metadata"].get("conversation") is False
            )
        ]
        if not summary_lines:
            return {"created": False, "memory": None, "reason": "no_conversation_events"}
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
            # Registros-indice de anexo: contam como memoria "ativa" no painel, mas
            # NAO sao lembranca e nao entram mais no contexto por turno. Expor o
            # numero deixa claro por que "ativas" e maior do que parece.
            attachments = conn.execute(
                """
                SELECT COUNT(*) AS count FROM memory_items
                WHERE status != ?
                  AND (COALESCE(kind, '') = 'attachment'
                       OR COALESCE(source, '') = 'chat_attachment'
                       OR COALESCE(metadata_json, '') LIKE '%"kind": "attachment"%'
                       OR COALESCE(metadata_json, '') LIKE '%"source": "chat_attachment"%')
                """,
                (MEMORY_STATUS_DELETED,),
            ).fetchone()
        return {
            "status": {row["status"]: row["count"] for row in status_rows},
            "category": {row["category"]: row["count"] for row in category_rows},
            "pinned": int(pinned["count"] if pinned else 0),
            "attachments": int(attachments["count"] if attachments else 0),
            "embeddingState": {row["embedding_state"]: row["count"] for row in embedding_rows},
            "semantic": self.semantic_status(),
        }


    def semantic_status(self) -> dict[str, Any]:
        """Report optional semantic memory availability without loading heavy models."""
        return semantic_memory_status().to_dict()

