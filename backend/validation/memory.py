"""Validações temporárias da memória, sem alterar o banco principal."""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from backend.bd.agent_core import AGENT_CORE_TABLES
from backend.api.services.unified_history import (
    CHANNEL_CONTROL_CENTER,
    CHANNEL_DISCORD,
    CHANNEL_TERMINAL_AGENT,
    CHANNEL_VOICE,
    build_unified_history,
    select_memories_for_context,
)
from backend.memory.core import CHANNELS, HanaMemory, build_prompt_messages
from backend.memory.long_term.sleep import SLEEP_SETTING_KEY, latest_episode
from backend.memory.store import MemoryStore
from backend.validation import validation_result

logger = logging.getLogger(__name__)

EXPECTED_TABLES = (
    "messages",
    "pinned",
    "chat_log",
    "settings",
    "memory_items",
    "memory_fts",
    "memory_embeddings",
    "memory_links",
) + AGENT_CORE_TABLES
VALID_EVENT_CHANNELS = {
    CHANNEL_CONTROL_CENTER,
    "chat",
    CHANNEL_DISCORD,
    CHANNEL_TERMINAL_AGENT,
    "terminal",
    CHANNEL_VOICE,
}


class _ClosingReadOnlyConnection(sqlite3.Connection):
    """Fecha a conexão e impede que um teste deixe o banco preso no Windows."""

    def __exit__(self, *exc: object) -> None:
        try:
            super().__exit__(*exc)  # type: ignore[arg-type]
        finally:
            self.close()


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        factory=_ClosingReadOnlyConnection,
        timeout=15.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


class _ReadOnlyMemoryStore(MemoryStore):
    """Usa os algoritmos reais do MemoryStore sem executar sua inicialização."""

    def __init__(self, db_path: str | Path, events_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.events_path = Path(events_path).resolve()

    def _connect(self) -> sqlite3.Connection:
        return _read_only_connection(self.db_path)


class _ReadOnlyHanaMemory(HanaMemory):
    """Permite validar a montagem do prompt sem criar ou migrar tabelas."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()

    def _connect(self) -> sqlite3.Connection:
        return _read_only_connection(self.db_path)


class _EventSource:
    """Entrega eventos isolados ao construtor real do histórico canônico."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    def recent_events(self, *, limit: int = 50, channel: str | None = None) -> list[dict[str, Any]]:
        events = self._events
        if channel is not None:
            events = [item for item in events if item.get("channel") == channel]
        return events[-limit:]


def _event_request_channel(event_channel: str) -> str:
    value = str(event_channel or "").strip().lower()
    if value == CHANNEL_DISCORD:
        return CHANNEL_DISCORD
    if value in {CHANNEL_TERMINAL_AGENT, "terminal", CHANNEL_VOICE}:
        return CHANNEL_TERMINAL_AGENT
    return CHANNEL_CONTROL_CENTER


def _conversation_false_is_filtered(events: list[dict[str, Any]]) -> bool:
    visual_events = [
        event
        for event in events
        if isinstance(event.get("metadata"), dict)
        and event["metadata"].get("conversation") is False
    ]
    if not visual_events:
        visual_events = [
            {
                "id": "validacao-sintetica",
                "role": "assistant",
                "content": "evento visual sintetico",
                "channel": CHANNEL_CONTROL_CENTER,
                "metadata": {"conversation": False},
                "created_at": "2000-01-01T00:00:00+00:00",
            }
        ]

    for event in visual_events:
        history = build_unified_history(
            _EventSource([event]),  # type: ignore[arg-type]
            channel=_event_request_channel(str(event.get("channel") or "")),
            limit=10,
        )
        if history:
            return False
    return True


def _count_visual_chat_log(conn: sqlite3.Connection) -> int:
    total = 0
    for row in conn.execute("SELECT meta_json FROM chat_log WHERE meta_json IS NOT NULL"):
        try:
            metadata = json.loads(row["meta_json"])
        except (TypeError, ValueError):
            continue
        if isinstance(metadata, dict) and metadata.get("conversation") is False:
            total += 1
    return total


def validate_principal_memory(
    db_path: str | Path,
    events_path: str | Path,
    *,
    query: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """Lê o estado real com conexões SQLite que recusam qualquer escrita."""

    database_path = Path(db_path).resolve()
    if not database_path.is_file():
        return validation_result(
            test="memoria_principal_somente_leitura",
            database="principal (somente leitura)",
            approved=False,
            evidence={"banco_existe": False},
            failure_next_step="Inicie a Hana para criar o banco e execute novamente.",
        )

    try:
        store = _ReadOnlyMemoryStore(database_path, events_path)
        fixed_memory = _ReadOnlyHanaMemory(database_path)
        with _read_only_connection(database_path) as conn:
            query_only = bool(conn.execute("PRAGMA query_only").fetchone()[0])
            present = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
            }
            missing = [table for table in EXPECTED_TABLES if table not in present]
            counts = {
                table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                for table in EXPECTED_TABLES
                if table in present
            }
            status_counts = (
                {
                    str(row["status"]): int(row["total"])
                    for row in conn.execute(
                        "SELECT status, COUNT(*) AS total FROM memory_items GROUP BY status"
                    )
                }
                if "memory_items" in present
                else {}
            )
            kind_counts = (
                {
                    str(row["kind"]): int(row["total"])
                    for row in conn.execute(
                        "SELECT kind, COUNT(*) AS total FROM memory_items GROUP BY kind"
                    )
                }
                if "memory_items" in present
                else {}
            )
            channel_counts = (
                {
                    str(row["channel"]): int(row["total"])
                    for row in conn.execute(
                        "SELECT channel, COUNT(*) AS total FROM messages GROUP BY channel"
                    )
                }
                if "messages" in present
                else {}
            )
            invalid_channels = sorted(set(channel_counts) - set(CHANNELS))
            visual_chat_log = _count_visual_chat_log(conn) if "chat_log" in present else 0

        raw_events = store.recent_events(limit=2000)
        event_channel_counts = Counter(str(event.get("channel") or "") for event in raw_events)
        invalid_event_channels = sorted(set(event_channel_counts) - VALID_EVENT_CHANNELS)
        visual_events = sum(
            1
            for event in raw_events
            if isinstance(event.get("metadata"), dict)
            and event["metadata"].get("conversation") is False
        )
        visual_contract = _conversation_false_is_filtered(raw_events)

        safe_limit = max(1, min(int(limit or 8), 20))
        selected = select_memories_for_context(
            store,
            query=str(query or "").strip(),
            max_items=safe_limit,
        )
        safe_selection = [
            {
                "id": item.get("id"),
                "tipo": item.get("kind"),
                "categoria": item.get("category"),
                "status": item.get("status"),
                "fixada": bool(item.get("pinned")),
                "pontuacao": item.get("score"),
            }
            for item in selected
        ]

        pinned = fixed_memory.list_pinned()
        prompt = build_prompt_messages(
            fixed_memory,
            channel="chat",
            pergunta="validacao interna",
            system_prompt="validacao interna",
            limit=1,
        )
        system_block = str(prompt[0].get("content") or "")
        fixed_block_ok = all(str(item["text"]) in system_block for item in pinned)
        if pinned:
            fixed_block_ok = fixed_block_ok and "[REGRAS FIXAS DA NAKAMURA" in system_block

        sleep_state = store.get_setting(SLEEP_SETTING_KEY, {}) or {}
        episode = latest_episode(store)
        approved = (
            query_only
            and not missing
            and not invalid_channels
            and not invalid_event_channels
            and visual_contract
            and fixed_block_ok
        )
        return validation_result(
            test="memoria_principal_somente_leitura",
            database="principal (somente leitura)",
            approved=approved,
            evidence={
                "conexao_bloqueada_para_escrita": query_only,
                "tabelas": {"presentes": len(EXPECTED_TABLES) - len(missing), "ausentes": missing},
                "contagens_por_tabela": counts,
                "memoria_longa_por_status": status_counts,
                "memoria_longa_por_tipo": kind_counts,
                "canais": {
                    "mensagens": {"contagens": channel_counts, "invalidos": invalid_channels},
                    "eventos_recentes": {
                        "contagens": dict(event_channel_counts),
                        "invalidos": invalid_event_channels,
                    },
                },
                "conversation_false": {
                    "eventos_no_runtime": visual_events,
                    "registros_no_historico_visual": visual_chat_log,
                    "fora_da_conversa_canonica": visual_contract,
                },
                "selecao_de_memoria": safe_selection,
                "memoria_fixa": {"ativas": len(pinned), "bloco_confirmado": fixed_block_ok},
                "ciclo_de_sono": {
                    "ultimo_ciclo": sleep_state.get("lastRunAt"),
                    "ultimo_episodio_id": episode.get("id") if episode else None,
                },
            },
            failure_next_step="Confira o item marcado como falso ou ausente antes de migrar a memória.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha na validação somente leitura da memória")
        return validation_result(
            test="memoria_principal_somente_leitura",
            database="principal (somente leitura)",
            approved=False,
            evidence={"erro_seguro": type(exc).__name__},
            failure_next_step="Consulte o log local da Hana; a resposta não expõe caminhos ou dados privados.",
        )


def validate_temporary_memory() -> dict[str, Any]:
    """Executa escritas apenas dentro de uma pasta temporária removida no final."""

    temp_root: Path | None = None
    evidence: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="hana-validacao-") as temp_dir:
            temp_root = Path(temp_dir)
            db_path = temp_root / "memoria.sqlite3"
            events_path = temp_root / "eventos.jsonl"
            store = MemoryStore(db_path=db_path, events_path=events_path)
            short_memory = HanaMemory(str(db_path))
            store._short_term = short_memory

            saved = store.add_memory(
                "amostra segura da validacao temporaria",
                kind="validation",
                source="internal_validation",
            )
            found = store.search("", limit=10, touch=False)
            save_and_search = any(item.get("id") == saved.get("id") for item in found)

            archived = store.archive_memory(str(saved["id"]))
            archived_status = (store.get_memory(str(saved["id"])) or {}).get("status") == "archived"
            restored = store.restore_memory(str(saved["id"]))
            restored_status = (store.get_memory(str(saved["id"])) or {}).get("status") == "active"

            fixed_marker = "regra temporaria da validacao"
            short_memory.add_pinned(fixed_marker, position=1)
            prompt = build_prompt_messages(
                short_memory,
                channel="chat",
                pergunta="validacao",
                system_prompt="validacao",
                limit=1,
            )
            fixed_in_prompt = fixed_marker in str(prompt[0].get("content") or "")

            visual_marker = "projecao visual temporaria"
            voice_marker = "fala canonica temporaria"
            chat_marker = "canal chat temporario"
            discord_marker = "canal discord temporario"
            store.append_event(
                "assistant",
                visual_marker,
                channel="terminal_agent",
                metadata={"conversation": False, "kind": "assistant_speech"},
            )
            store.append_event("assistant", voice_marker, channel="voice", metadata={"conversation": True})
            store.append_event("user", chat_marker, channel="control_center", metadata={"conversation": True})
            store.append_event("user", discord_marker, channel="discord", metadata={"conversation": True})

            terminal_history = build_unified_history(store, channel=CHANNEL_TERMINAL_AGENT, limit=20)
            chat_history = build_unified_history(store, channel=CHANNEL_CONTROL_CENTER, limit=20)
            discord_history = build_unified_history(store, channel=CHANNEL_DISCORD, limit=20)
            terminal_text = "\n".join(str(item.get("content") or "") for item in terminal_history)
            chat_text = "\n".join(str(item.get("content") or "") for item in chat_history)
            discord_text = "\n".join(str(item.get("content") or "") for item in discord_history)

            visual_not_canonical = visual_marker not in terminal_text and voice_marker in terminal_text
            channel_isolation = (
                chat_marker in chat_text
                and discord_marker not in chat_text
                and discord_marker in discord_text
                and chat_marker not in discord_text
            )
            evidence = {
                "salvar_e_buscar": save_and_search,
                "arquivar": archived and archived_status,
                "restaurar": restored and restored_status,
                "memoria_fixa_no_prompt": fixed_in_prompt,
                "evento_visual_fora_da_conversa": visual_not_canonical,
                "isolamento_entre_canais": channel_isolation,
            }

        evidence["banco_temporario_removido"] = bool(temp_root and not temp_root.exists())
        approved = all(evidence.values())
        return validation_result(
            test="memoria_com_escrita_temporaria",
            database="temporário descartável",
            approved=approved,
            evidence=evidence,
            failure_next_step="Não avance a migração; identifique qual verificação temporária ficou falsa.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha na validação temporária da memória")
        if temp_root is not None:
            evidence["banco_temporario_removido"] = not temp_root.exists()
        evidence["erro_seguro"] = type(exc).__name__
        return validation_result(
            test="memoria_com_escrita_temporaria",
            database="temporário descartável",
            approved=False,
            evidence=evidence,
            failure_next_step="Consulte o log local; nenhum dado foi escrito no banco principal.",
        )
