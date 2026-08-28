"""Ponto único que conhece o mapa provider_id -> classe STT e como montá-la.

O contrato compartilhado (``STTTranscriptionResult``/``STTConfigurationError``)
mora AQUI, não dentro do arquivo de um provider específico — assim nenhum STT
novo "empresta" o nome de outro pra falar a mesma língua (o mesmo problema que
o TTS tinha antes de existir ``tts_registry.py``).

STT novo: escreve ``stt_<nome>.py`` com um método
``transcribe_bytes(audio, *, filename, model, language, prompt)`` devolvendo
um ``STTTranscriptionResult``, e registra uma entrada em ``_BUILDERS``/
``_LABELS`` aqui embaixo. O import da classe do provider é feito DENTRO do
builder (não no topo do arquivo) de propósito: evita import circular, já que
``stt_whisper.py`` importa o contrato deste módulo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "STTTranscriptionResult",
    "STTConfigurationError",
    "SUPPORTED_STT_PROVIDERS",
    "DEFAULT_STT_PROVIDER",
    "provider_label",
    "build_stt_provider",
]


class STTConfigurationError(RuntimeError):
    """Raised when the selected STT provider cannot run."""


@dataclass(frozen=True)
class STTTranscriptionResult:
    provider: str
    model: str
    language: str
    text: str
    raw_text: str
    filtered: bool


DEFAULT_STT_PROVIDER = "groq_whisper"


def _build_groq_whisper(**_ignored: Any) -> Any:
    from backend.providers.stt.whisper import GroqWhisperSTTProvider

    return GroqWhisperSTTProvider()


def _build_openrouter(*, model: str = "", language: str = "", **_ignored: Any) -> Any:
    from backend.providers.stt.openrouter import OpenRouterSTTProvider

    return OpenRouterSTTProvider(model=model or None, language=language or None)


# provider_id -> (funcao que monta a classe, rotulo pra evento/log)
_BUILDERS = {
    "groq_whisper": _build_groq_whisper,
    "openrouter": _build_openrouter,
}

_LABELS = {
    "groq_whisper": "Groq Whisper",
    "openrouter": "OpenRouter STT",
}

SUPPORTED_STT_PROVIDERS = frozenset(_BUILDERS)


def provider_label(provider_id: str) -> str:
    return _LABELS.get(provider_id, provider_id)


def build_stt_provider(provider_id: str, **kwargs: Any) -> Any:
    """Constrói o provider certo a partir do nome.

    Model/language/prompt de cada transcrição são passados por chamada (em
    ``transcribe_bytes``), não na construção — por isso nenhum kwarg é
    obrigatório aqui hoje. Mantido `**kwargs` pra um provider futuro que
    precise de algo na construção (ex.: client próprio).
    """
    builder = _BUILDERS.get(provider_id)
    if builder is None:
        raise STTConfigurationError(f"Provider STT não suportado: {provider_id}.")
    return builder(**kwargs)


def _self_check() -> None:
    groq = build_stt_provider("groq_whisper")
    assert groq.provider_id == "groq_whisper"

    openrouter = build_stt_provider("openrouter", model="openai/whisper-1")
    assert openrouter.provider_id == "openrouter"
    assert openrouter.model == "openai/whisper-1"

    try:
        build_stt_provider("gemini_audio")
    except STTConfigurationError:
        pass
    else:
        raise AssertionError("provider inexistente deveria levantar STTConfigurationError")

    assert SUPPORTED_STT_PROVIDERS == {"groq_whisper", "openrouter"}
    assert provider_label("openrouter") == "OpenRouter STT"
    print("providers.stt.registry: ok")


if __name__ == "__main__":
    _self_check()
