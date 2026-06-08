from __future__ import annotations

import discord
from discord.ext import commands


class Geral(commands.Cog):
    """General utility commands for the Discord bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context) -> None:
        """Mostra a latencia do bot."""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"Pong. Latencia: **{latency}ms**")

    @commands.command(name="ajuda", aliases=["help"])
    async def ajuda(self, ctx: commands.Context) -> None:
        """Lista os comandos disponiveis."""
        embed = discord.Embed(
            title="Comandos da Hana",
            description="Comandos disponiveis no bot do Discord:",
            color=discord.Color.purple(),
        )

        for cog_name, cog in self.bot.cogs.items():
            commands_list = [
                f"`!{cmd.qualified_name}` - {cmd.short_doc or 'Sem descricao'}"
                for cmd in cog.get_commands()
                if not cmd.hidden
            ]
            if commands_list:
                embed.add_field(name=cog_name, value="\n".join(commands_list), inline=False)

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Geral(bot))
