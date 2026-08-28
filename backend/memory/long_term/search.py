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




class LongTermSearch:
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
            return self._rank_memories(memories, {}, touch=touch, limit=safe_limit)

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
                    # bm25 do SQLite e NEGATIVO e quanto MAIS negativo, melhor a
                    # combinacao. Com abs() vira magnitude de relevancia. A conta
                    # antiga era `1/(1+rel)`, que INVERTIA o ranking: combinacao
                    # perfeita (rel 3.4) tirava 0.23 e combinacao fraca (rel 0.5)
                    # tirava 0.67 — a busca por palavra empurrava pra baixo
                    # exatamente o que ela tinha achado de melhor, e qualquer
                    # acerto semantico fraco passava na frente.
                    relevance = abs(float(row["bm25_score"] or 0.0))
                    text_scores[str(row["id"])] = relevance / (1.0 + relevance)
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
        return self._rank_memories(memories, text_scores, touch=touch, limit=safe_limit)


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


    def _rank_memories(
        self,
        memories: list[dict[str, Any]],
        text_scores: dict[str, float],
        *,
        touch: bool,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
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
        if limit is not None:
            ranked = ranked[:limit]
        if touch:
            # So o que sobrou depois do corte. A busca levanta ate 4x o limite de
            # candidatas; marcar TODAS dava "uso" pra memoria que nunca chegou no
            # prompt, e como use_count so sobe, memoria velha ficava presa no topo
            # pra sempre (no banco real deu 386 usos em 13 memorias) enquanto fato
            # novo nascia sem chance de competir.
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

