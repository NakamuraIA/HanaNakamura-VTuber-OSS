from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from backend.api.routers.validation import require_local_request, router
from backend.bd import preparar_catalogos
from backend.catalog.repository import LlmModelRepository
from backend.memory.core import HanaMemory
from backend.memory.store import MemoryStore
from backend.memory.storage import RuntimeStore
from backend.validation.agent_core import validate_temporary_agent_core
from backend.validation.catalog import validate_principal_catalog, validate_temporary_catalog
from backend.validation.memory import (
    _ReadOnlyMemoryStore,
    validate_principal_memory,
    validate_temporary_memory,
)


def _request_from(host: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/validation/memory/read-only",
            "raw_path": b"/api/validation/memory/read-only",
            "query_string": b"",
            "headers": [],
            "client": (host, 12345),
            "server": ("127.0.0.1", 8042),
        }
    )


def test_principal_validation_is_read_only_and_hides_text() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        db_path = root / "principal.sqlite3"
        events_path = root / "events.jsonl"
        store = MemoryStore(db_path=db_path, events_path=events_path)
        fixed = HanaMemory(str(db_path))
        RuntimeStore(db_path)
        store._short_term = fixed
        memory = store.add_memory("conteudo privado que nao pode sair", kind="fato")
        fixed.add_pinned("regra privada que nao pode sair")
        store.append_event(
            "assistant",
            "projecao privada",
            channel="terminal_agent",
            metadata={"conversation": False},
        )

        result = validate_principal_memory(db_path, events_path, query="privado")

        assert result["resultado"] == "aprovado"
        assert result["banco_usado"] == "principal (somente leitura)"
        assert result["evidencia_resumida"]["conexao_bloqueada_para_escrita"] is True
        assert result["evidencia_resumida"]["memoria_fixa"]["bloco_confirmado"] is True
        assert result["evidencia_resumida"]["conversation_false"]["fora_da_conversa_canonica"] is True
        serialized = str(result)
        assert "conteudo privado" not in serialized
        assert "regra privada" not in serialized
        assert "projecao privada" not in serialized
        assert str(memory["id"]) in serialized

        read_only = _ReadOnlyMemoryStore(db_path, events_path)
        with pytest.raises(sqlite3.OperationalError):
            read_only.set_setting("nao_pode_gravar", {"ok": False})


def test_temporary_validation_removes_its_database() -> None:
    result = validate_temporary_memory()

    assert result["resultado"] == "aprovado"
    assert result["banco_usado"] == "temporário descartável"
    assert all(result["evidencia_resumida"].values())


def test_temporary_validation_cleans_up_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_safely(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("falha controlada")

    monkeypatch.setattr(MemoryStore, "add_memory", fail_safely)
    result = validate_temporary_memory()

    assert result["resultado"] == "falhou"
    assert result["evidencia_resumida"]["banco_temporario_removido"] is True
    assert result["evidencia_resumida"]["erro_seguro"] == "RuntimeError"
    assert "hana-validacao-" not in str(result)


def test_validation_routes_are_documented() -> None:
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()

    assert "/api/validation/memory/read-only" in schema["paths"]
    assert "/api/validation/memory/temporary" in schema["paths"]
    assert "/api/validation/agent-core/temporary" in schema["paths"]
    assert "/api/validation/catalog/read-only" in schema["paths"]
    assert "/api/validation/catalog/temporary" in schema["paths"]
    assert schema["paths"]["/api/validation/memory/read-only"]["get"]["tags"] == [
        "Validação (temporária)"
    ]


def test_agent_core_validation_uses_and_removes_temporary_database() -> None:
    result = validate_temporary_agent_core()

    assert result["resultado"] == "aprovado"
    assert result["banco_usado"] == "temporário descartável"
    assert result["evidencia_resumida"]["banco_temporario_removido"] is True
    assert result["evidencia_resumida"]["mensagem_canonica_preservada"] is True


def test_catalog_validation_migrates_and_removes_temporary_database() -> None:
    result = validate_temporary_catalog()

    assert result["resultado"] == "aprovado"
    assert result["banco_usado"] == "temporário descartável"
    assert all(result["evidencia_resumida"].values())


def test_catalog_read_only_validation_hides_model_names(tmp_path) -> None:
    database = tmp_path / "catalog.sqlite3"
    database.touch()
    preparar_catalogos(database)
    LlmModelRepository(database).save_model(
        {"provider": "privado", "id": "segredo-nao-expor", "custom": True}
    )

    result = validate_principal_catalog(database)

    assert result["resultado"] == "aprovado"
    assert "segredo-nao-expor" not in str(result)


def test_validation_rejects_non_local_request() -> None:
    require_local_request(_request_from("127.0.0.1"))
    require_local_request(_request_from("::1"))

    with pytest.raises(HTTPException) as error:
        require_local_request(_request_from("203.0.113.10"))
    assert error.value.status_code == 403
