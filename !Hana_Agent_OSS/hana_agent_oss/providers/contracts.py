from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderRequest:
    provider: str
    model: str
    messages: list[dict[str, str]]
    temperature: float = 0.7
    native_search_mode: str = "auto"
    channel: str = "control_center"
    attachments: list[dict[str, Any]] = field(default_factory=list)
    media_output_path: str | None = None
    memory: Any | None = None
    streaming: bool = False
    on_token: Any | None = None  # async callable receiving (str) -> None
    on_activity: Any | None = None  # async callable receiving operational activity dicts
    openrouter_routing: dict[str, Any] = field(default_factory=dict)
    # Mutable per-turn collector. Tool runners (e.g. MCP/Tavily) append run records
    # ({tool, server, query, ok, sources}) so the chat can show a search/sources card.
    tool_runs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProviderResponse:
    ok: bool
    text: str = ""
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
