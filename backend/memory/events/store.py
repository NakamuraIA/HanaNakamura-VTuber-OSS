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




class EventMemory:
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
        self._mirror_to_messages(role, content, channel, metadata)
        self._mirror_to_chat_log(role, content, channel, metadata)
        return event


    def _mirror_to_messages(
        self,
        role: str,
        content: str,
        channel: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Espelha a fala na tabela `messages` (memoria curta nova).

        Escreve nos DOIS lugares de proposito: o jsonl segue como fonte de verdade
        enquanto o front nao migra, e a tabela ja vai acumulando historico — assim
        a troca depois nao tem periodo cego. Ponto unico: todo caminho (chat, voz,
        Discord, terminal) passa por append_event.

        Evento de sistema/ferramenta nao entra: `messages` so aceita user e
        assistant. Falha aqui nunca pode derrubar o turno.
        """
        # Eventos do Terminal são projeções para a interface. A fala real já foi
        # persistida no canal de origem e não pode ser espelhada outra vez.
        if isinstance(metadata, dict) and metadata.get("conversation") is False:
            return
        papel = self._ROLE_MAP.get(str(role).strip().lower())
        canal = self._CHANNEL_MAP.get(str(channel).strip().lower())
        texto = str(content or "").strip()
        if not (papel and canal and texto):
            return
        try:
            from backend.memory.core import HanaMemory

            if getattr(self, "_short_term", None) is None:
                self._short_term = HanaMemory(str(self.db_path))
            self._short_term.add_message(
                role=papel,
                author="Nakamura" if papel == "user" else "Hana",
                content=texto,
                channel=canal,
            )
        except Exception:
            # warning, nao debug: `debug` fica fora do nivel padrao de log, entao
            # o espelho podia parar de funcionar por semanas sem ninguem ver.
            logger.warning("Falha ao espelhar fala na memoria curta", exc_info=True)


    def _mirror_to_chat_log(
        self, role: str, content: str, channel: str, metadata: dict[str, Any] | None
    ) -> None:
        """Grava o evento no historico da TELA (`chat_log`).

        Diferenca pra `messages`: aqui entra TUDO — ferramenta, pensamento, erro,
        imagem, evento de sistema. Esta tabela nunca vai pra LLM, entao nao custa
        token nem suja contexto; serve so pra remontar a tela igual voce deixou.

        A sessao e `<canal>-<data>`: abrir o app carrega a conversa de hoje, e
        cada canal fica na sua. Sem isso o Discord e o painel virariam uma sopa
        so na tela de historico.
        """
        texto = str(content or "").strip()
        if not texto:
            return
        try:
            from backend.memory.core import HanaMemory

            if getattr(self, "_short_term", None) is None:
                self._short_term = HanaMemory(str(self.db_path))
            canal = self._CHANNEL_MAP.get(str(channel).strip().lower(), "chat")
            self._short_term.log_chat(
                session_id=f"{canal}-{datetime.now().strftime('%Y-%m-%d')}",
                role=str(role).strip().lower() or "system",
                author="Nakamura" if self._ROLE_MAP.get(str(role).strip().lower()) == "user" else "Hana",
                content=texto,
                channel=canal,
                meta=metadata or None,
            )
        except Exception:
            logger.warning("Falha ao gravar no historico do front", exc_info=True)


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

