from __future__ import annotations

from typing import Any

from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.core.registry import RegisteredTool, ToolRegistry
from hana_agent_oss.memory.store import MemoryStore


def _store() -> MemoryStore:
    """Return a fresh MemoryStore handle for deterministic tool calls."""
    return MemoryStore()


def _metadata(args: dict[str, Any]) -> dict[str, Any]:
    """Build memory metadata from tool args without leaking internal fields."""
    metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else {}
    merged = dict(metadata)
    for key in ("category", "importance", "tags", "pinned", "status"):
        if key in args:
            merged[key] = args[key]
    return merged


def _memory_ids(args: dict[str, Any]) -> list[str]:
    """Normalize memory id lists from Hana or Control Panel payloads."""
    raw = args.get("memory_ids") or args.get("memoryIds") or args.get("ids") or []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


def append_event(args: dict[str, Any]) -> ToolResult:
    """Append one runtime event to the local JSONL short memory."""
    event = _store().append_event(
        str(args.get("role") or "system"),
        str(args.get("content") or ""),
        channel=str(args.get("channel") or "control_center"),
        metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
    )
    return ToolResult(ok=True, tool="memory.append_event", output={"event": event})


def save(args: dict[str, Any]) -> ToolResult:
    """Save a persistent long-term memory item."""
    text = str(args.get("text") or args.get("content") or "").strip()
    if not text:
        return ToolResult(ok=False, tool="memory.save", output={}, error="memory_text_empty")
    metadata = _metadata(args)
    memory = _store().add_memory(
        text,
        kind=str(args.get("kind") or metadata.get("kind") or "long_term"),
        source=str(args.get("source") or "hana_tool"),
        metadata=metadata,
        status=str(args.get("status") or metadata.get("status") or "active"),
    )
    return ToolResult(ok=True, tool="memory.save", output={"memory": memory})


def update(args: dict[str, Any]) -> ToolResult:
    """Update a persistent memory item by id."""
    memory_id = str(args.get("id") or args.get("memory_id") or "").strip()
    text = str(args.get("text") or args.get("content") or "").strip()
    if not memory_id:
        return ToolResult(ok=False, tool="memory.update", output={}, error="memory_id_required")
    if not text:
        return ToolResult(ok=False, tool="memory.update", output={}, error="memory_text_empty")
    metadata = _metadata(args)
    memory = _store().add_memory(
        text,
        kind=str(args.get("kind") or metadata.get("kind") or "long_term"),
        source=str(args.get("source") or metadata.get("source") or "hana_tool"),
        metadata=metadata,
        memory_id=memory_id,
        status=str(args.get("status") or metadata.get("status") or "active"),
    )
    return ToolResult(ok=True, tool="memory.update", output={"memory": memory})


def delete(args: dict[str, Any]) -> ToolResult:
    """Soft-delete one persistent memory; hard-delete is intentionally not exposed to Hana."""
    memory_id = str(args.get("id") or args.get("memory_id") or "").strip()
    if not memory_id:
        return ToolResult(ok=False, tool="memory.delete", output={}, error="memory_id_required")
    deleted = _store().delete_memory(memory_id, hard=False)
    return ToolResult(ok=deleted, tool="memory.delete", output={"deleted": deleted, "hard": False}, error=None if deleted else "memory_not_found")


def pin(args: dict[str, Any]) -> ToolResult:
    """Pin or unpin one persistent memory."""
    memory_id = str(args.get("id") or args.get("memory_id") or "").strip()
    if not memory_id:
        return ToolResult(ok=False, tool="memory.pin", output={}, error="memory_id_required")
    pinned = bool(args.get("pinned", True))
    updated = _store().pin_memory(memory_id, pinned=pinned)
    return ToolResult(ok=updated, tool="memory.pin", output={"pinned": pinned}, error=None if updated else "memory_not_found")


def search(args: dict[str, Any]) -> ToolResult:
    """Search persistent memory using low-latency SQLite FTS ranking."""
    results = _store().search(
        str(args.get("query") or ""),
        limit=int(args.get("limit") or 12),
        status=str(args.get("status") or "active"),
    )
    return ToolResult(ok=True, tool="memory.search", output={"memories": results})


def short_context(args: dict[str, Any]) -> ToolResult:
    """Build short variable context for one channel."""
    context = _store().short_context(
        str(args.get("query") or ""),
        channel=str(args.get("channel") or "control_center"),
        event_limit=int(args.get("event_limit") or 12),
        memory_limit=int(args.get("memory_limit") or 8),
    )
    return ToolResult(ok=True, tool="memory.short_context", output={"context": context})


def compact(args: dict[str, Any]) -> ToolResult:
    """Compact recent channel events or selected memories into a summary."""
    result = _store().compact(
        source_channel=str(args.get("channel") or "control_center"),
        limit=int(args.get("limit") or 40),
        memory_ids=_memory_ids(args) or None,
        archive_originals=bool(args.get("archive_originals") or args.get("archiveOriginals") or False),
    )
    return ToolResult(ok=True, tool="memory.compact", output=result)


def merge(args: dict[str, Any]) -> ToolResult:
    """Merge selected memories into one consolidated memory."""
    result = _store().merge_memories(
        _memory_ids(args),
        text=str(args.get("text") or "").strip() or None,
        archive_originals=bool(args.get("archive_originals") if "archive_originals" in args else True),
    )
    return ToolResult(ok=bool(result.get("created")), tool="memory.merge", output=result, error=None if result.get("created") else str(result.get("reason") or "merge_failed"))


def audit(args: dict[str, Any]) -> ToolResult:
    """Return counters and optional semantic backend health."""
    return ToolResult(ok=True, tool="memory.audit", output={"audit": _store().audit_memories()})


def maintenance(args: dict[str, Any]) -> ToolResult:
    """Run the lightweight manual sleep cycle for memory decay and duplicate cleanup."""
    result = _store().run_maintenance(channel=str(args.get("channel") or "control_center"))
    return ToolResult(ok=True, tool="memory.maintenance", output=result)


def clear_runtime(args: dict[str, Any]) -> ToolResult:
    """Dangerous admin reset for runtime memory; not for normal conversation."""
    result = _store().clear_runtime()
    return ToolResult(ok=True, tool="memory.clear_runtime", output=result)


def list_longterm_memories(args: dict[str, Any]) -> ToolResult:
    """Let Hana query her own long-term persistent memories."""
    all_mems = _store().list_memories(limit=int(args.get("limit") or 50), status=str(args.get("status") or "active"))
    longterm = [
        m for m in all_mems
        if m.get("metadata", {}).get("kind") == "long_term"
        or m.get("kind") == "long_term"
    ]
    return ToolResult(ok=True, tool="memory.list_longterm", output={"memories": longterm, "count": len(longterm)})


def register_memory_tools(registry: ToolRegistry) -> None:
    """Register local memory tools without mixing them with LLM/STT/TTS providers."""
    common_output = {"type": "object"}
    tool_specs = [
        ("memory.append_event", "Append one event to local JSONL runtime memory.", append_event, "low"),
        ("memory.save", "Save a useful persistent memory with optional category, importance and tags.", save, "low"),
        ("memory.update", "Update an existing persistent memory by id.", update, "low"),
        ("memory.delete", "Soft-delete a persistent memory by id. This does not hard-delete.", delete, "low"),
        ("memory.pin", "Pin or unpin a memory so it ranks higher and survives maintenance.", pin, "low"),
        ("memory.search", "Search persistent memory using SQLite FTS ranking.", search, "low"),
        ("memory.short_context", "Build short variable context for one channel.", short_context, "low"),
        ("memory.list_longterm", "List active long-term memories saved by Hana.", list_longterm_memories, "low"),
        ("memory.compact", "Compact recent events or selected memories into one summary.", compact, "low"),
        ("memory.merge", "Merge selected memories into a consolidated memory.", merge, "low"),
        ("memory.audit", "Audit memory status, categories, pinned count, and semantic fallback.", audit, "low"),
        ("memory.maintenance", "Run Hana's manual memory sleep cycle for decay and duplicate cleanup.", maintenance, "low"),
        ("memory.clear_runtime", "Dangerous admin reset for runtime memory; avoid in normal conversation.", clear_runtime, "medium"),
    ]
    for name, description, handler, risk in tool_specs:
        registry.register(
            RegisteredTool(
                name,
                description,
                handler,
                {"type": "object"},
                common_output,
                risk=risk,
                capability_id="memory.module",
            )
        )
