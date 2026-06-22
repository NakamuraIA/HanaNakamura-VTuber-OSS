from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class Geral(commands.Cog):
    """Comandos utilitários do bot da Hana (slash)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Latência do bot.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ping(self, interaction: discord.Interaction) -> None:
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong. Latência: **{latency}ms**", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Geral(bot))
