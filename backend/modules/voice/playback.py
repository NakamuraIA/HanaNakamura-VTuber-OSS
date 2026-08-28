"""Reprodução local de áudio sintetizado.

Esta é a fronteira usada pelo runtime. A implementação atual ainda reutiliza o
player consolidado do Edge enquanto a lógica de decodificação é estabilizada.
"""

from backend.providers.tts.edge import EdgeTTSPlayer

__all__ = ["EdgeTTSPlayer"]
