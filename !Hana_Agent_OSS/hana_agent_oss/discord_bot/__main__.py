#!/usr/bin/env python3
"""Entry point para rodar o bot do Discord da Hana.

Uso:
    python -m hana_agent_oss.discord_bot
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# Carrega variaveis do .env (procura na raiz do projeto)
dotenv_path = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", ".env"
)
load_dotenv(dotenv_path)

from hana_agent_oss.discord_bot import HanaBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print(
            "❌ DISCORD_TOKEN não encontrado no .env. "
            "Certifique-se de que o token está configurado."
        )
        sys.exit(1)

    bot = HanaBot()
    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
