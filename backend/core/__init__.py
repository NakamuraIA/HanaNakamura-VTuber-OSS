"""Coordenação da execução do agente.

Contrato da pasta:
- protocol.py : os dataclasses do turno (AgentRequest/Response, ToolCall...).
- planner.py / executor.py / verifier.py : planeja, executa e verifica.
- registry.py : registros de integração/subbrain/plugin (placeholders).
- runtime.py  : HanaAgentCore, o orquestrador que a API chama por turno.
- runtime.py persiste o turno por meio de memory/storage.py (RuntimeStore).

Regra: core/ não conhece HTTP nem executa SQL direto; api/ e memory/ fazem
essas traduções.
"""

from backend.core.protocol import (
    AgentEvent,
    AgentRequest,
    AgentResponse,
    CapabilityManifest,
    ChannelProfile,
    PlannerAction,
    PlannerResult,
    RequestContext,
    ToolCall,
    ToolResult,
    VerificationResult,
    WorkingContext,
)

__all__ = [
    "AgentEvent",
    "AgentRequest",
    "AgentResponse",
    "CapabilityManifest",
    "ChannelProfile",
    "HanaAgentCore",
    "PlannerAction",
    "PlannerResult",
    "RequestContext",
    "RuntimeStore",
    "ToolCall",
    "ToolResult",
    "VerificationResult",
    "WorkingContext",
]


def __getattr__(name: str):
    if name == "HanaAgentCore":
        from backend.core.runtime import HanaAgentCore

        return HanaAgentCore
    if name == "RuntimeStore":
        from backend.memory.storage import RuntimeStore

        return RuntimeStore
    raise AttributeError(f"module 'backend.core' has no attribute {name!r}")
