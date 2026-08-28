"""Contratos do catálogo de modelos de conversa (LLMs)."""

from backend.catalog.llm.execution_policy import (
    ExecutionContext,
    ExecutionStrategy,
    decide_execution_strategy,
)

__all__ = ["ExecutionContext", "ExecutionStrategy", "decide_execution_strategy"]
