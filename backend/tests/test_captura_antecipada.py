"""Regressões da captura de tela iniciada no pressionamento do PTT."""

from __future__ import annotations

import asyncio
import concurrent.futures
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.modules.voice.runtime import VoiceRuntime, VoiceRuntimeConfig
from backend.modules.voice.runtime import coordinator


def _memory() -> MagicMock:
    memory = MagicMock()

    def setting(key: str, default):
        values = {
            "connections_config": {"visao": True},
            "llm_config": {
                "llmProvider": "deepseek",
                "llmModel": "texto",
                "visionProvider": "qwen",
                "visionModel": "visao",
            },
            "agent_settings": {"safety_mode": "safe"},
        }
        return values.get(key, default)

    memory.get_setting.side_effect = setting
    return memory


def test_f2_inicia_captura_quando_fallback_aceita_imagem(monkeypatch) -> None:
    memory = _memory()
    runtime = VoiceRuntime(memory=memory, core=object())
    monkeypatch.setattr(coordinator, "resolve_vision_target", lambda config, store: ("qwen", "visao"))
    monkeypatch.setattr(
        coordinator,
        "model_supports_vision",
        lambda provider, model, store: (provider, model) == ("qwen", "visao"),
    )
    monkeypatch.setattr(
        coordinator,
        "capture_screen",
        lambda store: {"sucesso": True, "b64": "abc", "mime_type": "image/jpeg", "extension": ".jpg"},
    )

    with runtime._lock:
        runtime._ptt_started_at[1] = 10.0
        runtime._start_early_vision_locked(1)
    attachment, marks = asyncio.run(runtime._consume_early_vision(1))
    runtime._vision_executor.shutdown(wait=True)

    assert attachment == {"name": "screen_capture.jpg", "type": "image/jpeg", "data": "abc", "path": None}
    assert marks["pttStarted"] == 10.0
    assert "captureFinished" in marks
    assert not runtime._pending_vision


def test_captura_de_um_turno_nao_vaza_para_outro() -> None:
    runtime = VoiceRuntime(memory=_memory(), core=object())
    first: concurrent.futures.Future[dict] = concurrent.futures.Future()
    second: concurrent.futures.Future[dict] = concurrent.futures.Future()
    first.set_result({"sucesso": True, "b64": "primeira"})
    second.set_result({"sucesso": True, "b64": "segunda"})
    runtime._pending_vision = {1: first, 2: second}

    attachment, _marks = asyncio.run(runtime._consume_early_vision(1))
    runtime._vision_executor.shutdown(wait=True)

    assert attachment and attachment["data"] == "primeira"
    assert 1 not in runtime._pending_vision
    assert runtime._pending_vision[2] is second


def test_turno_de_voz_entrega_captura_antecipada_uma_vez(monkeypatch) -> None:
    memory = _memory()
    received: dict = {}

    async def text_runner(payload, **kwargs):
        received.update(payload)
        return {"text": "ok", "meta": {"provider": "qwen", "model": "visao"}, "status": {"stage": "success"}}

    stt_result = SimpleNamespace(
        text="o que tem na tela?",
        raw_text="o que tem na tela?",
        filtered=False,
        provider="groq_whisper",
        model="whisper-large-v3",
        language="pt",
    )
    runtime = VoiceRuntime(memory=memory, core=object(), stt_factory=lambda: SimpleNamespace(), text_runner=text_runner)
    runtime._config = VoiceRuntimeConfig.from_payload({"sttEnabled": True, "ttsEnabled": False, "pttEnabled": True})
    future: concurrent.futures.Future[dict] = concurrent.futures.Future()
    future.set_result({"sucesso": True, "b64": "imagem", "mime_type": "image/png", "extension": ".png"})
    runtime._pending_vision[7] = future
    runtime._ptt_started_at[7] = 1.0
    monkeypatch.setattr(coordinator, "transcribe_frames", lambda frames, config, provider: stt_result)
    monkeypatch.setattr(coordinator, "build_unified_history", lambda memory, channel: [])

    asyncio.run(runtime._process_utterance([b"audio"], {"visionTurnId": 7}))
    runtime._vision_executor.shutdown(wait=True)

    assert received["vision_pre_captured"] is True
    assert received["attachments"][0]["data"] == "imagem"
    assert 7 not in runtime._pending_vision
