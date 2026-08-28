"""Validações temporárias do catálogo unificado."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.bd import preparar_catalogos
from backend.catalog.repository import LlmModelRepository
from backend.catalog.stt_repository import SttModelRepository
from backend.catalog.tts_repository import TtsModelRepository
from backend.validation import validation_result

CATALOG_TABLES = ("llm_models", "tts_models", "stt_models", "model_overrides")
LEGACY_TABLES = ("provider_models", "schema_info")


def _read_only(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def validate_principal_catalog(db_path: str | Path) -> dict[str, Any]:
    """Confere o banco real sem listar nomes nem alterar qualquer linha."""

    path = Path(db_path).resolve()
    if not path.is_file():
        return validation_result(
            test="catalogo_principal_somente_leitura",
            database="principal (somente leitura)",
            approved=False,
            evidence={"banco_existe": False},
            failure_next_step="Inicie a Hana e execute novamente.",
        )

    with closing(_read_only(path)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = sorted(set(CATALOG_TABLES) - tables)
        legacy = sorted(set(LEGACY_TABLES) & tables)
        counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in CATALOG_TABLES
            if table in tables
        }
        providers = {
            table: {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    f'SELECT provider, COUNT(*) FROM "{table}" GROUP BY provider'
                )
            }
            for table in ("llm_models", "tts_models", "stt_models")
            if table in tables
        }
        parallel_setting = (
            "settings" in tables
            and connection.execute(
                "SELECT 1 FROM settings WHERE key='custom_models'"
            ).fetchone()
            is not None
        )
        query_only = bool(connection.execute("PRAGMA query_only").fetchone()[0])

    approved = query_only and not missing and not legacy and not parallel_setting
    return validation_result(
        test="catalogo_principal_somente_leitura",
        database="principal (somente leitura)",
        approved=approved,
        evidence={
            "conexao_bloqueada_para_escrita": query_only,
            "tabelas_ausentes": missing,
            "tabelas_legadas": legacy,
            "lista_paralela_em_settings": parallel_setting,
            "contagens": counts,
            "contagens_por_provider": providers,
        },
        failure_next_step="Não avance; confira a tabela ou lista paralela indicada.",
    )


def validate_temporary_catalog() -> dict[str, Any]:
    """Prova migração, leitura e limpeza usando só um banco descartável."""

    temp_root: Path | None = None
    evidence: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="hana-catalogo-validacao-") as temp_dir:
            temp_root = Path(temp_dir)
            db_path = temp_root / "hana.sqlite3"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT);
                    CREATE TABLE schema_info (id INTEGER PRIMARY KEY, version INTEGER NOT NULL);
                    CREATE TABLE provider_models (
                      provider TEXT NOT NULL, model_id TEXT NOT NULL, label TEXT,
                      supports_vision INTEGER, custom INTEGER,
                      PRIMARY KEY(provider, model_id)
                    );
                    INSERT INTO provider_models VALUES ('legacy','modelo-legado','Legado',1,0);
                    INSERT INTO settings VALUES ('custom_models','[]',datetime('now'));
                    """
                )
                connection.execute(
                    "UPDATE settings SET value_json=? WHERE key='custom_models'",
                    (json.dumps([{"provider": "manual", "id": "modelo-manual", "label": "Manual", "supportsTools": True}]),),
                )
                connection.commit()

            first = preparar_catalogos(db_path)
            second = preparar_catalogos(db_path)
            llm = LlmModelRepository(db_path)
            legacy_model = llm.get_model("legacy", "modelo-legado")
            manual_model = llm.get_model("manual", "modelo-manual")
            with closing(sqlite3.connect(db_path)) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                custom_setting = connection.execute(
                    "SELECT 1 FROM settings WHERE key='custom_models'"
                ).fetchone()

            checks = {
                "linha_legada_preservada": bool(legacy_model and legacy_model["supportsVision"]),
                "modelo_manual_migrado": bool(manual_model and manual_model["custom"]),
                "tres_catalogos_legiveis": (
                    isinstance(llm.list_models(), list)
                    and isinstance(TtsModelRepository(db_path).list_models(), list)
                    and isinstance(SttModelRepository(db_path).list_models(), list)
                ),
                "legado_removido": not (set(LEGACY_TABLES) & tables),
                "lista_paralela_removida": custom_setting is None,
                "segunda_execucao_neutra": not any(second.values()),
                "primeira_execucao_migrou": first == {
                    "legacy_models_migrated": 1,
                    "custom_models_migrated": 1,
                },
            }
            evidence.update(checks)

        evidence["banco_temporario_removido"] = bool(temp_root and not temp_root.exists())
        return validation_result(
            test="catalogo_com_migracao_temporaria",
            database="temporário descartável",
            approved=all(evidence.values()),
            evidence=evidence,
            failure_next_step="Não avance; identifique a verificação falsa.",
        )
    except Exception as exc:  # noqa: BLE001
        evidence["erro_seguro"] = type(exc).__name__
        evidence["banco_temporario_removido"] = bool(temp_root and not temp_root.exists())
        return validation_result(
            test="catalogo_com_migracao_temporaria",
            database="temporário descartável",
            approved=False,
            evidence=evidence,
            failure_next_step="Consulte o log local; o banco principal não foi usado.",
        )
