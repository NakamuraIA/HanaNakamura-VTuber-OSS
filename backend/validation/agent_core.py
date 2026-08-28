"""Validação temporária da persistência do Agent Core no banco único."""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.bd.agent_core import AGENT_CORE_TABLES
from backend.core.runtime import HanaAgentCore
from backend.memory.core import HanaMemory
from backend.memory.storage import RuntimeStore
from backend.validation import validation_result

logger = logging.getLogger(__name__)


def validate_temporary_agent_core() -> dict[str, Any]:
    """Executa dois turnos seguros num banco temporário e remove tudo ao final."""

    temp_root: Path | None = None
    evidence: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="hana-agent-core-validacao-") as temp_dir:
            temp_root = Path(temp_dir)
            db_path = temp_root / "hana.sqlite3"
            canonical = HanaMemory(str(db_path))
            canonical.add_message(
                role="user",
                author="Naka",
                content="mensagem canonica temporaria",
                channel="chat",
            )

            store = RuntimeStore(db_path)
            core = HanaAgentCore(store=store)
            tools_turn = core.run("tools")
            file_turn = core.run(f'file.exists "{Path(__file__).resolve()}"')
            counts = store.counts()
            context_has_file = bool(store.load_working_context().preferred_file())
            canonical_unchanged = len(canonical.recent_messages("chat")) == 1

            with closing(sqlite3.connect(db_path)) as conn:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            namespaced_tables = set(AGENT_CORE_TABLES) <= tables
            expected_counts = {
                "messages": 4,
                "events": 7,
                "tool_runs": 1,
                "working_context": 1,
            }
            checks = {
                "turno_sem_ferramenta": tools_turn.ok,
                "turno_com_ferramenta": file_turn.ok,
                "tabelas_com_prefixo_agent_core": namespaced_tables,
                "mensagem_canonica_preservada": canonical_unchanged,
                "contexto_de_trabalho_recuperado": context_has_file,
                "persistencia_agent_core_completa": counts == expected_counts,
            }
            evidence = {**checks, "contagens_agent_core": counts}

        evidence["banco_temporario_removido"] = bool(temp_root and not temp_root.exists())
        approved = all(checks.values()) and evidence["banco_temporario_removido"]
        return validation_result(
            test="agent_core_no_banco_unico",
            database="temporário descartável",
            approved=approved,
            evidence=evidence,
            failure_next_step="Não avance; confira qual item do Agent Core ficou falso.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha na validação temporária do Agent Core")
        if temp_root is not None:
            evidence["banco_temporario_removido"] = not temp_root.exists()
        evidence["erro_seguro"] = type(exc).__name__
        return validation_result(
            test="agent_core_no_banco_unico",
            database="temporário descartável",
            approved=False,
            evidence=evidence,
            failure_next_step="Consulte o log local; o banco principal não foi usado para escrita.",
        )
