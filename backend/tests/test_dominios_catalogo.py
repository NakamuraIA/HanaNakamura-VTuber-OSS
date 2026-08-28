"""Domínio explícito dos modelos do catálogo (llm_models.model_domain).

Cobre a migração aditiva, o seed classificado, os filtros de conversa/imagem,
o fallback multimodal, os filtros do Discord e a barreira central do turno.
Todos os bancos são SQLite temporários e descartáveis.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import backend.api.services.catalog as catalog_service
from backend.bd import preparar_catalogos
from backend.bd.llm import criar_tabela_llm
from backend.catalog.repository import LlmModelRepository
from backend.discord_bot.cogs.config import model_ids_for
from backend.setup.database import (
    SETUP_MARKER_KEY,
    initialize_database,
    installation_status,
    restore_defaults,
)

ESPECIALIZADOS = {
    ("qwen", "qwen-image-2.0-pro"): "image",
    ("qwen", "text-embedding-v4"): "embedding",
    ("qwen", "tongyi-embedding-vision-plus"): "embedding",
    ("qwen", "qwen3-rerank"): "rerank",
}


def _repository(tmp_path) -> LlmModelRepository:
    database = tmp_path / "catalog.sqlite3"
    database.touch()
    preparar_catalogos(database)
    return LlmModelRepository(database)


def _dominios(repository: LlmModelRepository) -> dict[tuple[str, str], str]:
    return {
        (m["provider"], m["id"]): str(m.get("modelDomain") or "chat")
        for m in repository.list_models()
    }


def _stub_payload(monkeypatch, repository: LlmModelRepository, openrouter_rows: list[dict]) -> dict:
    monkeypatch.setattr(catalog_service, "LlmModelRepository", lambda: repository)
    monkeypatch.setattr(catalog_service, "get_openrouter_catalog", lambda: (openrouter_rows, None))
    monkeypatch.setattr(catalog_service, "_tts_provider_ids", lambda rows: [])
    monkeypatch.setattr(catalog_service, "_tts_flat_voices", lambda rows: [])
    monkeypatch.setattr(catalog_service, "_tts_provider_catalog", lambda rows: [])
    monkeypatch.setattr(catalog_service.TtsModelRepository, "list_models", lambda self: [])
    return catalog_service.catalog_payload()


# 1) Migração de banco legado sem a coluna ------------------------------------ #

def test_migracao_banco_legado_sem_model_domain(tmp_path) -> None:
    database = tmp_path / "legado.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            CREATE TABLE llm_models (
              provider TEXT NOT NULL,
              model_id TEXT NOT NULL,
              label TEXT NOT NULL DEFAULT '',
              supports_vision INTEGER,
              supports_streaming INTEGER,
              source TEXT NOT NULL DEFAULT 'manual',
              lifecycle_status TEXT NOT NULL DEFAULT 'active',
              PRIMARY KEY (provider, model_id)
            )
            """
        )
        for (provider, model_id), dominio in ESPECIALIZADOS.items():
            connection.execute(
                "INSERT INTO llm_models (provider, model_id, label) VALUES (?, ?, ?)",
                (provider, model_id, model_id),
            )
        connection.execute(
            "INSERT INTO llm_models (provider, model_id, label) VALUES ('local', 'meu-modelo', 'Meu modelo')"
        )
        connection.commit()

    with closing(sqlite3.connect(database)) as connection:
        criar_tabela_llm(connection)
        colunas = {str(row[1]) for row in connection.execute("PRAGMA table_info(llm_models)")}
        linhas = {
            (row[0], row[1]): row[2]
            for row in connection.execute("SELECT provider, model_id, model_domain FROM llm_models")
        }

    assert "model_domain" in colunas
    for chave, dominio in ESPECIALIZADOS.items():
        assert linhas[chave] == dominio
    # Personalizado/legado fica em chat por padrão.
    assert linhas[("local", "meu-modelo")] == "chat"


# 2, 4, 5) Seed, idempotência e personalizados -------------------------------- #

def test_seed_segunda_execucao_e_personalizados_preservados(tmp_path) -> None:
    database = tmp_path / "hana.sqlite3"

    primeiro = initialize_database(database)
    assert primeiro["changed"] is True
    repository = LlmModelRepository(database)
    dominios = _dominios(repository)
    for chave, dominio in ESPECIALIZADOS.items():
        assert dominios[chave] == dominio

    # Personalizado criado DEPOIS da instalação, com rótulo próprio.
    repository.save_model(
        {"provider": "local", "id": "meu-modelo", "label": "Da dona", "custom": True}
    )

    # Segunda execução: marca ativa, nada reimportado.
    segundo = initialize_database(database)
    assert segundo["changed"] is False
    assert installation_status(database)["status"] == "initialized"

    # Restauração manual completa (upsert do seed): especializados continuam
    # classificados e o personalizado NÃO é tocado nem apagado.
    restauracao = restore_defaults("all", confirm=True, db_path=database)
    assert restauracao["database_changed"] is True
    repositorio_depois = LlmModelRepository(database)
    dominios_depois = _dominios(repositorio_depois)
    for chave, dominio in ESPECIALIZADOS.items():
        assert dominios_depois[chave] == dominio
    meu = repositorio_depois.get_model("local", "meu-modelo")
    assert meu is not None and meu["label"] == "Da dona"
    assert meu["modelDomain"] == "chat"
    assert _tem_marca(database)


def _tem_marca(db_path: Path) -> bool:
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute(
            "SELECT 1 FROM settings WHERE key = ?", (SETUP_MARKER_KEY,)
        ).fetchone() is not None


# 3) Valor padrão para personalizado via API administrativa ------------------- #

def test_modelo_personalizado_nasce_chat(tmp_path) -> None:
    repository = _repository(tmp_path)
    salvo = repository.save_model({"provider": "openai", "id": "gpt-custom"})
    assert salvo["modelDomain"] == "chat"


# 6, 7, 9, 12) Catálogo servido pela API -------------------------------------- #

def test_catalogo_conversa_exclui_especializados_e_imagemodels_inclui_local(
    tmp_path,
    monkeypatch,
) -> None:
    database = tmp_path / "hana.sqlite3"
    initialize_database(database)
    repository = LlmModelRepository(database)

    openrouter_rows = [
        {"provider": "openrouter", "id": "or-chat", "outputModalities": ["text"]},
        {"provider": "openrouter", "id": "or-imagem", "outputModalities": ["image"]},
    ]
    payload = _stub_payload(monkeypatch, repository, openrouter_rows)

    ids_conversa = {(m["provider"], m["id"]) for m in payload["models"]}
    # Especializados FORA da lista de conversa...
    for chave in ESPECIALIZADOS:
        assert chave not in ids_conversa
    # ...dinâmico do OpenRouter SEM modelDomain continua dentro (compatível).
    assert ("openrouter", "or-chat") in ids_conversa
    # VL e omni (conversa multimodal) continuam disponíveis.
    assert ("qwen", "qwen3-vl-plus") in ids_conversa
    assert ("qwen", "qwen3.5-omni-plus") in ids_conversa

    # imageModels inclui apenas modelos de providers com runtime executável.
    ids_imagem = {(m["provider"], m["id"]) for m in payload["imageModels"]}
    assert ("qwen", "qwen-image-2.0-pro") not in ids_imagem
    assert ("openrouter", "or-imagem") in ids_imagem
    assert payload["imageProviders"] == ["gemini_api", "openrouter"]


# 8) Fallback multimodal não escolhe embedding -------------------------------- #

def test_visao_recusa_embedding_multimodal_e_aceita_vl(tmp_path, monkeypatch) -> None:
    database = tmp_path / "hana.sqlite3"
    initialize_database(database)
    repository = LlmModelRepository(database)
    monkeypatch.setattr(catalog_service, "LlmModelRepository", lambda: repository)

    assert catalog_service.model_supports_vision("qwen", "tongyi-embedding-vision-plus") is False
    assert catalog_service.model_supports_vision("qwen", "text-embedding-v4") is False
    assert catalog_service.model_supports_vision("qwen", "qwen3-vl-plus") is True


# 10) Filtros do Discord ------------------------------------------------------- #

def test_filtros_do_discord_por_dominio() -> None:
    catalogo = {
        "models": [
            {"provider": "qwen", "id": "qwen3-max", "outputModalities": ["text"], "modelDomain": "chat"},
            {"provider": "qwen", "id": "text-embedding-v4", "outputModalities": ["text"], "modelDomain": "embedding"},
            {"provider": "qwen", "id": "qwen3-vl-plus", "outputModalities": ["text"], "supportsVision": True, "modelDomain": "chat"},
            {"provider": "qwen", "id": "tongyi-embedding-vision-plus", "outputModalities": ["text"], "supportsVision": True, "modelDomain": "embedding"},
        ],
        "imageModels": [
            {"provider": "qwen", "id": "qwen-image-2.0-pro", "modelDomain": "image"},
        ],
    }

    chat = [m["id"] for m in model_ids_for("chat", "qwen", catalogo)]
    assert "qwen3-max" in chat and "qwen3-vl-plus" in chat
    assert "text-embedding-v4" not in chat and "tongyi-embedding-vision-plus" not in chat

    agente = [m["id"] for m in model_ids_for("agente", "qwen", catalogo)]
    assert "text-embedding-v4" not in agente

    multimodal = [m["id"] for m in model_ids_for("multimodal", "qwen", catalogo)]
    assert multimodal == ["qwen3-vl-plus"]

    imagem = [m["id"] for m in model_ids_for("imagem", "qwen", catalogo)]
    assert imagem == ["qwen-image-2.0-pro"]

    # Linha SEM modelDomain (fonte antiga/dinâmica) continua entrando como chat.
    catalogo_legado = {
        "models": [{"provider": "groq", "id": "antigo", "outputModalities": ["text"]}]
    }
    assert [m["id"] for m in model_ids_for("chat", "groq", catalogo_legado)] == ["antigo"]


# 11) Barreira central do turno ------------------------------------------------ #

def test_barreira_central_do_turno(tmp_path) -> None:
    database = tmp_path / "hana.sqlite3"
    initialize_database(database)
    repository = LlmModelRepository(database)
    monkey_target = catalog_service
    monkey_target_original = monkey_target.LlmModelRepository
    monkey_target.LlmModelRepository = lambda: repository
    try:
        bloqueio = catalog_service.erro_modelo_nao_conversa("qwen", "text-embedding-v4")
        assert bloqueio is not None and "embeddings" in bloqueio
        assert catalog_service.erro_modelo_nao_conversa("qwen", "qwen3-rerank") is not None
        assert catalog_service.erro_modelo_nao_conversa("qwen", "qwen-image-2.0-pro") is not None
        # Conversa e desconhecidos passam livres.
        assert catalog_service.erro_modelo_nao_conversa("qwen", "qwen3-vl-plus") is None
        assert catalog_service.erro_modelo_nao_conversa("openrouter", "modelo-que-nao-existe-local") is None
        assert catalog_service.erro_modelo_nao_conversa("agent_core", "") is None
    finally:
        monkey_target.LlmModelRepository = monkey_target_original
