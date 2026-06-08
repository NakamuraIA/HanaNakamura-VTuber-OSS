__all__ = ["HanaAgentCore"]


def __getattr__(name: str):
    if name == "HanaAgentCore":
        from hana_agent_oss.core.runtime import HanaAgentCore

        return HanaAgentCore
    raise AttributeError(f"module 'hana_agent_oss' has no attribute {name!r}")
