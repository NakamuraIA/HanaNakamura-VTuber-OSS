"""Decide como uma chamada LLM será executada antes de falar com o provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ExecutionContext:
    """Fatos da chamada que não pertencem ao catálogo do modelo."""

    streaming_requested: bool
    """Indica se o chamador consegue receber partes da resposta."""

    tools_requested: bool
    """Indica se esta chamada pode oferecer tools ao modelo."""

    reasoning_requested: bool = True
    """Indica se o usuário deixou o raciocínio habilitado nesta chamada."""

    internal_call: bool = False
    """Impede streaming em chamadas internas, como o Agent Core."""


@dataclass(frozen=True)
class ExecutionStrategy:
    """Estratégia imutável que o provider recebe para executar uma chamada."""

    use_streaming: bool
    """Indica se a resposta deve chegar gradualmente ao frontend."""

    use_tools: bool
    """Indica se esta chamada oferece tools ao modelo."""

    use_streaming_tools: bool
    """Indica se tools e streaming podem ser usados simultaneamente."""

    use_reasoning: bool
    """Indica se o modelo e o contexto permitem raciocínio nesta chamada."""

    reason: str
    """Explicação curta, útil para logs e para um aviso futuro na interface."""


def _capability(model: Mapping[str, Any] | None, camel_name: str, snake_name: str) -> bool:
    """Lê uma capacidade aceitando o formato da API e o formato interno Python."""
    if not model:
        return False
    value = model.get(camel_name)
    if value is None:
        value = model.get(snake_name)
    return bool(value)


def decide_execution_strategy(
    model: Mapping[str, Any] | None,
    *,
    context: ExecutionContext,
) -> ExecutionStrategy:
    """Escolhe a estratégia uma vez, antes do provider montar a requisição.

    A ausência de informação é tratada como ausência de suporte. Isso é seguro
    durante a migração: o catálogo legado continuará fornecendo capacidades aos
    providers que ainda não foram migrados.
    """
    supports_streaming = _capability(model, "supportsStreaming", "supports_streaming")
    supports_tools = _capability(model, "supportsTools", "supports_tools")
    supports_streaming_tools = _capability(
        model,
        "supportsStreamingTools",
        "supports_streaming_tools",
    )
    use_tools = context.tools_requested and supports_tools
    use_streaming = (
        context.streaming_requested
        and supports_streaming
        and not context.internal_call
    )
    use_reasoning = context.reasoning_requested and _capability(
        model,
        "supportsReasoning",
        "supports_reasoning",
    )

    if use_tools and use_streaming and not supports_streaming_tools:
        return ExecutionStrategy(
            use_streaming=False,
            use_tools=True,
            use_streaming_tools=False,
            use_reasoning=use_reasoning,
            reason="tools_sem_streaming",
        )

    if use_tools:
        return ExecutionStrategy(
            use_streaming=use_streaming,
            use_tools=True,
            use_streaming_tools=use_streaming and supports_streaming_tools,
            use_reasoning=use_reasoning,
            reason="tools_com_streaming" if use_streaming else "tools_sem_streaming",
        )

    return ExecutionStrategy(
        use_streaming=use_streaming,
        use_tools=False,
        use_streaming_tools=False,
        use_reasoning=use_reasoning,
        reason="streaming" if use_streaming else "sem_streaming",
    )
