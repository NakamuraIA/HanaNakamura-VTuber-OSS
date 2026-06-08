from __future__ import annotations

from hana_agent_oss.core.executor import DeterministicExecutor
from hana_agent_oss.core.planner import StructuredPlanner
from hana_agent_oss.core.protocol import (
    AgentEvent,
    AgentRequest,
    AgentResponse,
    CapabilityManifest,
    ToolCall,
    ToolResult,
    VerificationResult,
    WorkingContext,
)
from hana_agent_oss.core.registry import (
    CapabilityRegistry,
    IntegrationRegistry,
    PluginRegistry,
    SubbrainRegistry,
    ToolRegistry,
)
from hana_agent_oss.memory.storage import RuntimeStore
from hana_agent_oss.core.verifier import ToolVerifier
from hana_agent_oss.mcp.manager import McpManager
from hana_agent_oss.mcp.tools import register_mcp_tools
from hana_agent_oss.tools.file_tools import register_file_tools
from hana_agent_oss.tools.memory_tools import register_memory_tools
from hana_agent_oss.tools.omni_tools import DEFAULT_OMNI_BASE_URL, register_omni_tools


class HanaAgentCore:
    """New standalone Agent Core foundation for Hana Agent OSS."""

    def __init__(self, *, store: RuntimeStore | None = None) -> None:
        self.channels = {}
        self.capabilities = CapabilityRegistry()
        self.tools = ToolRegistry()
        self.integrations = IntegrationRegistry()
        self.subbrains = SubbrainRegistry()
        self.plugins = PluginRegistry()
        self.store = store or RuntimeStore()
        self.mcp = McpManager()
        self._register_builtin_capabilities()
        self.planner = StructuredPlanner()
        self.executor = DeterministicExecutor(self.tools)
        self.verifier = ToolVerifier(self.tools)

    def _register_builtin_capabilities(self) -> None:
        self.capabilities.register(
            CapabilityManifest(
                id="hana.agent_core",
                name="Hana Agent Core",
                type="module",
                version="0.1.0",
                description="Standalone modular core foundation.",
                capabilities=["agent.request", "agent.event", "agent.response"],
                entrypoint={"kind": "python", "module": "hana_agent_oss.core"},
                permissions={"risk": "low", "requires_user_enable": False},
            )
        )
        self.capabilities.register(
            CapabilityManifest(
                id="file.module",
                name="Local File Tools",
                type="tool",
                version="0.1.0",
                description="Deterministic local file inspection and controlled write tools.",
                capabilities=["file.exists", "file.read", "file.write", "file.append", "file.verify_content"],
                entrypoint={"kind": "python", "module": "hana_agent_oss.tools.file_tools"},
                permissions={"risk": "medium", "requires_user_enable": False},
            )
        )
        self.capabilities.register(
            CapabilityManifest(
                id="memory.module",
                name="Local Memory Tools",
                type="tool",
                version="0.1.0",
                description="Runtime memory CRUD, search, compaction, maintenance, and event append tools.",
                capabilities=[
                    "memory.append_event",
                    "memory.save",
                    "memory.update",
                    "memory.delete",
                    "memory.pin",
                    "memory.short_context",
                    "memory.search",
                    "memory.compact",
                    "memory.merge",
                    "memory.audit",
                    "memory.maintenance",
                    "memory.clear_runtime",
                    "memory.list_longterm",
                ],
                entrypoint={"kind": "python", "module": "hana_agent_oss.tools.memory_tools"},
                permissions={"risk": "medium", "requires_user_enable": False},
            )
        )
        self.capabilities.register(
            CapabilityManifest(
                id="omni.bridge",
                name="Omni Bridge",
                type="adapter",
                version="0.1.0",
                description="HTTP bridge to the local Omni-Agent OS executor.",
                capabilities=["omni.delegate", "omni.supervise"],
                entrypoint={"kind": "http", "url": f"{DEFAULT_OMNI_BASE_URL}/api/command"},
                permissions={"risk": "medium", "requires_user_enable": False},
                transport="http",
            )
        )
        register_file_tools(self.tools)
        register_memory_tools(self.tools)
        register_mcp_tools(self.tools, self.mcp)
        register_omni_tools(self.tools)

    def run(
        self,
        request: AgentRequest | str,
        *,
        channel: str = "control_center",
        extra_args: dict[str, str] | None = None,
    ) -> AgentResponse:
        agent_request = request if isinstance(request, AgentRequest) else AgentRequest(str(request), channel=channel)
        profile_id = agent_request.channel
        working_context = self.store.load_working_context()
        events = [
            AgentEvent(
                type="request_received",
                message="Request received by the new Hana Agent Core.",
                payload={"channel": profile_id, "context": agent_request.context.to_dict() if agent_request.context else {}},
            ),
        ]
        self.store.save_request(agent_request)

        planner_result = self.planner.plan(
            agent_request,
            tools=self.tools,
            capabilities=self.capabilities,
            working_context=working_context,
            extra_args=extra_args,
        )
        events.append(
            AgentEvent(
                type="planner_result",
                message=f"Planner selected {planner_result.action.type}.",
                payload={"planner_result": planner_result.to_dict()},
            )
        )

        if planner_result.action.type == "final_answer" and planner_result.action.message == "tools":
            response = AgentResponse(
                ok=True,
                response="Registered tools listed.",
                events=events,
                channel=profile_id,
                context=agent_request.context,
                working_context=working_context,
                planner_result=planner_result,
                data={"tools": [tool.to_dict() for tool in self.tools.list()]},
            )
            return self._persist_response(response)

        if planner_result.action.type == "final_answer" and planner_result.action.message == "capabilities":
            response = AgentResponse(
                ok=True,
                response="Registered capabilities listed.",
                events=events,
                channel=profile_id,
                context=agent_request.context,
                working_context=working_context,
                planner_result=planner_result,
                data={"capabilities": [manifest.to_dict() for manifest in self.capabilities.list()]},
            )
            return self._persist_response(response)

        if planner_result.action.type == "tool_call" and planner_result.action.tool_call:
            tool_call = planner_result.action.tool_call
            tool_result, tool_events = self.executor.execute(tool_call)
            events.extend(tool_events)
            self.store.save_tool_run(tool_call, tool_result)
            verification = self.verifier.verify(tool_call, tool_result)
            events.append(
                AgentEvent(
                    type="verification",
                    message=verification.message,
                    payload={"verification": verification.to_dict()},
                )
            )
            working_context = self._updated_working_context(working_context, tool_call, tool_result)
            self.store.save_working_context(working_context)
            response = AgentResponse(
                ok=tool_result.ok and verification.ok,
                response=self._compose_tool_response(tool_call, tool_result, verification),
                events=events,
                channel=profile_id,
                context=agent_request.context,
                working_context=working_context,
                planner_result=planner_result,
                tool_result=tool_result,
                verification=verification,
                error=None if tool_result.ok and verification.ok else tool_result.error or verification.message,
            )
            return self._persist_response(response)

        if planner_result.action.type == "ask_clarification":
            response = AgentResponse(
                ok=False,
                response=planner_result.action.message,
                events=events,
                channel=profile_id,
                context=agent_request.context,
                working_context=working_context,
                planner_result=planner_result,
                error="ask_clarification",
            )
            return self._persist_response(response)

        response = AgentResponse(
            ok=False,
            response=planner_result.action.message or "Planner LLM is not connected yet.",
            events=events,
            channel=profile_id,
            context=agent_request.context,
            working_context=working_context,
            planner_result=planner_result,
            error="planner_not_connected",
        )
        return self._persist_response(response)

    def list_capabilities(self) -> list[CapabilityManifest]:
        return self.capabilities.list()

    def _persist_response(self, response: AgentResponse) -> AgentResponse:
        for event in response.events:
            self.store.save_event(event)
        self.store.save_response(response)
        return response

    def _updated_working_context(
        self,
        working_context: WorkingContext,
        call: ToolCall,
        result: ToolResult,
    ) -> WorkingContext:
        updated = WorkingContext.from_dict(working_context.to_dict())
        updated.last_tool_result = result.to_dict()
        if not result.ok:
            return updated

        path = str(result.output.get("path") or call.args.get("path") or "")
        if call.tool in {"file.read", "file.exists"} and path:
            updated.active_file = path
        if call.tool == "file.write" and path:
            updated.active_file = path
            updated.last_created_file = path
            updated.last_written_file = path
        if call.tool == "file.append" and path:
            updated.active_file = path
            updated.last_written_file = path
        return updated

    def _compose_tool_response(
        self,
        call: ToolCall,
        result: ToolResult,
        verification: VerificationResult,
    ) -> str:
        """Compose a concise user-facing response from one deterministic tool run."""
        if not result.ok:
            return f"{call.tool} failed: {result.error}"
        if not verification.ok:
            return f"{call.tool} executed, but verification failed: {verification.message}"
        if call.tool == "file.read":
            path = str(result.output.get("path") or call.args.get("path") or "")
            content = str(result.output.get("content") or "")
            if len(content) > 4000:
                content = content[:4000].rstrip() + "\n\n[conteudo truncado]"
            return f"Conteudo de {path}:\n{content}"
        if call.tool == "file.exists":
            path = str(result.output.get("path") or call.args.get("path") or "")
            exists = "existe" if result.output.get("exists") else "nao existe"
            kind = "diretorio" if result.output.get("is_dir") else "arquivo" if result.output.get("is_file") else "path"
            return f"{path}: {exists} ({kind})."
        if call.tool.startswith("memory."):
            if call.tool in {"memory.save", "memory.update"}:
                memory = result.output.get("memory") if isinstance(result.output, dict) else {}
                memory_id = str(memory.get("id") or "") if isinstance(memory, dict) else ""
                return f"Memoria salva ({memory_id[:8]})." if memory_id else "Memoria salva."
            if call.tool == "memory.delete":
                return "Memoria movida para lixeira." if result.output.get("deleted") else "Memoria nao encontrada."
            if call.tool == "memory.pin":
                return "Memoria fixada." if result.output.get("pinned") else "Memoria desafixada."
            if call.tool in {"memory.compact", "memory.merge"}:
                return "Memorias compactadas." if result.output.get("created") else f"Nada para compactar: {result.output.get('reason', 'sem_dados')}."
            if call.tool == "memory.maintenance":
                return "Manutencao de memoria executada."
            if call.tool == "memory.audit":
                return f"Auditoria de memoria: {result.output.get('audit')}"
            return f"{call.tool} retornou: {result.output}"
        if call.tool in {"omni.delegate", "omni.supervise"}:
            status = str(result.output.get("status") or "unknown")
            completion_status = str(result.output.get("completion_status") or "needs_review")
            round_count = result.output.get("round_count")
            response = str(result.output.get("response") or "").strip()
            if len(response) > 4000:
                response = response[:4000].rstrip() + "\n\n[resposta do Omni truncada]"
            rounds = f" em {round_count} rodada(s)" if round_count else ""
            return f"Omni retornou ({status}, {completion_status}){rounds}:\n{response}"
        if call.tool in {"file.write", "file.append"}:
            return f"{call.tool} executed and verified."
        return f"{call.tool} executed."
