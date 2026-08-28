"""Streaming visual do Terminal não grava deltas no histórico."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from backend.api.services.terminal_agent import (
    publish_terminal_stream,
    subscribe_terminal_stream,
    unsubscribe_terminal_stream,
)
from backend.api.routers import voice


def test_terminal_stream_receives_delta_from_voice_thread() -> None:
    async def scenario() -> None:
        subscription = subscribe_terminal_stream()
        queue = subscription[1]
        try:
            worker = threading.Thread(
                target=lambda: publish_terminal_stream(
                    {"type": "delta", "streamId": "turno", "delta": "Oi"}
                )
            )
            worker.start()
            worker.join()

            assert await asyncio.wait_for(queue.get(), timeout=1) == {
                "type": "delta",
                "streamId": "turno",
                "delta": "Oi",
            }
        finally:
            unsubscribe_terminal_stream(subscription)

    asyncio.run(scenario())


def test_terminal_text_turn_publishes_real_deltas(monkeypatch) -> None:
    published: list[dict] = []

    async def fake_turn(payload, **kwargs):
        await kwargs["on_delta"]("Oi")
        await kwargs["on_delta"](" ao vivo")
        return {
            "text": "Oi ao vivo",
            "meta": {"provider": "qwen", "model": "teste"},
            "status": {"stage": "success"},
        }

    monkeypatch.setattr(voice, "_voice_llm_payload", lambda *args: {"provider": "qwen"})
    monkeypatch.setattr(voice, "run_text_turn", fake_turn)
    monkeypatch.setattr(voice, "append_terminal_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(voice, "publish_terminal_stream", published.append)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(core=object(), memory=object())))

    result = asyncio.run(voice._run_voice_text_response(request, {}, "teste"))

    assert result["text"] == "Oi ao vivo"
    assert [item["type"] for item in published] == ["delta", "delta", "done"]
    assert "".join(item.get("delta", "") for item in published) == "Oi ao vivo"
