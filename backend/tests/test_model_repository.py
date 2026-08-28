"""Testes isolados da primeira etapa do catálogo unificado."""

import json
import sqlite3

from backend.bd.llm import criar_tabela_llm
from backend.bd import preparar_catalogos
from backend.catalog.repository import LlmModelRepository


def _create_models_db(path) -> None:
    """Cria a tabela pelo dono dela (``bd/llm.py``) e insere um modelo de teste."""
    with sqlite3.connect(path) as connection:
        criar_tabela_llm(connection)
        connection.execute(
            """
            INSERT INTO llm_models (
                provider, model_id, label, supports_tools, max_input_tokens,
                supported_parameters, supports_streaming
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "deepseek",
                "deepseek-test",
                "DeepSeek Teste",
                1,
                128000,
                json.dumps(["tools", "tool_choice"]),
                1,
            ),
        )


def test_repository_lista_modelo_e_capacidades(tmp_path) -> None:
    """Confirma que o repositório lê campos normais e capacidades extras."""
    database = tmp_path / "models.sqlite3"
    _create_models_db(database)

    models = LlmModelRepository(database).list_models("deepseek")

    assert models[0]["id"] == "deepseek-test"
    assert models[0]["supportsTools"] is True
    assert models[0]["supportsStreaming"] is True


def test_repository_busca_modelo_exato(tmp_path) -> None:
    """Confirma a busca por provider e id sem permitir escrita no banco."""
    database = tmp_path / "models.sqlite3"
    _create_models_db(database)

    model = LlmModelRepository(database).get_model("deepseek", "deepseek-test")

    assert model is not None
    assert LlmModelRepository(database).get_model("groq", "deepseek-test") is None


def test_repository_preserva_observacao_ao_aplicar_e_remover_correcao_manual(tmp_path) -> None:
    """Confirma que uma correção manual não apaga o valor obtido da fonte."""
    database = tmp_path / "models.sqlite3"
    _create_models_db(database)
    repository = LlmModelRepository(database)

    repository.ensure_schema()
    repository.set_override("deepseek", "deepseek-test", "maxInputTokens", 256000)

    corrected = repository.get_model("deepseek", "deepseek-test")
    assert corrected is not None
    assert corrected["maxInputTokens"] == 256000
    assert corrected["manualOverrides"] == ["maxInputTokens"]

    assert repository.remove_override("deepseek", "deepseek-test", "maxInputTokens") is True
    restored = repository.get_model("deepseek", "deepseek-test")
    assert restored is not None
    assert restored["maxInputTokens"] == 128000


def test_repository_le_colunas_dedicadas_de_capacidade(tmp_path) -> None:
    """Trava o bug do Qwen: capacidade vem por MODELO, não chutada por provider.

    ``supports_video`` fixo em False no código mentia sobre o qwen3.6-flash.
    Cada capacidade tem coluna própria e o repositório precisa ler todas.
    """
    database = tmp_path / "models.sqlite3"
    _create_models_db(database)
    repository = LlmModelRepository(database)

    repository.ensure_schema()
    repository.ensure_schema()  # idempotente: rodar duas vezes não quebra
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(llm_models)")}
        connection.execute(
            """
            UPDATE llm_models
            SET supports_video = 1,
                supports_streaming = 1,
                supports_streaming_tools = 0,
                supports_reasoning = 1,
                supports_structured_output = 1,
                source = 'official_api'
            WHERE provider = 'deepseek' AND model_id = 'deepseek-test'
            """
        )
        connection.commit()

    assert {
        "supports_video",
        "supports_streaming",
        "supports_streaming_tools",
        "supports_reasoning",
        "supports_structured_output",
    } <= columns

    model = repository.get_model("deepseek", "deepseek-test")
    assert model is not None
    assert model["supportsVideo"] is True
    assert model["supportsStreaming"] is True
    assert model["supportsStreamingTools"] is False
    assert model["supportsReasoning"] is True
    assert model["supportsStructuredOutput"] is True
    assert model["source"] == "official_api"


def test_migracao_legada_preserva_dados_remove_paralelos_e_e_idempotente(tmp_path) -> None:
    """Confirma a troca explícita sem recriar o catálogo antigo."""
    database = tmp_path / "runtime" / "hana_memory.sqlite3"
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
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
            """
        )
        connection.execute(
            "INSERT INTO settings VALUES ('custom_models', ?, datetime('now'))",
            (json.dumps([{"provider": "manual", "id": "modelo-manual", "supportsTools": True}]),),
        )

    first = preparar_catalogos(database)
    second = preparar_catalogos(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        custom_setting = connection.execute(
            "SELECT 1 FROM settings WHERE key='custom_models'"
        ).fetchone()

    repository = LlmModelRepository(database)
    assert first == {"legacy_models_migrated": 1, "custom_models_migrated": 1}
    assert second == {"legacy_models_migrated": 0, "custom_models_migrated": 0}
    assert {"llm_models", "tts_models", "stt_models", "model_overrides"} <= tables
    assert not ({"provider_models", "schema_info"} & tables)
    assert custom_setting is None
    assert repository.get_model("legacy", "modelo-legado")["supportsVision"] is True
    assert repository.get_model("manual", "modelo-manual")["custom"] is True


def test_modelo_customizado_fica_na_mesma_tabela(tmp_path) -> None:
    database = tmp_path / "models.sqlite3"
    _create_models_db(database)
    repository = LlmModelRepository(database)

    saved = repository.save_model(
        {"provider": "qwen", "id": "modelo-novo", "supportsVision": True, "custom": True}
    )

    assert saved["custom"] is True
    assert saved["supportsVision"] is True
