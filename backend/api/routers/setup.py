"""Recuperação manual dos catálogos públicos, acessível somente localmente."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from backend.api.local_request import require_local_request
from backend.setup.database import SetupDataError, preview_defaults, restore_defaults

router = APIRouter(prefix="/api/setup", tags=["Setup e recuperação"])

CatalogName = Literal["llm", "tts", "stt"]


@router.get(
    "/defaults/{catalog}",
    summary="Ver modelos públicos antes de restaurar",
)
def preview_public_defaults(request: Request, catalog: CatalogName) -> dict[str, Any]:
    """Lê o JSON público sem abrir ou alterar o banco."""

    require_local_request(request)
    try:
        return preview_defaults(catalog)
    except SetupDataError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/defaults/{catalog}/restore",
    summary="Restaurar modelos públicos sob confirmação",
)
def restore_public_defaults(
    request: Request,
    catalog: CatalogName,
    confirm: bool = Query(
        False,
        description="Mantenha false para prévia. Troque para true somente depois de conferir a lista.",
    ),
) -> dict[str, Any]:
    """Sem ``confirm=true`` devolve apenas a prévia e não grava nada."""

    require_local_request(request)
    try:
        return restore_defaults(catalog, confirm=confirm)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SetupDataError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Falha ao restaurar o catálogo no banco.") from exc
