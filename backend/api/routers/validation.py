"""Rotas temporárias de validação manual para uso local no Swagger."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from backend.api.local_request import require_local_request
from backend.validation.agent_core import validate_temporary_agent_core
from backend.validation.catalog import validate_principal_catalog, validate_temporary_catalog
from backend.validation.memory import validate_principal_memory, validate_temporary_memory
from backend.paths import MEMORY_DB

router = APIRouter(prefix="/api/validation", tags=["Validação (temporária)"])


@router.get(
    "/memory/read-only",
    summary="Validar a memória real sem permitir escrita",
)
def validate_real_memory(
    request: Request,
    q: str = Query(
        "",
        description="Texto opcional para testar a seleção do RAG. A resposta mostra IDs, nunca o texto privado.",
    ),
    limit: int = Query(8, ge=1, le=20),
) -> dict[str, Any]:
    """Verifica tabelas, canais, RAG, memória fixa, eventos e ciclo de sono."""

    require_local_request(request)
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="Memória não inicializada.")
    return validate_principal_memory(
        memory.db_path,
        memory.events_path,
        query=q,
        limit=limit,
    )


@router.post(
    "/memory/temporary",
    summary="Testar gravação em um banco descartável",
)
def validate_memory_with_writes(request: Request) -> dict[str, Any]:
    """Cria, testa e remove um banco temporário sem tocar no banco principal."""

    require_local_request(request)
    return validate_temporary_memory()


@router.post(
    "/agent-core/temporary",
    summary="Testar o Agent Core no banco único descartável",
)
def validate_agent_core_with_writes(request: Request) -> dict[str, Any]:
    """Prova a separação das tabelas sem alterar o banco principal."""

    require_local_request(request)
    return validate_temporary_agent_core()


@router.get(
    "/catalog/read-only",
    summary="Validar o catálogo real sem permitir escrita",
)
def validate_real_catalog(request: Request) -> dict[str, Any]:
    """Mostra apenas estrutura e contagens, sem nomes de modelos privados."""

    require_local_request(request)
    return validate_principal_catalog(MEMORY_DB)


@router.post(
    "/catalog/temporary",
    summary="Testar a migração do catálogo em banco descartável",
)
def validate_catalog_with_writes(request: Request) -> dict[str, Any]:
    """Migra dados sintéticos sem tocar no banco principal."""

    require_local_request(request)
    return validate_temporary_catalog()
