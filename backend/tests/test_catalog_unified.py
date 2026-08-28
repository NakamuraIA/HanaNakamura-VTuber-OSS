from __future__ import annotations

import sqlite3

import backend.api.services.catalog as catalog_service
from backend.bd import preparar_catalogos
from backend.catalog.repository import LlmModelRepository


def _repository(tmp_path) -> LlmModelRepository:
    database = tmp_path / "catalog.sqlite3"
    database.touch()
    preparar_catalogos(database)
    return LlmModelRepository(database)


def test_catalog_payload_usa_tabela_local_e_openrouter_dinamico(tmp_path, monkeypatch) -> None:
    repository = _repository(tmp_path)
    repository.save_model(
        {"provider": "qwen", "id": "qwen-local", "supportsVision": True}
    )
    repository.save_model(
        {"provider": "openrouter", "id": "modelo-dinamico", "label": "Correção local", "custom": True}
    )
    monkeypatch.setattr(catalog_service, "LlmModelRepository", lambda: repository)
    monkeypatch.setattr(
        catalog_service,
        "get_openrouter_catalog",
        lambda: ([{"provider": "openrouter", "id": "modelo-dinamico", "label": "API"}], None),
    )
    monkeypatch.setattr(catalog_service, "_tts_provider_ids", lambda rows: [])
    monkeypatch.setattr(catalog_service, "_tts_flat_voices", lambda rows: [])
    monkeypatch.setattr(catalog_service, "_tts_provider_catalog", lambda rows: [])
    monkeypatch.setattr(catalog_service.TtsModelRepository, "list_models", lambda self: [])

    payload = catalog_service.catalog_payload()
    keyed = {(item["provider"], item["id"]): item for item in payload["models"]}

    assert keyed[("qwen", "qwen-local")]["supportsVision"] is True
    assert keyed[("openrouter", "modelo-dinamico")]["label"] == "Correção local"
    assert payload["customModels"] == [keyed[("openrouter", "modelo-dinamico")]]


def test_visao_e_inferencia_de_provider_usam_capacidade_do_modelo(tmp_path, monkeypatch) -> None:
    repository = _repository(tmp_path)
    repository.save_model(
        {"provider": "gemini_api", "id": "sem-visao", "supportsVision": False}
    )
    repository.save_model(
        {"provider": "qualquer", "id": "com-visao", "supportsVision": True}
    )
    monkeypatch.setattr(catalog_service, "LlmModelRepository", lambda: repository)

    assert catalog_service.model_supports_vision("gemini_api", "sem-visao") is False
    assert catalog_service.model_supports_vision("qualquer", "com-visao") is True
    assert catalog_service.catalog_provider_for_model("com-visao") == "qualquer"


def test_modelo_customizado_nao_usa_settings(tmp_path, monkeypatch) -> None:
    repository = _repository(tmp_path)
    monkeypatch.setattr(catalog_service, "LlmModelRepository", lambda: repository)

    saved = catalog_service.upsert_custom_model(
        {"provider": "qwen", "id": "custom", "supportsTools": True}
    )
    deleted = catalog_service.delete_custom_model({"provider": "qwen", "id": "custom"})

    assert saved["custom"] is True
    assert saved["supportsTools"] is True
    assert deleted is True
    with sqlite3.connect(repository.db_path) as connection:
        has_parallel_setting = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'"
        ).fetchone()
    assert has_parallel_setting is None
