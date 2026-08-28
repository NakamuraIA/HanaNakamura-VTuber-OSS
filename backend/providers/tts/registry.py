"""Ponto único que conhece o mapa provider_id -> classe TTS e como montá-la.

Antes disso essa escolha existia em DOIS lugares (``runtime.py`` e
``routers/voice.py``), cada um com sua própria lista de "provider permitido"
— e as duas já tinham saído de sincronia uma da outra.

TTS novo: escreve ``tts_<nome>.py`` com ``synthesize()`` (e opcionalmente
``stream_audio_chunks()``, ver ``tts_edge.py``), e registra uma entrada em
``_BUILDERS``/``_LABELS`` aqui embaixo. Isso e o cadastro da voz/modelo em
``catalog/tts_repository.py`` (ver ``docs/DECISOES_CATALOGO_FONTES.md`` §12)
são as duas únicas coisas que faltam pra ele existir pro resto do sistema.
"""

from __future__ import annotations

from typing import Any

from backend.providers.tts.edge import EdgeTTSProvider, TTSConfigurationError
from backend.providers.tts.elevenlabs import (
    DEFAULT_ELEVENLABS_MODEL,
    DEFAULT_ELEVENLABS_VOICE,
    ElevenlabsTTSProvider,
)
from backend.providers.tts.fishaudio import DEFAULT_FISHAUDIO_MODEL, FishAudioTTSProvider

__all__ = [
    "TTSConfigurationError",
    "SUPPORTED_TTS_PROVIDERS",
    "DEFAULT_TTS_PROVIDER",
    "provider_label",
    "build_tts_provider",
]

DEFAULT_TTS_PROVIDER = "edge"


def _build_edge(*, voice: str, speed: float, pitch: float, **_ignored: Any) -> EdgeTTSProvider:
    return EdgeTTSProvider(voice=voice, speed=speed, pitch=pitch)


def _build_fishaudio(*, voice: str, model: str, speed: float, latency: str, **_ignored: Any) -> FishAudioTTSProvider:
    return FishAudioTTSProvider(
        voice=voice or "",
        model=model or DEFAULT_FISHAUDIO_MODEL,
        speed=speed,
        latency=latency or "balanced",
    )


def _build_elevenlabs(
    *,
    voice: str,
    model: str,
    language: str,
    speed: float,
    stability: float,
    similarity: float,
    style: float,
    speaker_boost: bool,
    **_ignored: Any,
) -> ElevenlabsTTSProvider:
    return ElevenlabsTTSProvider(
        voice=voice or DEFAULT_ELEVENLABS_VOICE,
        model=model or DEFAULT_ELEVENLABS_MODEL,
        language=language or "pt",
        speed=speed,
        stability=stability,
        similarity_boost=similarity,
        style=style,
        speaker_boost=speaker_boost,
    )


# provider_id -> (funcao que monta a classe, rotulo pra evento/log)
_BUILDERS = {
    "edge": _build_edge,
    "fishaudio": _build_fishaudio,
    "elevenlabs": _build_elevenlabs,
}

_LABELS = {
    "edge": "Edge TTS",
    "fishaudio": "Fish Audio TTS",
    "elevenlabs": "ElevenLabs TTS",
}

SUPPORTED_TTS_PROVIDERS = frozenset(_BUILDERS)


def provider_label(provider_id: str) -> str:
    return _LABELS.get(provider_id, provider_id)


def build_tts_provider(
    provider_id: str,
    *,
    voice: str = "",
    model: str = "",
    language: str = "pt",
    speed: float = 1.0,
    pitch: float = 0.0,
    stability: float = 0.5,
    similarity: float = 0.75,
    style: float = 0.0,
    speaker_boost: bool = True,
    latency: str = "balanced",
) -> Any:
    """Constrói o provider certo a partir do nome. Cada builder só usa o que precisa."""
    builder = _BUILDERS.get(provider_id)
    if builder is None:
        raise TTSConfigurationError(f"Provider TTS não suportado: {provider_id}.")
    return builder(
        voice=voice,
        model=model,
        language=language,
        speed=speed,
        pitch=pitch,
        stability=stability,
        similarity=similarity,
        style=style,
        speaker_boost=speaker_boost,
        latency=latency,
    )


def _self_check() -> None:
    edge = build_tts_provider("edge", voice="pt-BR-FranciscaNeural", speed=1.2, pitch=3)
    assert isinstance(edge, EdgeTTSProvider)
    assert edge.voice == "pt-BR-FranciscaNeural"

    eleven = build_tts_provider("elevenlabs", voice="abc123", stability=0.8)
    assert isinstance(eleven, ElevenlabsTTSProvider)
    assert eleven.stability == 0.8
    assert eleven.model == DEFAULT_ELEVENLABS_MODEL  # default quando nao informado

    fish = build_tts_provider("fishaudio", model="s2.1-pro")
    assert isinstance(fish, FishAudioTTSProvider)
    assert fish.model == "s2.1-pro"

    try:
        build_tts_provider("cartesia")
    except TTSConfigurationError:
        pass
    else:
        raise AssertionError("provider inexistente deveria levantar TTSConfigurationError")

    assert SUPPORTED_TTS_PROVIDERS == {"edge", "fishaudio", "elevenlabs"}
    print("providers.tts.registry: ok")


if __name__ == "__main__":
    _self_check()
