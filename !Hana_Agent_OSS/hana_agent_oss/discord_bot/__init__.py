"""Pacote do bot do Discord da Hana.

``HanaBot`` é exposto de forma preguiçosa (PEP 562) para que importar submódulos
leves como ``owner`` NÃO arraste a dependência opcional ``discord``. Assim o backend
pode reusar ``owner.py`` (fonte única do dono) sem precisar do pacote do Discord.
"""

from __future__ import annotations

from typing import Any

__all__ = ["HanaBot"]


def __getattr__(name: str) -> Any:
    if name == "HanaBot":
        from hana_agent_oss.discord_bot.bot import HanaBot

        return HanaBot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
