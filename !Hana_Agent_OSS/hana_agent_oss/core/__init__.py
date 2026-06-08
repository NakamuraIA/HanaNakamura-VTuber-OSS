from hana_agent_oss.core.protocol import (
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
        from hana_agent_oss.core.runtime import HanaAgentCore

        return HanaAgentCore
    if name == "RuntimeStore":
        from hana_agent_oss.memory.storage import RuntimeStore

        return RuntimeStore
    raise AttributeError(f"module 'hana_agent_oss.core' has no attribute {name!r}")
