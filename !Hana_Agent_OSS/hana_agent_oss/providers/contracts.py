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
    # Voice call mode: the transcription may come from anyone in the call, not the
    # main user. Switches the system prompt to group-participant behavior.
    call_mode: bool = False
    attachments: list[dict[str, Any]] = field(default_factory=list)
    media_output_path: str | None = None
    memory: Any | None = None
    streaming: bool = False
    # Internal sub-calls (sleep-cycle summaries, screen_find vision queries) set this
    # False so the model just answers text instead of wandering into tool calls.
    allow_tools: bool = True
    on_token: Any | None = None  # async callable receiving (str) -> None
    on_activity: Any | None = None  # async callable receiving operational activity dicts
    on_reasoning: Any | None = None  # async callable for reasoning tokens (str) -> None
    on_tool_activity: Any | None = None  # async callable for per-tool events (dict) -> None
    openrouter_routing: dict[str, Any] = field(default_factory=dict)
    # Groq "thinker" switch: when False, reasoning models (qwen3/gpt-oss) skip their
    # hidden chain-of-thought (reasoning_effort=none) for a fast, direct answer. When
    # True they think before answering. Voice/terminal also auto-disable thinking.
    thinking: bool = True
    # Explicit reasoning depth (OpenRouter's unified scale: none/minimal/low/medium/
    # high/max). When set, overrides the on/off "thinking" heuristic for providers
    # that support graded effort (currently only OpenRouter). None = use "thinking".
    reasoning_effort: str | None = None
    # "Pensar" do MODELO DE AGENTE (loop de ferramentas), independente do chat.
    # Quando o chat escala pro agente (cérebro econômico), esses valores mandam no
    # esforço dele em vez de herdar o do chat. Mesma semantica de thinking/reasoning_effort.
    agent_thinking: bool = True
    agent_reasoning_effort: str | None = None
    # Mutable per-turn collector. Tool runners (e.g. MCP/Tavily) append run records
    # ({tool, server, query, ok, sources}) so the chat can show a search/sources card.
    tool_runs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProviderResponse:
    ok: bool
    text: str = ""
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
