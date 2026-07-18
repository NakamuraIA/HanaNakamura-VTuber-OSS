from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from hana_agent_oss.discord_bot.backend_client import HanaBackendClient

logger = logging.getLogger(__name__)

# Teto de caracteres falados por resposta numa call (protege crédito de TTS e evita
# a Hana monologar 4 parágrafos no ouvido de alguém).
_MAX_SPEAK_CHARS = 800


class _GuildVoice:
    """Fila de falas por servidor: toca uma resposta de cada vez, em ordem."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task[None] | None = None


class VozCog(commands.Cog):
    """Voz da Hana no Discord — MODO SÓ FALAR.

    Ela entra numa call e fala as respostas (TTS), tocando o áudio que o backend
    gera. Não ouve/transcreve (isso seria o modo completo). Assim não mexe na voz
    local nem arrisca o loop de áudio que trava a máquina.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.backend = HanaBackendClient()
        self._guilds: dict[int, _GuildVoice] = {}

    def _state(self, guild_id: int) -> _GuildVoice:
        state = self._guilds.get(guild_id)
        if state is None:
            state = _GuildVoice()
            self._guilds[guild_id] = state
        return state

    # ---- comandos --------------------------------------------------------- #

    @app_commands.command(name="entrar", description="A Hana entra na sua call e passa a falar as respostas.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def entrar(self, interaction: discord.Interaction) -> None:
        channel = getattr(getattr(interaction.user, "voice", None), "channel", None)
        if channel is None:
            await interaction.response.send_message("Entra numa call primeiro que eu te sigo. 🎧", ephemeral=True)
            return
        try:
            voice_client = interaction.guild.voice_client if interaction.guild else None
            if voice_client and voice_client.is_connected():
                await voice_client.move_to(channel)
            else:
                await channel.connect()
        except Exception as exc:
            logger.exception("Falha ao entrar na call")
            await interaction.response.send_message(f"Não consegui entrar: `{exc}`", ephemeral=True)
            return
        await interaction.response.send_message(f"Entrei na **{channel.name}**. Agora eu falo aqui. 🔊", ephemeral=True)

    @app_commands.command(name="sair", description="A Hana sai da call.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def sair(self, interaction: discord.Interaction) -> None:
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client is None or not voice_client.is_connected():
            await interaction.response.send_message("Não tô em call nenhuma. 🤷", ephemeral=True)
            return
        await self._teardown(interaction.guild.id, voice_client)
        await interaction.response.send_message("Saí da call. 👋", ephemeral=True)

    @app_commands.command(
        name="falar",
        description="Gera um áudio TTS do texto (sem passar pela IA) e te manda o arquivo.",
    )
    @app_commands.describe(texto="O texto que a Hana vai falar no áudio.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def falar(self, interaction: discord.Interaction, texto: str) -> None:
        """TTS pura: o texto vai DIRETO pro TTS, sem cérebro nem memória.

        Serve pra gerar áudios sob demanda. Devolve o arquivo no canal onde foi
        chamado; a Hana não vê nem lembra do que foi digitado.
        """
        await interaction.response.defer(thinking=True)
        try:
            audio = await self.backend.synthesize_speech(texto)
        except Exception as exc:
            logger.exception("Falha no /falar")
            await interaction.followup.send(f"Não consegui gerar o áudio: `{exc}`")
            return
        if not audio:
            await interaction.followup.send("Veio áudio vazio. 🤔 Confere o TTS nas configurações.")
            return
        file = discord.File(io.BytesIO(audio), filename="hana-tts.mp3")
        await interaction.followup.send(content="Aqui o áudio. 🔊", file=file)

    async def _teardown(self, guild_id: int, voice_client: discord.VoiceClient) -> None:
        state = self._guilds.pop(guild_id, None)
        if state and state.worker and not state.worker.done():
            state.worker.cancel()
        try:
            if voice_client.is_playing():
                voice_client.stop()
            await voice_client.disconnect(force=True)
        except Exception:
            logger.debug("Erro ao desconectar da call", exc_info=True)

    # ---- fala (chamado pelo cog Hana após cada resposta) ------------------ #

    async def speak(self, guild: discord.Guild | None, text: str) -> None:
        """Enfileira uma resposta pra ser falada na call, se a Hana estiver conectada."""
        if guild is None:
            return
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            return
        clean = str(text or "").strip()
        if not clean:
            return
        if len(clean) > _MAX_SPEAK_CHARS:
            clean = clean[:_MAX_SPEAK_CHARS].rstrip() + "..."
        state = self._state(guild.id)
        await state.queue.put(clean)
        if state.worker is None or state.worker.done():
            state.worker = asyncio.create_task(self._run_worker(guild))

    async def _run_worker(self, guild: discord.Guild) -> None:
        """Drena a fila do servidor tocando uma fala de cada vez; sai quando esvazia."""
        state = self._state(guild.id)
        while True:
            try:
                text = state.queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await self._play_text(guild, text)
            except Exception:
                logger.exception("Falha ao falar na call")
            finally:
                state.queue.task_done()

    async def _play_text(self, guild: discord.Guild, text: str) -> None:
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            return
        audio = await self.backend.synthesize_speech(text)
        if not audio:
            return

        # Arquivo temporário: tocar de arquivo é mais estável no Windows que pipe.
        fd, path = tempfile.mkstemp(prefix="hana_voz_", suffix=".mp3")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(audio)

            if voice_client.is_playing():
                voice_client.stop()

            loop = asyncio.get_running_loop()
            done = asyncio.Event()

            def _after(error: Exception | None) -> None:
                if error:
                    logger.warning("Erro tocando voz no Discord: %s", error)
                loop.call_soon_threadsafe(done.set)

            source = discord.FFmpegPCMAudio(path)
            voice_client.play(source, after=_after)
            await done.wait()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VozCog(bot))
