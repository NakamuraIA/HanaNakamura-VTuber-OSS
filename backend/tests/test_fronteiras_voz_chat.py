"""Contratos arquiteturais da fase 6."""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.api.services.chat import handle_chat_payload, run_text_turn
from backend.api.services.chat.coordinator import _provider_error_token
from backend.core.protocol import AgentResponse
from backend.modules.voice.runtime import VoiceRuntime
from backend.providers.stt.registry import SUPPORTED_STT_PROVIDERS
from backend.providers.tts.registry import SUPPORTED_TTS_PROVIDERS

ROOT = Path(__file__).resolve().parents[1]


def test_interfaces_publicas_continuam_importaveis() -> None:
    assert callable(handle_chat_payload)
    assert callable(run_text_turn)
    assert VoiceRuntime.__name__ == "VoiceRuntime"


def test_integracoes_externas_nao_ficam_em_modules_voice() -> None:
    voice = ROOT / "modules" / "voice"
    forbidden = ("tts_edge.py", "tts_elevenlabs.py", "tts_fishaudio.py", "stt_whisper.py", "stt_openrouter.py")

    assert not any((voice / name).exists() for name in forbidden)
    assert SUPPORTED_TTS_PROVIDERS == {"edge", "fishaudio", "elevenlabs"}
    assert SUPPORTED_STT_PROVIDERS == {"groq_whisper", "openrouter"}


def test_agent_core_remove_xml_privado_da_resposta() -> None:
    class Memory:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        def get_setting(self, _key: str, default: object) -> object:
            return default

        def append_event(self, author: str, text: str, **_kwargs: object) -> None:
            self.events.append((author, text))

    class Core:
        def run(self, _request: object) -> AgentResponse:
            return AgentResponse(
                ok=True,
                response="<salvar_memoria>segredo apenas da memoria</salvar_memoria>Resposta visivel.",
            )

    memory = Memory()
    result = asyncio.run(
        run_text_turn(
            {"text": "teste", "provider": "agent_core", "channel": "voice"},
            core=Core(),
            memory=memory,
        )
    )

    assert result["text"] == "Resposta visivel."
    assert memory.events[-1] == ("hana", "Resposta visivel.")


def test_streaming_reconhece_erro_do_provider_sem_exibir_como_texto() -> None:
    assert _provider_error_token("[ERRO: provider_indisponivel]") == "[ERRO: provider_indisponivel]"
    assert _provider_error_token("Resposta normal.") is None
