from __future__ import annotations

import shlex

from hana_agent_oss.core.protocol import (
    AgentRequest,
    PlannerAction,
    PlannerResult,
    ToolCall,
    WorkingContext,
)
from hana_agent_oss.core.registry import CapabilityRegistry, ToolRegistry


class StructuredPlanner:
    """Deterministic planner used before real provider-backed planning exists."""

    def plan(
        self,
        request: AgentRequest,
        *,
        tools: ToolRegistry,
        capabilities: CapabilityRegistry,
        working_context: WorkingContext,
        extra_args: dict[str, str] | None = None,
    ) -> PlannerResult:
        text = str(request.message or "").strip()
        normalized = text.lower()
        extra_args = extra_args or {}
        context_used = {
            "channel": request.channel,
            "local_datetime": request.context.local_datetime if request.context else "",
            "timezone": request.context.timezone if request.context else "",
            "safety_mode": request.safety_mode,
            "tool_count": len(tools.list()),
            "capability_count": len(capabilities.list()),
            "working_context": working_context.to_dict(),
        }

        if normalized == "tools":
            return PlannerResult(PlannerAction("final_answer", message="tools", reason="List registered tools."), context_used=context_used)

        if normalized == "capabilities":
            return PlannerResult(
                PlannerAction("final_answer", message="capabilities", reason="List registered capabilities."),
                context_used=context_used,
            )

        contextual = self._contextual_file_action(normalized, working_context, extra_args)
        if contextual:
            return PlannerResult(PlannerAction("tool_call", tool_call=contextual, reason="Resolved file reference from working context."), context_used=context_used)

        if normalized in {"continua nele", "continuar nele"} and working_context.preferred_file():
            return PlannerResult(
                PlannerAction(
                    "ask_clarification",
                    message="Tenho um arquivo ativo, mas ainda preciso do texto para continuar nele.",
                    reason="Contextual append needs content.",
                ),
                context_used=context_used,
            )

        tool_call = self._explicit_tool_call(text, extra_args)
        if tool_call:
            return PlannerResult(PlannerAction("tool_call", tool_call=tool_call, reason="Parsed explicit deterministic file command."), context_used=context_used)

        if normalized in {"abre ele", "abrir ele", "continua nele", "continuar nele"}:
            return PlannerResult(
                PlannerAction(
                    "ask_clarification",
                    message="Nao ficou claro qual arquivo devo usar. Rode um file.read ou file.write primeiro.",
                    reason="No active file is available in WorkingContext.",
                ),
                context_used=context_used,
            )

        return PlannerResult(
            PlannerAction(
                "planner_not_connected",
                message="Planner LLM is not connected yet. Try: tools, capabilities, file.exists, file.read, file.write, file.append, file.verify_content, memory.search, memory.save, memory.audit, mcp.discover, mcp.invoke, omni.delegate, or omni.supervise.",
                reason="No deterministic intent matched.",
            ),
            context_used=context_used,
        )

    def _contextual_file_action(
        self,
        normalized: str,
        working_context: WorkingContext,
        extra_args: dict[str, str],
    ) -> ToolCall | None:
        path = working_context.preferred_file()
        if not path:
            return None

        if normalized in {"abre ele", "abrir ele"}:
            return ToolCall(tool="file.read", args={"path": path}, reason="User referred to the active file.")

        if normalized in {"continua nele", "continuar nele"}:
            content = extra_args.get("content", "")
            if not content:
                return None
            return ToolCall(tool="file.append", args={"path": path, "content": content}, reason="User asked to continue in the active file.")

        return None

    def _explicit_tool_call(self, message: str, extra_args: dict[str, str]) -> ToolCall | None:
        parts = shlex.split(message, posix=False)
        if not parts:
            return None

        command = parts[0].strip().lower()
        if command in {"file.exists", "file.read"} and len(parts) >= 2:
            return ToolCall(tool=command, args={"path": " ".join(parts[1:]).strip('"')})

        if command == "file.write" and len(parts) >= 2:
            return ToolCall(
                tool="file.write",
                args={"path": " ".join(parts[1:]).strip('"'), "content": extra_args.get("content", "")},
            )

        if command == "file.append" and len(parts) >= 2:
            return ToolCall(
                tool="file.append",
                args={"path": " ".join(parts[1:]).strip('"'), "content": extra_args.get("content", "")},
            )

        if command == "file.verify_content" and len(parts) >= 2:
            return ToolCall(
                tool="file.verify_content",
                args={"path": " ".join(parts[1:]).strip('"'), "contains": extra_args.get("contains", "")},
            )

        if command == "memory.search":
            query = " ".join(parts[1:]).strip('"') if len(parts) >= 2 else extra_args.get("query", "")
            return ToolCall(tool="memory.search", args={"query": query})

        if command == "memory.save":
            text = " ".join(parts[1:]).strip('"') if len(parts) >= 2 else extra_args.get("text", "")
            return ToolCall(tool="memory.save", args={"text": text, "source": "agent_core"})

        if command == "memory.update" and len(parts) >= 2:
            text = " ".join(parts[2:]).strip('"') if len(parts) >= 3 else extra_args.get("text", "")
            return ToolCall(tool="memory.update", args={"id": parts[1].strip('"'), "text": text, "source": "agent_core"})

        if command == "memory.delete" and len(parts) >= 2:
            return ToolCall(tool="memory.delete", args={"id": parts[1].strip('"')})

        if command == "memory.pin" and len(parts) >= 2:
            pinned = str(extra_args.get("pinned") or "true").lower() not in {"0", "false", "no", "off"}
            return ToolCall(tool="memory.pin", args={"id": parts[1].strip('"'), "pinned": pinned})

        if command == "memory.short_context":
            query = " ".join(parts[1:]).strip('"') if len(parts) >= 2 else extra_args.get("query", "")
            return ToolCall(tool="memory.short_context", args={"query": query})

        if command == "memory.compact":
            return ToolCall(tool="memory.compact", args={"channel": extra_args.get("channel", "control_center")})

        if command == "memory.merge":
            ids = [part.strip('"') for part in parts[1:] if part.strip('"')]
            return ToolCall(tool="memory.merge", args={"memory_ids": ids})

        if command == "memory.audit":
            return ToolCall(tool="memory.audit", args={})

        if command in {"memory.maintenance", "memory.maintenance.run"}:
            return ToolCall(tool="memory.maintenance", args={"channel": extra_args.get("channel", "control_center")})

        if command == "memory.clear_runtime":
            return ToolCall(tool="memory.clear_runtime", args={})

        if command == "mcp.discover":
            server_id = " ".join(parts[1:]).strip('"') if len(parts) >= 2 else extra_args.get("server_id", "")
            return ToolCall(tool="mcp.discover", args={"server_id": server_id})

        if command == "mcp.invoke" and len(parts) >= 3:
            raw_args = " ".join(parts[3:]).strip()
            arguments = extra_args.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            if raw_args and not arguments:
                import json

                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
            return ToolCall(tool="mcp.invoke", args={"server_id": parts[1], "tool": parts[2], "arguments": arguments})

        if command in {"omni", "omni.delegate"}:
            task = " ".join(parts[1:]).strip('"') if len(parts) >= 2 else extra_args.get("task", "")
            mode = str(extra_args.get("mode") or "inspect")
            return ToolCall(tool="omni.delegate", args={"task": task, "mode": mode}, reason="User delegated a task to Omni.")

        if command == "omni.supervise":
            task = " ".join(parts[1:]).strip('"') if len(parts) >= 2 else extra_args.get("task", "")
            mode = str(extra_args.get("mode") or "inspect")
            max_rounds = extra_args.get("max_rounds", 3)
            return ToolCall(
                tool="omni.supervise",
                args={"task": task, "mode": mode, "max_rounds": max_rounds},
                reason="User delegated a supervised task to Omni.",
            )

        return None
