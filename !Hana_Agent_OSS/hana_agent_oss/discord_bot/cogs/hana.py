from __future__ import annotations

import base64
import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from hana_agent_oss.discord_bot.backend_client import HanaBackendClient

logger = logging.getLogger(__name__)


def _ffmpeg_path() -> str:
    """Return the FFmpeg executable used for optional Discord TTS playback."""
    for env_name in ("FFMPEG_PATH", "HANA_FFMPEG_PATH"):
        value = os.environ.get(env_name)
        if value:
            return value
    local = Path("C:/Ffmpeg/ffmpeg.exe")
    if local.exists():
        return str(local)
    return shutil.which("ffmpeg") or "ffmpeg"


class HanaCog(commands.Cog):
    """Discord text command bridge for the local Hana backend."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.backend = HanaBackendClient()

    @commands.command(name="hana")
    async def hana(self, ctx: commands.Context, *, mensagem: str) -> None:
        """Envia uma mensagem para a Hana AI e recebe a resposta."""
        async with ctx.typing():
            try:
                resposta = await self._consultar_hana(mensagem, ctx.author, ctx)
                await ctx.reply(str(resposta.get("text") or "Sem resposta.")[:1900])
                audio = resposta.get("audio")
                if ctx.voice_client and isinstance(audio, dict) and audio.get("audioBase64"):
                    await self._play_audio(ctx.voice_client, audio)
            except Exception as exc:
                logger.exception("Erro ao consultar Hana pelo Discord")
                await ctx.reply(f"Erro ao contactar a Hana: `{exc}`")

    async def _consultar_hana(self, mensagem: str, autor: discord.User | discord.Member, ctx: commands.Context) -> dict[str, Any]:
        """Call the backend Discord message endpoint with author metadata."""
        return await self.backend.send_message(
            {
                "text": mensagem,
                "userId": autor.id,
                "displayName": getattr(autor, "display_name", autor.name),
                "guildId": ctx.guild.id if ctx.guild else "",
                "textChannelId": ctx.channel.id,
                "voiceChannelId": ctx.voice_client.channel.id if ctx.voice_client else "",
            }
        )

    async def _play_audio(self, voice_client: discord.VoiceClient, audio: dict[str, Any]) -> None:
        """Play backend-generated TTS in the current Discord voice channel."""
        suffix = ".wav" if "wav" in str(audio.get("mimeType") or "") else ".mp3"
        fd, raw_path = tempfile.mkstemp(prefix="hana-discord-text-tts-", suffix=suffix)
        os.close(fd)
        path = Path(raw_path)
        path.write_bytes(base64.b64decode(str(audio["audioBase64"])))
        done = asyncio.Event()

        def _after(error: Exception | None) -> None:
            if error:
                logger.warning("[Discord] Text command playback failed: %s", error)
            self.bot.loop.call_soon_threadsafe(done.set)

        try:
            source = discord.FFmpegPCMAudio(str(path), executable=_ffmpeg_path())
            if not voice_client.is_playing():
                voice_client.play(source, after=_after)
                await done.wait()
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HanaCog(bot))
