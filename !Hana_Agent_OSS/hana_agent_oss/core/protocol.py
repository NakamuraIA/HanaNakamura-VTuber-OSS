from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


CapabilityType = Literal[
    "tool",
    "module",
    "integration",
    "subbrain",
    "external_process",
    "plugin",
    "channel",
    "adapter",
]

TransportKind = Literal["python", "http", "stdio", "websocket", "node", "rust", "subprocess"]
PlannerActionType = Literal[
    "assistant_message",
    "tool_call",
    "final_answer",
    "ask_clarification",
    "planner_not_connected",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def local_timezone_name() -> str:
    local_now = datetime.now().astimezone()
    return local_now.tzname() or str(local_now.tzinfo or "")


@dataclass(frozen=True)
class RequestContext:
    created_at_utc: str
    local_datetime: str
    timezone: str
    cwd: str
    channel: str
    user_id: str
    safety_mode: str

    @classmethod
    def build(
        cls,
        *,
        channel: str,
        user_id: str,
        safety_mode: str,
        cwd: str | Path | None = None,
    ) -> "RequestContext":
        return cls(
            created_at_utc=utc_now_iso(),
            local_datetime=local_now_iso(),
            timezone=local_timezone_name(),
            cwd=str(Path(cwd).resolve() if cwd is not None else Path.cwd().resolve()),
            channel=str(channel or "control_center"),
            user_id=str(user_id or "local_user"),
            safety_mode=str(safety_mode or "safe"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at_utc": self.created_at_utc,
            "local_datetime": self.local_datetime,
            "timezone": self.timezone,
            "cwd": self.cwd,
            "channel": self.channel,
            "user_id": self.user_id,
            "safety_mode": self.safety_mode,
        }


@dataclass(frozen=True)
class ChannelProfile:
    id: str
    name: str
    response_style: str
    supports_markdown: bool
    supports_tts: bool = False
    supports_user_updates: bool = True
    max_update_chars: int = 800

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "response_style": self.response_style,
            "supports_markdown": self.supports_markdown,
            "supports_tts": self.supports_tts,
            "supports_user_updates": self.supports_user_updates,
            "max_update_chars": self.max_update_chars,
        }


@dataclass
class AgentRequest:
    message: str
    channel: str = "control_center"
    user_id: str = "local_user"
    safety_mode: str = "safe"
    context: RequestContext | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.context is None:
            self.context = RequestContext.build(
                channel=self.channel,
                user_id=self.user_id,
                safety_mode=self.safety_mode,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "channel": self.channel,
            "user_id": self.user_id,
            "safety_mode": self.safety_mode,
            "context": self.context.to_dict() if self.context else None,
            "attachments": self.attachments,
            "metadata": self.metadata,
        }


@dataclass
class AgentEvent:
    type: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "agent_core"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "payload": self.payload,
            "source": self.source,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "reason": self.reason, "risk": self.risk}


@dataclass
class ToolResult:
    ok: bool
    tool: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "output": self.output,
            "error": self.error,
            "artifacts": self.artifacts,
        }


@dataclass
class WorkingContext:
    active_file: str | None = None
    last_created_file: str | None = None
    last_written_file: str | None = None
    last_tool_result: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WorkingContext":
        data = data or {}
        return cls(
            active_file=data.get("active_file"),
            last_created_file=data.get("last_created_file"),
            last_written_file=data.get("last_written_file"),
            last_tool_result=data.get("last_tool_result"),
        )

    def preferred_file(self) -> str | None:
        return self.active_file or self.last_written_file or self.last_created_file

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_file": self.active_file,
            "last_created_file": self.last_created_file,
            "last_written_file": self.last_written_file,
            "last_tool_result": self.last_tool_result,
        }


@dataclass(frozen=True)
class PlannerAction:
    type: PlannerActionType
    tool_call: ToolCall | None = None
    message: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "tool_call": self.tool_call.to_dict() if self.tool_call else None,
            "message": self.message,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlannerResult:
    action: PlannerAction
    source: str = "structured_deterministic"
    context_used: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "source": self.source,
            "context_used": self.context_used,
        }


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    method: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "method": self.method,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class CapabilityManifest:
    id: str
    name: str
    type: CapabilityType
    version: str = "0.1.0"
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    entrypoint: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    channels: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    transport: TransportKind = "python"
    language: str = "python"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "version": self.version,
            "description": self.description,
            "capabilities": self.capabilities,
            "entrypoint": self.entrypoint,
            "permissions": self.permissions,
            "channels": self.channels,
            "dependencies": self.dependencies,
            "transport": self.transport,
            "language": self.language,
        }


@dataclass
class AgentResponse:
    ok: bool
    response: str
    events: list[AgentEvent] = field(default_factory=list)
    channel: str = "control_center"
    context: RequestContext | None = None
    working_context: WorkingContext | None = None
    planner_result: PlannerResult | None = None
    tool_result: ToolResult | None = None
    verification: VerificationResult | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "response": self.response,
            "context": self.context.to_dict() if self.context else None,
            "working_context": self.working_context.to_dict() if self.working_context else None,
            "events": [event.to_dict() for event in self.events],
            "planner_result": self.planner_result.to_dict() if self.planner_result else None,
            "tool_result": self.tool_result.to_dict() if self.tool_result else None,
            "verification": self.verification.to_dict() if self.verification else None,
            "data": self.data,
            "channel": self.channel,
            "error": self.error,
        }
