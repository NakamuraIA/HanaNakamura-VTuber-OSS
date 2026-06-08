from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["Memory"])


def _payload_dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize optional JSON bodies from Control Panel calls."""
    return payload if isinstance(payload, dict) else {}


def _metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge explicit memory fields into metadata for backward-compatible clients."""
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    merged = dict(metadata)
    for key in ("category", "importance", "tags", "pinned", "status"):
        if key in payload:
            merged[key] = payload[key]
    return merged


def _memory_ids(payload: dict[str, Any]) -> list[str]:
    """Read selected memory ids from the API payload without accepting junk values."""
    raw = payload.get("memoryIds") or payload.get("memory_ids") or payload.get("ids") or []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


@router.get("/api/memory/graph")
async def memory_graph(request: Request) -> dict[str, Any]:
    return {"facts": request.app.state.memory.list_facts()}


@router.post("/api/memory/graph")
async def create_graph_fact(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    request.app.state.memory.add_fact(str(payload.get("subject") or ""), str(payload.get("relation") or ""), str(payload.get("object") or ""))
    return {"status": "ok"}


@router.delete("/api/memory/graph")
async def delete_graph_fact(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    deleted = request.app.state.memory.delete_fact(str(payload.get("subject") or ""), str(payload.get("relation") or ""), str(payload.get("object") or ""))
    return {"status": "ok", "deleted": deleted}


@router.get("/api/memory/rag")
async def memory_rag(
    request: Request,
    query: str = Query("", max_length=1200),
    status: str = Query("active", max_length=32),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """List or search persistent memories through the backend ranking path."""
    if query.strip():
        memories = request.app.state.memory.search(query, limit=limit, status=status)
    else:
        memories = request.app.state.memory.list_memories(limit=limit, status=status)
    return {"memories": memories, "count": len(memories), "semantic": request.app.state.memory.semantic_status()}


@router.get("/api/memory/longterm")
async def memory_longterm(request: Request, limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
    """Return only long-term memories saved by the model (kind=long_term)."""
    all_memories = request.app.state.memory.list_memories(limit=limit, status="active")
    longterm = [
        m for m in all_memories
        if m.get("metadata", {}).get("kind") == "long_term"
        or m.get("kind") == "long_term"
    ]
    return {"memories": longterm, "count": len(longterm)}


@router.post("/api/memory/rag")
async def create_memory(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Create one persistent memory with v2 metadata fields."""
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="memory_text_empty")
    metadata = _metadata_from_payload(payload)
    memory = request.app.state.memory.add_memory(
        text,
        metadata=metadata,
        kind=str(payload.get("kind") or metadata.get("kind") or "note"),
        source=str(payload.get("source") or "control_panel"),
        status=str(payload.get("status") or metadata.get("status") or "active"),
    )
    return {"status": "ok", "memory": memory}


@router.put("/api/memory/rag/{memory_id}")
async def update_memory(request: Request, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Update text and metadata while keeping the same memory id."""
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="memory_text_empty")
    metadata = _metadata_from_payload(payload)
    memory = request.app.state.memory.add_memory(
        text,
        metadata=metadata,
        kind=str(payload.get("kind") or metadata.get("kind") or "note"),
        source=str(payload.get("source") or metadata.get("source") or "control_panel"),
        memory_id=memory_id,
        status=str(payload.get("status") or metadata.get("status") or "active"),
    )
    return {"status": "ok", "memory": memory}


@router.delete("/api/memory/rag/{memory_id}")
async def delete_memory(request: Request, memory_id: str, hard: bool = Query(False)) -> dict[str, Any]:
    """Soft-delete by default; hard-delete only when explicitly requested."""
    deleted = request.app.state.memory.delete_memory(memory_id, hard=hard)
    if not deleted:
        raise HTTPException(status_code=404, detail="memory_not_found")
    return {"status": "ok", "deleted": deleted, "hard": hard}


@router.delete("/api/memory/longterm/{memory_id}")
async def delete_longterm_memory(request: Request, memory_id: str) -> dict[str, Any]:
    """Soft-delete a specific long-term memory saved by the model."""
    deleted = request.app.state.memory.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="memory_not_found")
    return {"status": "ok", "deleted": deleted}


@router.post("/api/memory/rag/{memory_id}/restore")
async def restore_memory(request: Request, memory_id: str) -> dict[str, Any]:
    restored = request.app.state.memory.restore_memory(memory_id)
    if not restored:
        raise HTTPException(status_code=404, detail="memory_not_found")
    return {"status": "ok", "restored": restored}


@router.post("/api/memory/rag/{memory_id}/pin")
async def pin_memory(request: Request, memory_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _payload_dict(payload)
    pinned = bool(body.get("pinned", True))
    updated = request.app.state.memory.pin_memory(memory_id, pinned=pinned)
    if not updated:
        raise HTTPException(status_code=404, detail="memory_not_found")
    return {"status": "ok", "pinned": pinned}


@router.post("/api/memory/rag/{memory_id}/archive")
async def archive_memory(request: Request, memory_id: str) -> dict[str, Any]:
    archived = request.app.state.memory.archive_memory(memory_id)
    if not archived:
        raise HTTPException(status_code=404, detail="memory_not_found")
    return {"status": "ok", "archived": archived}


@router.post("/api/memory/search")
async def search_memory(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _payload_dict(payload)
    query = str(body.get("query") or "").strip()
    status = str(body.get("status") or "active")
    limit = int(body.get("limit") or 12)
    memories = request.app.state.memory.search(query, limit=limit, status=status)
    return {"status": "ok", "memories": memories, "count": len(memories), "semantic": request.app.state.memory.semantic_status()}


@router.post("/api/memory/compact")
async def compact_memory(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _payload_dict(payload)
    result = request.app.state.memory.compact(
        source_channel=str(body.get("channel") or "control_center"),
        limit=int(body.get("limit") or 40),
        memory_ids=_memory_ids(body) or None,
        archive_originals=bool(body.get("archiveOriginals") or body.get("archive_originals") or False),
    )
    return {"status": "ok", **result}


@router.post("/api/memory/merge")
async def merge_memory(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _payload_dict(payload)
    result = request.app.state.memory.merge_memories(
        _memory_ids(body),
        text=str(body.get("text") or "").strip() or None,
        archive_originals=bool(body.get("archiveOriginals") if "archiveOriginals" in body else True),
    )
    return {"status": "ok", **result}


@router.get("/api/memory/audit")
async def audit_memory(request: Request) -> dict[str, Any]:
    return {"status": "ok", "audit": request.app.state.memory.audit_memories()}


@router.post("/api/memory/maintenance/run")
async def run_memory_maintenance(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _payload_dict(payload)
    result = request.app.state.memory.run_maintenance(channel=str(body.get("channel") or "control_center"))
    return {"status": "ok", **result}


@router.post("/api/memory/clear-runtime")
async def clear_memory(request: Request) -> dict[str, Any]:
    return request.app.state.memory.clear_runtime()
