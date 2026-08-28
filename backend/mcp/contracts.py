from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpServerConfig:
    id: str
    name: str
    enabled: bool
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout: float = 20.0
    allowed_tools: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "McpServerConfig":
        return cls(
            id=str(data.get("id") or "").strip(),
            name=str(data.get("name") or data.get("id") or "").strip(),
            enabled=bool(data.get("enabled", False)),
            command=str(data.get("command") or "").strip(),
            args=[str(item) for item in data.get("args", []) if str(item).strip()],
            env={str(key): str(value) for key, value in (data.get("env") or {}).items()},
            cwd=str(data["cwd"]) if data.get("cwd") else None,
            timeout=float(data.get("timeout") or 20.0),
            allowed_tools=[str(item) for item in data.get("allowed_tools", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "cwd": self.cwd,
            "timeout": self.timeout,
            "allowed_tools": self.allowed_tools,
        }


@dataclass
class McpToolInfo:
    server_id: str
    name: str
    title: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "annotations": self.annotations,
        }


@dataclass
class McpCallRequest:
    server_id: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpCallResult:
    ok: bool
    content: list[dict[str, Any]] = field(default_factory=list)
    structured_content: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "content": self.content,
            "structuredContent": self.structured_content,
            "isError": self.is_error,
            "raw": self.raw,
            "error": self.error,
        }
