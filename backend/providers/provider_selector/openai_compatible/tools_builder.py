"""Agregador das ferramentas compartilhadas por providers OpenAI-compatible."""

from __future__ import annotations

from typing import Any, Callable

from backend.providers.contracts import ProviderRequest
from backend.tools.mcp_provider_tools import mcp_openai_runners, mcp_openai_schemas
from .image_tools import register_image_tools
from .local_hands import register_local_hands
from .memory_skills import register_memory_skills
from .policy import apply_tool_policy
from .reminders import register_reminders


def build_tool_schemas_and_runners(
    provider: Any,
    request: ProviderRequest,
    *,
    supports_tools: bool,
) -> tuple[list[dict[str, Any]], dict[str, Callable[[dict[str, Any]], dict[str, Any]]]]:
    """Monta schemas e executores sem atribuir as ferramentas a um provider específico."""
    connections: dict[str, Any] = {}
    if request.memory is not None:
        try:
            raw = request.memory.get_setting("connections_config", {}) or {}
            from backend.api.routers.config import normalize_connections_config
            connections = normalize_connections_config(raw)
        except Exception:
            connections = {}

    if not getattr(request, "allow_tools", True):
        return [], {}

    tools: list[dict[str, Any]] = list(mcp_openai_schemas())
    runners: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = dict(
        mcp_openai_runners(request.memory, manager=request.mcp_manager)
    )
    if not supports_tools:
        return [], {}

    register_local_hands(provider, request, connections, tools, runners)
    register_reminders(provider, request, connections, tools, runners)
    register_memory_skills(provider, request, connections, tools, runners)
    register_image_tools(provider, request, connections, tools, runners)
    apply_tool_policy(provider, request, connections, tools, runners)
    return [provider._sanitize_tool_schema(schema) for schema in tools], runners
