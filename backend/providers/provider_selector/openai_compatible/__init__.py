"""Base compartilhada por providers que usam o protocolo da OpenAI.

O pacote pertence ao seletor de providers, não a um provider específico.
"""

from .provider import OpenAICompatibleProvider

__all__ = ["OpenAICompatibleProvider"]
