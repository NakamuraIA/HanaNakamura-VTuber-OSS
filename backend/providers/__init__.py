"""Integração com providers externos de LLM, TTS e STT.

Contrato da pasta:
- contracts.py            : ProviderRequest/ProviderResponse, o contrato único.
- provider_aliases.py     : normalização canônica dos IDs de providers de LLM
  nas entradas do runtime (ex.: "google_cloud" -> "gemini_api").
- provider_selector/      : um subpasta por provider + selector.py roteando;
  openai_compatible/ é o pacote compartilhado dos providers OpenAI-like,
  incluindo mensagens, anexos, loop e ferramentas por domínio.
- tts/                    : Edge, ElevenLabs, Fish Audio e registro TTS.
- stt/                    : Groq Whisper, OpenRouter e registro STT.

Providers não conhecem FastAPI nem guardam o estado canônico da conversa.
"""

from backend.providers.contracts import ProviderRequest, ProviderResponse
from backend.providers.provider_selector.selector import (
    ProviderDefinition,
    ProviderSelector,
)

__all__ = [
    "ProviderDefinition",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderSelector",
]
