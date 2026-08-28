"""Cria e migra o catálogo de LLM no banco principal."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

# Domínios fechados de um modelo do catálogo. "chat" é conversa (inclui
# multimodais de entrada tipo VL/omni); image/embedding/rerank são
# especializados que NÃO podem ser enviados ao endpoint de conversa.
MODEL_DOMAINS = ("chat", "image", "embedding", "rerank")

# Disponibilidade confirmada pelos dois endpoints configurados da Hana.
# O identificador técnico não muda; a etiqueta existe só para a pessoa saber
# qual região pode usar. Modelos fora deste mapa não foram confirmados.
QWEN_REGION_METADATA: dict[str, dict[str, Any]] = {
    "deepseek-v4-pro": {"label": "DeepSeek V4 Pro — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"], "deploymentScope": "global"},
    "deepseek-v4-pro-us": {"label": "DeepSeek V4 Pro US — Virgínia", "availableRegions": ["virginia"], "deploymentScope": "international"},
    "deepseek-v4-flash": {"label": "DeepSeek V4 Flash — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"], "deploymentScope": "global"},
    "deepseek-v4-flash-us": {"label": "DeepSeek V4 Flash US — Virgínia", "availableRegions": ["virginia"], "deploymentScope": "international"},
    "deepseek-v3.2": {"label": "DeepSeek V3.2 — Singapura", "availableRegions": ["singapore"]},
    "deepseek-v4-flash-0731": {"label": "DeepSeek V4 Flash 0731 — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"], "deploymentScope": "global"},
    "qwen-flash": {"label": "Qwen Flash — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen-plus": {"label": "Qwen Plus — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3-vl-flash": {"label": "Qwen3 VL Flash — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3-vl-plus": {"label": "Qwen3 VL Plus — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3.5-flash": {"label": "Qwen3.5 Flash — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3.5-omni-plus": {"label": "Qwen3.5 Omni Plus — Singapura", "availableRegions": ["singapore"]},
    "qwen3.5-omni-plus-realtime": {"label": "Qwen3.5 Omni Plus Realtime — Singapura", "availableRegions": ["singapore"]},
    "qwen3.5-plus": {"label": "Qwen3.5 Plus — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3.6-35b-a3b": {"label": "Qwen3.6 35B A3B — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3.6-flash": {"label": "Qwen3.6 Flash — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3.6-max-preview": {"label": "Qwen3.6 Max Preview — Singapura", "availableRegions": ["singapore"]},
    "qwen3.6-plus": {"label": "Qwen3.6 Plus — Singapura", "availableRegions": ["singapore"]},
    "qwen3.7-flash": {"label": "Qwen3.7 Flash — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3.7-max": {"label": "Qwen3.7 Max — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3.7-plus": {"label": "Qwen3.7 Plus — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
    "qwen3.8-flash": {"label": "Qwen3.8 Flash — Singapura", "availableRegions": ["singapore"], "deploymentScope": "international"},
    "qwen3.8-max": {"label": "Qwen3.8 Max — Virgínia e Singapura", "availableRegions": ["virginia", "singapore"]},
}


def normalizar_model_domain(value: Any) -> str:
    """Devolve sempre um domínio válido; vazio/inválido = 'chat'."""
    text = str(value or "").strip().lower()
    return text if text in MODEL_DOMAINS else "chat"


def criar_tabela_llm(conexao: sqlite3.Connection) -> None:
    """Cria (se nao existir) a tabela llm_models.

    Uma linha por (provider, model_id) — o id e sempre relativo ao provider
    (ver DECISOES_CATALOGO_FONTES.md secao 7). Capacidade e por modelo, nao
    por provider (o bug do Qwen que gerou essa regra: supports_video fixo em
    False no codigo antigo, errado pro qwen3.6-flash).
    """
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_models (
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            model_domain TEXT NOT NULL DEFAULT 'chat',

            supports_vision INTEGER,
            supports_video INTEGER,
            supports_tools INTEGER,
            supports_streaming INTEGER,
            supports_streaming_tools INTEGER,
            supports_reasoning INTEGER,
            reasoning_modes TEXT,
            supports_structured_output INTEGER,
            supports_documents INTEGER,
            supports_native_search INTEGER,

            max_input_tokens INTEGER,
            max_output_tokens INTEGER,
            free INTEGER,
            pricing TEXT,
            input_modalities TEXT,
            output_modalities TEXT,
            supported_parameters TEXT,
            description TEXT,

            custom INTEGER NOT NULL DEFAULT 0,
            capabilities TEXT,
            field_sources TEXT,

            source TEXT NOT NULL DEFAULT 'manual',
            observed_at TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            lifecycle_status TEXT NOT NULL DEFAULT 'active',
            missing_success_count INTEGER NOT NULL DEFAULT 0,

            PRIMARY KEY (provider, model_id)
        )
        """
    )

    existing = {str(row[1]) for row in conexao.execute("PRAGMA table_info(llm_models)")}
    for column, definition in (
        ("custom", "INTEGER NOT NULL DEFAULT 0"),
        ("capabilities", "TEXT"),
        ("field_sources", "TEXT"),
        ("missing_success_count", "INTEGER NOT NULL DEFAULT 0"),
        ("model_domain", "TEXT NOT NULL DEFAULT 'chat'"),
    ):
        if column not in existing:
            conexao.execute(f"ALTER TABLE llm_models ADD COLUMN {column} {definition}")

    # Classificacao idempotente dos 4 modelos publicos especializados conhecidos.
    # O WHERE model_domain='chat' protege qualquer mudanca deliberada de dominio
    # feita pela dona (a migracao nunca sobrescreve um valor escolhido).
    conexao.execute(
        """
        UPDATE llm_models SET model_domain = 'embedding'
        WHERE provider = 'qwen' AND model_id IN ('text-embedding-v4', 'tongyi-embedding-vision-plus')
          AND model_domain = 'chat'
        """
    )
    conexao.execute(
        """
        UPDATE llm_models SET model_domain = 'rerank'
        WHERE provider = 'qwen' AND model_id = 'qwen3-rerank'
          AND model_domain = 'chat'
        """
    )
    conexao.execute(
        """
        UPDATE llm_models SET model_domain = 'image'
        WHERE provider = 'qwen' AND model_id = 'qwen-image-2.0-pro'
          AND model_domain = 'chat'
        """
    )

    # Correcao manual de um campo. Fica separada pra nunca sobrescrever o dado
    # observado: o valor efetivo e a soma dos dois, calculada na leitura.
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS model_overrides (
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (provider, model_id, field_name)
        )
        """
    )
    conexao.commit()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _apply_qwen_region_metadata(connection: sqlite3.Connection) -> int:
    """Atualiza somente linhas públicas que ainda não receberam ajuste manual."""

    changed = 0
    for model_id, metadata in QWEN_REGION_METADATA.items():
        row = connection.execute(
            """
            SELECT capabilities FROM llm_models
            WHERE provider = 'qwen' AND model_id = ? AND custom = 0 AND source = 'public_default'
              AND NOT EXISTS (
                  SELECT 1 FROM model_overrides
                  WHERE provider = 'qwen' AND model_id = ? AND field_name = 'label'
              )
            """,
            (model_id, model_id),
        ).fetchone()
        if row is None:
            continue
        try:
            capabilities = json.loads(row[0]) if row[0] else {}
        except (TypeError, ValueError):
            capabilities = {}
        capabilities.update({key: value for key, value in metadata.items() if key != "label"})
        cursor = connection.execute(
            """
            UPDATE llm_models SET label = ?, capabilities = ?, fetched_at = datetime('now')
            WHERE provider = 'qwen' AND model_id = ?
            """,
            (metadata["label"], json.dumps(capabilities, ensure_ascii=False), model_id),
        )
        changed += cursor.rowcount
    return changed


def _copy_legacy_provider_models(connection: sqlite3.Connection) -> int:
    """Copia linhas ausentes do catálogo antigo e só então remove a tabela."""

    if not _table_exists(connection, "provider_models"):
        return 0
    source_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(provider_models)")
    }
    if not {"provider", "model_id"} <= source_columns:
        raise sqlite3.DatabaseError("provider_models não possui provider/model_id")

    targets = (
        "provider", "model_id", "label", "supports_vision", "supports_video",
        "supports_tools", "supports_streaming", "supports_streaming_tools",
        "supports_reasoning", "reasoning_modes", "supports_structured_output",
        "supports_documents", "supports_native_search", "max_input_tokens",
        "max_output_tokens", "free", "pricing", "input_modalities",
        "output_modalities", "supported_parameters", "description", "custom",
        "capabilities", "field_sources", "source", "observed_at", "fetched_at",
        "lifecycle_status", "missing_success_count",
    )
    defaults = {
        "label": "model_id",
        "custom": "0",
        "source": "'legacy_migration'",
        "fetched_at": "datetime('now')",
        "lifecycle_status": "'active'",
        "missing_success_count": "0",
    }
    expressions = [
        f'"{column}"' if column in source_columns else defaults.get(column, "NULL")
        for column in targets
    ]
    before = connection.total_changes
    connection.execute(
        f"INSERT INTO llm_models ({','.join(targets)}) "
        f"SELECT {','.join(expressions)} FROM provider_models WHERE 1 "
        "ON CONFLICT(provider, model_id) DO NOTHING"
    )
    copied = connection.total_changes - before
    connection.execute("DROP TABLE provider_models")
    return copied


def _migrate_custom_models_setting(connection: sqlite3.Connection) -> int:
    """Move a lista paralela de settings para llm_models sem perder modelos."""

    if not _table_exists(connection, "settings"):
        return 0
    row = connection.execute(
        "SELECT value_json FROM settings WHERE key='custom_models'"
    ).fetchone()
    if row is None:
        return 0
    try:
        models = json.loads(row[0])
    except (TypeError, ValueError):
        return 0
    if not isinstance(models, list):
        return 0

    migrated = 0
    for item in models:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        model_id = str(item.get("id") or "").strip()
        if not provider or not model_id:
            continue
        connection.execute(
            """
            INSERT INTO llm_models (
              provider, model_id, label, supports_vision, supports_tools,
              supports_documents, supports_native_search, max_input_tokens,
              max_output_tokens, input_modalities, output_modalities,
              supported_parameters, custom, source, fetched_at, lifecycle_status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,'manual',datetime('now'),'active')
            ON CONFLICT(provider, model_id) DO UPDATE SET
              label=excluded.label,
              supports_vision=excluded.supports_vision,
              supports_tools=excluded.supports_tools,
              supports_documents=excluded.supports_documents,
              supports_native_search=excluded.supports_native_search,
              max_input_tokens=excluded.max_input_tokens,
              max_output_tokens=excluded.max_output_tokens,
              input_modalities=excluded.input_modalities,
              output_modalities=excluded.output_modalities,
              supported_parameters=excluded.supported_parameters,
              custom=1,
              source='manual',
              fetched_at=datetime('now')
            """,
            (
                provider,
                model_id,
                str(item.get("label") or model_id),
                int(bool(item.get("supportsVision"))),
                int(bool(item.get("supportsTools"))),
                int(bool(item.get("supportsDocuments"))),
                int(bool(item.get("supportsNativeSearch"))),
                item.get("maxInputTokens"),
                item.get("maxOutputTokens"),
                json.dumps(item.get("inputModalities") or ["text"], ensure_ascii=False),
                json.dumps(item.get("outputModalities") or ["text"], ensure_ascii=False),
                json.dumps(item.get("supportedParameters") or [], ensure_ascii=False),
            ),
        )
        migrated += 1
    connection.execute("DELETE FROM settings WHERE key='custom_models'")
    return migrated


def migrar_catalogo_llm(db_path: str | Path) -> dict[str, Any]:
    """Aplica a migração explícita e idempotente do catálogo antigo."""

    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Banco do catálogo não encontrado: {path}")
    with closing(sqlite3.connect(path)) as connection:
        criar_tabela_llm(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            legacy_models = _copy_legacy_provider_models(connection)
            custom_models = _migrate_custom_models_setting(connection)
            _apply_qwen_region_metadata(connection)
            if _table_exists(connection, "schema_info"):
                connection.execute("DROP TABLE schema_info")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "legacy_models_migrated": legacy_models,
        "custom_models_migrated": custom_models,
    }
