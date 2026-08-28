"""API atual da memória, incluindo fatos, regras fixas, conversa e sono.

O router anterior cresceu por acúmulo: cada ação ganhou um endpoint próprio e
três rotas diferentes faziam "arrumar a memória". Aqui a regra é uma só:

    endpoint e SUBSTANTIVO, nao verbo.

Fixar, arquivar e restaurar sao "mudar um campo" — cabem todos no mesmo PUT.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request

from backend.memory.core import CHANNELS, HanaMemory, PINNED_KINDS
from backend.memory.store import MemoryStore

router = APIRouter(prefix="/api/memoria", tags=["Memória"])


def _mem(request: Request) -> HanaMemory:
    memoria = getattr(request.app.state, "memoria", None)
    if memoria is None:
        raise HTTPException(status_code=503, detail="Memória não inicializada.")
    return memoria


def _store(request: Request) -> MemoryStore:
    """Memória longa (RAG) mora em memory_items — a mesma que o chat usa de verdade."""
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="Memória não inicializada.")
    return memory


@router.post("/sono", summary="Executar o ciclo de sono")
async def executar_sono(
    request: Request,
    payload: dict[str, Any] | None = Body(None, examples=[{"force": False}]),
) -> dict[str, Any]:
    """Relê o período recente e executa a manutenção da memória longa.

    A chamada ao modelo é bloqueante, por isso roda fora do event loop. O corpo
    é opcional; ``force=true`` ignora o intervalo normal de 24 horas.
    """
    from backend.memory.long_term.sleep import run_sleep_cycle

    force = bool((payload or {}).get("force", False))
    memory = _store(request)
    result = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: run_sleep_cycle(memory, force=force),
    )
    return {"status": "ok" if result.get("ok") else "error", **result}


# Vocabulario da tela (pt) <-> vocabulario do MemoryStore (en).
_STATUS_TELA_PARA_STORE = {"ativa": "active", "arquivada": "archived", "lixeira": "deleted"}
_STATUS_STORE_PARA_TELA = {v: k for k, v in _STATUS_TELA_PARA_STORE.items()}


def _fato_from_memory_item(item: dict[str, Any]) -> dict[str, Any]:
    """Reformata um item de memory_items no formato que a tela de fatos espera."""
    meta = item.get("metadata") or {}
    return {
        "id": item.get("id"),
        "text": item.get("text"),
        "kind": item.get("kind"),
        "source": item.get("source"),
        "status": _STATUS_STORE_PARA_TELA.get(item.get("status"), item.get("status")),
        "use_count": meta.get("useCount"),
        "last_used_at": meta.get("lastAccessedAt"),
        "created_at": meta.get("createdAt"),
        "updated_at": meta.get("updatedAt"),
    }


# ============ panorama ================================================= #

@router.get("/status", summary="Panorama da memória")
async def status(request: Request) -> dict[str, Any]:
    """Quantas memórias existem de cada tipo.

    Serve pra tela de memória e pra você conferir de fora se algo está inchando
    (ex.: histórico do front crescendo sem parar).
    """
    st = _mem(request).status()
    store = _store(request)
    st["fatos"] = {
        "ativas": len(store.list_memories(limit=100000, status="active")),
        "arquivadas": len(store.list_memories(limit=100000, status="archived")),
        "lixeira": len(store.list_memories(limit=100000, status="deleted")),
    }
    return {"ok": True, "status": st}


# ============ memória longa: os fatos (RAG) ============================ #

@router.get("", summary="Listar / buscar fatos (memória longa)")
async def listar_fatos(
    request: Request,
    q: str = Query("", description="Texto pra buscar. Vazio devolve os mais recentes."),
    status_filtro: Literal["ativa", "arquivada", "lixeira"] = Query("ativa", alias="status"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Os fatos que a Hana guardou sozinha.

    Com `q`: busca por palavra (BM25 + semântica quando ligada) — a mesma
    ranking que alimenta o RAG no prompt de verdade (memory_items).
    Sem `q`: lista por data, do mais novo pro mais velho.
    """
    store = _store(request)
    status_store = _STATUS_TELA_PARA_STORE[status_filtro]
    if q.strip():
        itens_raw = store.search(q, limit=limit, status=status_store)
    else:
        itens_raw = store.list_memories(limit=limit, status=status_store)
    itens = [_fato_from_memory_item(item) for item in itens_raw]
    return {"ok": True, "total": len(itens), "itens": itens}


@router.post("", status_code=201, summary="Criar um fato")
async def criar_fato(
    request: Request,
    payload: dict[str, Any] = Body(..., examples=[{"text": "Nakamura tem TDAH e dislexia", "kind": "fato"}]),
) -> dict[str, Any]:
    """Grava um fato novo na memória longa.

    Normalmente quem chama isto é a própria Hana, pela ferramenta de salvar
    memória. Você também pode criar na mão pela tela.
    """
    texto = str(payload.get("text") or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="O campo 'text' é obrigatório.")
    memory = _store(request).add_memory(
        texto, kind=str(payload.get("kind") or "fato"), source=str(payload.get("source") or "manual")
    )
    return {"ok": True, "id": memory["id"]}


@router.put("/{fact_id}", summary="Editar, arquivar ou restaurar um fato")
async def editar_fato(
    request: Request,
    fact_id: str,
    payload: dict[str, Any] = Body(..., examples=[{"status": "arquivada"}]),
) -> dict[str, Any]:
    """Muda o texto e/ou o status de um fato.

    Substitui quatro rotas antigas (`/archive`, `/restore`, `/pin`, `PUT /rag`):
    arquivar é `status="arquivada"`, restaurar é `status="ativa"`, mandar pra
    lixeira é `status="lixeira"`. Uma rota, três ações.
    """
    store = _store(request)
    existente = store.get_memory(fact_id)
    if existente is None:
        raise HTTPException(status_code=404, detail="Fato não encontrado.")
    texto = payload.get("text")
    status_tela = payload.get("status")
    if texto is None and status_tela is None:
        raise HTTPException(status_code=400, detail="Nada pra mudar.")
    status_store = _STATUS_TELA_PARA_STORE.get(status_tela, status_tela) if status_tela else None
    store.add_memory(
        str(texto) if texto is not None else existente["text"],
        kind=existente["kind"],
        source=existente["source"],
        memory_id=fact_id,
        status=status_store,
    )
    return {"ok": True}


@router.delete("/{fact_id}", summary="Apagar um fato de vez")
async def apagar_fato(request: Request, fact_id: str) -> dict[str, Any]:
    """Apaga para sempre. Pra apagar com volta, use `PUT` com `status="lixeira"`."""
    if not _store(request).delete_memory(fact_id, hard=True):
        raise HTTPException(status_code=404, detail="Fato não encontrado.")
    return {"ok": True}


# ============ memória fixa: só a Nakamura escreve ====================== #

@router.get("/fixas", summary="Listar a memória fixa")
async def listar_fixas(
    request: Request,
    todas: bool = Query(False, description="true inclui as desligadas"),
) -> dict[str, Any]:
    """As regras que entram em TODA resposta, sem passar por busca.

    É a continuação do system prompt — mas em banco, não em código, pra você
    editar sem mexer em arquivo nenhum. A Hana só lê: não existe ferramenta que
    deixe ela escrever aqui.
    """
    return {"ok": True, "itens": _mem(request).list_pinned(only_enabled=not todas)}


@router.post("/fixas", status_code=201, summary="Criar uma memória fixa")
async def criar_fixa(
    request: Request,
    payload: dict[str, Any] = Body(..., examples=[{"text": "responda curto", "kind": "regra", "position": 1}]),
) -> dict[str, Any]:
    """Cria uma regra fixa.

    `kind`: regra, giria, tarefa ou fato. `position` define a ordem no prompt
    (menor primeiro) — o que vem antes pesa mais pro modelo.
    """
    texto = str(payload.get("text") or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="O campo 'text' é obrigatório.")
    kind = str(payload.get("kind") or "regra")
    if kind not in PINNED_KINDS:
        raise HTTPException(status_code=400, detail=f"'kind' precisa ser um de: {', '.join(PINNED_KINDS)}")
    pin_id = _mem(request).add_pinned(texto, kind=kind, position=int(payload.get("position") or 100))
    return {"ok": True, "id": pin_id}


@router.put("/fixas/{pin_id}", summary="Editar / ligar / desligar uma fixa")
async def editar_fixa(
    request: Request,
    pin_id: int,
    payload: dict[str, Any] = Body(..., examples=[{"enabled": False}]),
) -> dict[str, Any]:
    """Muda texto, tipo, posição ou liga/desliga.

    Desligar (`enabled: false`) tira do prompt sem apagar — bom pra testar se uma
    regra é a causa de algum comportamento estranho.
    """
    if not _mem(request).update_pinned(pin_id, **payload):
        raise HTTPException(status_code=404, detail="Memória fixa não encontrada ou nada pra mudar.")
    return {"ok": True}


@router.delete("/fixas/{pin_id}", summary="Apagar uma memória fixa")
async def apagar_fixa(request: Request, pin_id: int) -> dict[str, Any]:
    if not _mem(request).delete_pinned(pin_id):
        raise HTTPException(status_code=404, detail="Memória fixa não encontrada.")
    return {"ok": True}


# ============ memória curta: a conversa ================================ #

@router.get("/conversa/{channel}", summary="Ver a memória curta de um canal")
async def conversa(
    request: Request,
    channel: Literal["chat", "discord", "terminal", "voice"],
    limit: int = Query(80, ge=1, le=500),
) -> dict[str, Any]:
    """As últimas falas DAQUELE canal, em ordem cronológica.

    É exatamente o que entra no prompt. Cada canal é isolado: o que foi dito no
    terminal não aparece no Discord. (A ausência desse filtro era o bug que fazia
    a Hana citar no Discord uma conversa de voz de uma hora antes.)
    """
    if channel not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"Canal inválido. Use: {', '.join(CHANNELS)}")
    itens = _mem(request).recent_messages(channel, limit=limit)
    return {"ok": True, "canal": channel, "total": len(itens), "itens": itens}


# ============ histórico do front: NUNCA vai pra LLM ==================== #

@router.get("/historico", summary="Sessões salvas do chat (só pra tela)")
async def sessoes(request: Request, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    """Lista as conversas guardadas pro front recarregar quando você abre o app.

    Isto NÃO é memória: nada daqui entra no prompt. Por isso pode ter JSON de
    ferramenta, imagem e pensamento sem custar token nem sujar o contexto.
    """
    return {"ok": True, "sessoes": _mem(request).chat_sessions(limit=limit)}


@router.get("/historico/{session_id}", summary="Carregar uma sessão do chat")
async def historico(
    request: Request, session_id: str, limit: int = Query(500, ge=1, le=2000)
) -> dict[str, Any]:
    """Todas as mensagens de uma sessão, pra remontar a tela igual você deixou."""
    itens = _mem(request).chat_history(session_id, limit=limit)
    return {"ok": True, "sessionId": session_id, "total": len(itens), "itens": itens}
