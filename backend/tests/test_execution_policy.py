"""Testes da regra única que escolhe streaming e tools."""

import pytest

from backend.catalog.llm.execution_policy import ExecutionContext, decide_execution_strategy


@pytest.mark.parametrize(
    ("model", "context", "expected_streaming", "expected_tools", "expected_reason"),
    [
        (
            {"supportsStreaming": True},
            ExecutionContext(streaming_requested=True, tools_requested=False),
            True,
            False,
            "streaming",
        ),
        (
            {
                "supportsStreaming": True,
                "supportsTools": True,
                "supportsStreamingTools": True,
            },
            ExecutionContext(streaming_requested=True, tools_requested=True),
            True,
            True,
            "tools_com_streaming",
        ),
        (
            {
                "supportsStreaming": True,
                "supportsTools": True,
                "supportsStreamingTools": False,
            },
            ExecutionContext(streaming_requested=True, tools_requested=True),
            False,
            True,
            "tools_sem_streaming",
        ),
        (
            {"supportsStreaming": True, "supportsTools": False},
            ExecutionContext(streaming_requested=True, tools_requested=True),
            True,
            False,
            "streaming",
        ),
        (None, ExecutionContext(streaming_requested=True, tools_requested=False), False, False, "sem_streaming"),
    ],
)
def test_decide_execution_strategy(
    model,
    context,
    expected_streaming,
    expected_tools,
    expected_reason,
) -> None:
    """Confirma cada combinação aprovada para streaming e tools."""
    strategy = decide_execution_strategy(model, context=context)

    assert strategy.use_streaming is expected_streaming
    assert strategy.use_tools is expected_tools
    assert strategy.reason == expected_reason
