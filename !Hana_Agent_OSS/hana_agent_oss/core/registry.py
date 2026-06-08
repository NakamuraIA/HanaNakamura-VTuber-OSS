from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hana_agent_oss.core.protocol import CapabilityManifest, ToolCall, ToolResult


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    handler: Callable[[dict[str, Any]], ToolResult]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk: str = "low"
    capability_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "risk": self.risk,
            "capability_id": self.capability_id,
        }


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, CapabilityManifest] = {}

    def register(self, manifest: CapabilityManifest) -> None:
        if not manifest.id:
            raise ValueError("Capability id is required.")
        self._items[manifest.id] = manifest

    def get(self, capability_id: str) -> CapabilityManifest:
        return self._items[capability_id]

    def list(self, *, type: str | None = None) -> list[CapabilityManifest]:
        items = list(self._items.values())
        if type is None:
            return items
        return [item for item in items if item.type == type]


class ToolRegistry:
    def __init__(self) -> None:
        self._items: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        if not tool.name:
            raise ValueError("Tool name is required.")
        self._items[tool.name] = tool

    def get(self, name: str) -> RegisteredTool:
        return self._items[name]

    def list(self) -> list[RegisteredTool]:
        return list(self._items.values())

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self.get(call.tool)
        return tool.handler(call.args)


class IntegrationRegistry(CapabilityRegistry):
    pass


class SubbrainRegistry(CapabilityRegistry):
    pass


class PluginRegistry(CapabilityRegistry):
    pass
