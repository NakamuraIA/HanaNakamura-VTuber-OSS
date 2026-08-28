"""Catalogo de modelos LLM (`llm_models`): listar, cadastrar, editar, apagar.

Existe porque nem todo provider tem um endpoint publico de "liste seus modelos".
O OpenRouter tem (`/api/v1/models`); Groq, DeepSeek, Qwen, Maritaca e Gemini nao
— a lista deles vivia hardcoded em `catalog.py` e envelhecia calada. Hoje mora
no banco (migracao dos 5 providers concluida em 2026-08-05).

Estas rotas escrevem na MESMA tabela que o chat le. Nao existe lista paralela:
cadastrar aqui e o mesmo que o modelo passar a existir pra Hana.

Historico: a fase 4 removeu o cache paralelo que existia antes de `llm_models`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from backend.catalog.repository import LlmModelRepository

router = APIRouter(prefix="/api/modelos", tags=["Modelos"])


def _repo() -> LlmModelRepository:
    return LlmModelRepository()


@router.get("", summary="Listar modelos do catálogo")
async def listar(provider: str = "") -> dict[str, Any]:
    """Modelos guardados no banco, opcionalmente de um provider só.

    Sem `provider`: devolve tudo, com a contagem por provider em `porProvider`.
    """
    itens = _repo().list_models(provider.strip().lower() or None)
    por_provider: dict[str, int] = {}
    for item in itens:
        chave = str(item.get("provider") or "")
        por_provider[chave] = por_provider.get(chave, 0) + 1
    return {"ok": True, "total": len(itens), "porProvider": por_provider, "itens": itens}


@router.put("", summary="Cadastrar ou editar um modelo")
async def salvar(
    payload: dict[str, Any] = Body(
        ...,
        examples=[
            {
                "provider": "deepseek",
                "id": "deepseek-v4-flash",
                "label": "DeepSeek V4 Flash",
                "supportsTools": True,
                "maxInputTokens": 1000000,
                "pricing": {"prompt": "0.00000014", "completion": "0.00000028"},
            }
        ],
    ),
) -> dict[str, Any]:
    """Cria o modelo, ou sobrescreve se `provider` + `id` já existirem.

    Uma rota só para os dois casos: do ponto de vista de quem usa a tela,
    "adicionar" e "editar" preenchem o mesmo formulário.
    """
    try:
        modelo = _repo().save_model(payload)
    except ValueError:
        raise HTTPException(status_code=400, detail="Informe 'provider' e 'id'.")
    return {"ok": True, "modelo": modelo}


@router.delete("/{provider}/{model_id:path}", summary="Apagar um modelo")
async def apagar(provider: str, model_id: str) -> dict[str, Any]:
    """Apaga de vez. `model_id` usa `:path` porque id tem barra (`qwen/qwen3-32b`)."""
    if not _repo().delete_model(provider, model_id):
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")
    return {"ok": True}
