from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class HanaBot(commands.Bot):
    """Discord bot shell that loads Hana command cogs."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            description="Hana AI - sua assistente inteligente no Discord",
        )

    async def setup_hook(self) -> None:
        """Load all Discord command cogs at startup."""
        for cog in ("geral", "hana", "voz"):
            try:
                await self.load_extension(f"hana_agent_oss.discord_bot.cogs.{cog}")
                logger.info("Cog '%s' carregado com sucesso.", cog)
            except Exception:
                logger.exception("Falha ao carregar cog '%s'.", cog)

    async def on_ready(self) -> None:
        """Log the connected Discord bot identity."""
        logger.info("Bot logado como %s (ID: %s)", self.user, getattr(self.user, "id", "?"))
        print(f"[ON] Hana Discord bot online como {self.user}", flush=True)

    async def on_command_error(self, context: commands.Context, exception: Exception) -> None:
        """Send command errors back to Discord instead of failing silently."""
        if isinstance(exception, commands.CommandNotFound):
            return
        logger.warning("Erro no comando '%s': %s", context.message.content, exception)
        await context.send(f"Erro no comando: {exception}")
