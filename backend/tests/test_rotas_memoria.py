"""Contrato da remoção da API antiga de memória."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.api.routers.memoria import executar_sono
from backend.api.server import app
from backend.memory.long_term import sleep


def test_openapi_expoe_sono_novo_sem_rotas_antigas() -> None:
    paths = app.openapi()["paths"]

    assert "/api/memoria/sono" in paths
    assert not any(path.startswith("/api/memory") for path in paths)


def test_openapi_separa_configuracao_por_dominio() -> None:
    schema = app.openapi()
    tags = {
        tag
        for path in schema["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict)
        for tag in operation.get("tags", [])
    }

    assert {
        "Configuração — LLM e chat",
        "Configuração — voz",
        "Configuração — conexões",
        "Configuração — ambiente",
        "Configuração — imagem",
        "Catálogo",
    } <= tags
    assert "Configuração" not in tags
    assert not any(path.startswith("/api/permissions") for path in schema["paths"])


def test_sono_repassa_force_sem_gravar_em_banco_real(monkeypatch) -> None:
    memory = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(memory=memory)))
    recebido: dict[str, object] = {}

    def fake_run_sleep_cycle(received_memory: object, *, force: bool) -> dict[str, object]:
        recebido.update(memory=received_memory, force=force)
        return {"ok": True, "reason": "teste"}

    monkeypatch.setattr(sleep, "run_sleep_cycle", fake_run_sleep_cycle)

    response = asyncio.run(executar_sono(request, {"force": True}))

    assert recebido == {"memory": memory, "force": True}
    assert response == {"status": "ok", "ok": True, "reason": "teste"}
