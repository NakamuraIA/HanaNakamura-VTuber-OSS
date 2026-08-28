__all__ = ["HanaAgentCore"]


def __getattr__(name: str):
    if name == "HanaAgentCore":
        from backend.core.runtime import HanaAgentCore

        return HanaAgentCore
    raise AttributeError(f"module 'backend' has no attribute {name!r}")
