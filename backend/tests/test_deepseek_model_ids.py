"""Trava os IDs aceitos pela API oficial da DeepSeek.

Bug real: alguem cadastrou "deepseek-v4-flash-0731" (a VERSAO do modelo,
"MODEL VERSION" na doc oficial) como se fosse um "MODEL" selecionavel. A API
rejeitou a chamada porque so aceita "deepseek-v4-pro" ou "deepseek-v4-flash".

Migrado (2026-08-04): nao existe mais lista estatica em Python pra travar.
O dado mora em ``llm_models``; este teste documenta os dois IDs corretos
contra um banco de teste, sem tocar no banco real de runtime.
"""

import json
import sqlite3
from pathlib import Path

from backend.bd.llm import criar_tabela_llm
from backend.catalog.repository import LlmModelRepository

API_ACCEPTED_MODEL_IDS = {
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp",
}


def test_catalogo_so_tem_ids_aceitos_pela_api(tmp_path):
    database = tmp_path / "models.sqlite3"
    with sqlite3.connect(database) as connection:
        criar_tabela_llm(connection)
        for model_id in API_ACCEPTED_MODEL_IDS:
            connection.execute(
                "INSERT INTO llm_models (provider, model_id, label) VALUES ('deepseek', ?, ?)",
                (model_id, model_id),
            )
        connection.commit()

    ids = {m["id"] for m in LlmModelRepository(database).list_models("deepseek")}
    assert ids == API_ACCEPTED_MODEL_IDS


def test_deepseek_vision_experimental_esta_no_catalogo_publico():
    catalog_path = Path(__file__).resolve().parents[1] / "setup" / "defaults" / "llm_models.json"
    models = json.loads(catalog_path.read_text(encoding="utf-8"))["models"]
    vision = next(model for model in models if model["model_id"] == "deepseek-v4-flash-vision-exp")

    assert vision["provider"] == "deepseek"
    assert vision["supports_vision"] is True
    assert vision["input_modalities"] == ["text", "image"]
