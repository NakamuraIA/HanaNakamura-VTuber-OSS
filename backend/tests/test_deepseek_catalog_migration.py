"""Testes da primeira migração de provider para o LlmModelRepository."""

import logging
import sqlite3

from backend.bd.llm import criar_tabela_llm
from backend.catalog.repository import LlmModelRepository
from backend.providers.provider_selector.deepseek.provider import DeepSeekProvider


def _create_database(path, model_id: str) -> None:
    """Cria a tabela pelo dono dela (``bd/llm.py``) e insere um modelo de teste."""
    with sqlite3.connect(path) as connection:
        criar_tabela_llm(connection)
        connection.execute(
            """
            INSERT INTO llm_models (
                provider, model_id, label, supports_tools,
                supports_streaming, supports_streaming_tools
            )
            VALUES ('deepseek', ?, 'Modelo vindo do SQLite', 1, 1, 1)
            """,
            (model_id,),
        )


def test_deepseek_prefere_model_repository(tmp_path, caplog) -> None:
    """Confirma que o modelo do banco vence o mesmo ID do catálogo legado."""
    database = tmp_path / "models.sqlite3"
    _create_database(database, "deepseek-v4-pro")
    provider = DeepSeekProvider(LlmModelRepository(database))

    with caplog.at_level(logging.WARNING):
        model = provider._catalog_model("deepseek-v4-pro")

    assert model is not None
    assert model["label"] == "Modelo vindo do SQLite"
    assert "LEGACY FALLBACK" not in caplog.text


def test_deepseek_sem_catalogo_legado_retorna_none(tmp_path) -> None:
    """Migrado (2026-08-04): sem fallback. Fora do banco, o modelo não existe."""
    database = tmp_path / "models.sqlite3"
    _create_database(database, "outro-modelo")
    provider = DeepSeekProvider(LlmModelRepository(database))

    model = provider._catalog_model("deepseek-v4-pro")

    assert model is None
