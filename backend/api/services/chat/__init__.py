"""Serviço de chat público.

Consumidores importam daqui; a organização interna pode mudar sem espalhar
novos caminhos pelo backend.
"""

from backend.api.services.chat.coordinator import (
    STREAMING_PROVIDERS,
    _terminal_channels,
    handle_chat_payload,
    run_text_turn,
)

__all__ = ["STREAMING_PROVIDERS", "handle_chat_payload", "run_text_turn"]
