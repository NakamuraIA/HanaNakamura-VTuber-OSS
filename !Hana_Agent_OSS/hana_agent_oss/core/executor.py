from __future__ import annotations

from hana_agent_oss.core.protocol import AgentEvent, ToolCall, ToolResult
from hana_agent_oss.core.registry import ToolRegistry


class DeterministicExecutor:
    """Executes explicit ToolCalls without LLM planning."""

    def __init__(self, tools: ToolRegistry):
        self.tools = tools

    def execute(self, call: ToolCall) -> tuple[ToolResult, list[AgentEvent]]:
        events = [
            AgentEvent(
                type="tool_call",
                message=f"Executing {call.tool}.",
                payload={"tool_call": call.to_dict()},
            )
        ]
        try:
            result = self.tools.execute(call)
        except KeyError as exc:
            result = ToolResult(ok=False, tool=call.tool, error=f"Tool not registered: {call.tool}")
            events.append(
                AgentEvent(
                    type="tool_result",
                    message=f"{call.tool} failed.",
                    payload={"tool_result": result.to_dict(), "error": str(exc)},
                )
            )
            return result, events

        events.append(
            AgentEvent(
                type="tool_result",
                message=f"{call.tool} {'succeeded' if result.ok else 'failed'}.",
                payload={"tool_result": result.to_dict()},
            )
        )
        return result, events

