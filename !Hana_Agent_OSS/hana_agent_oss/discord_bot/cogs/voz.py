from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from hana_agent_oss.discord_bot.backend_client import HanaBackendClient

logger = logging.getLogger(__name__)

SAMPLE_RATE = 48_000
SAMPLE_WIDTH = 2
CHANNELS = 2
SEGMENT_SILENCE_SECONDS = 0.9
MIN_SEGMENT_SECONDS = 0.45


def _ffmpeg_path() -> str:
    """Return the FFmpeg executable used by Discord playback."""
    for env_name in ("FFMPEG_PATH", "HANA_FFMPEG_PATH"):
        value = os.environ.get(env_name)
        if value:
            return value
    local = Path("C:/Ffmpeg/ffmpeg.exe")
    if local.exists():
        return str(local)
    return shutil.which("ffmpeg") or "ffmpeg"


def _wav_from_pcm(pcm: bytes) -> bytes:
    """Wrap raw Discord PCM in a WAV container accepted by Groq Whisper."""
    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm)
    output.seek(0)
    return output.read()


def make_discord_audio_sink(cog: Voz, ctx: commands.Context, voice_recv_module: Any) -> Any:
    """Build a discord-ext-voice-recv AudioSink after the optional package is imported."""

    class DiscordAudioSink(voice_recv_module.AudioSink):
        """Voice receive sink that buffers PCM per Discord user and flushes on silence."""

        def __init__(self) -> None:
            super().__init__()
            self.cog = cog
            self.ctx = ctx
            self._lock = threading.RLock()
            self._buffers: dict[int, dict[str, Any]] = {}
            self._closed = False
            self._flush_task = cog.bot.loop.create_task(self._flush_loop())

        def wants_opus(self) -> bool:
            """Ask discord-ext-voice-recv to decode packets to PCM before write()."""
            return False

        def write(self, user: discord.User | discord.Member | None, data: Any) -> None:
            """Receive one PCM chunk from discord-ext-voice-recv."""
            if self._closed or not self.cog.listen_enabled:
                return
            user = user or getattr(data, "user", None)
            if user is None or user.bot:
                return
            pcm = getattr(data, "pcm", None) or getattr(data, "data", None)
            if not pcm:
                return
            with self._lock:
                item = self._buffers.setdefault(
                    int(user.id),
                    {"user": user, "chunks": [], "last_packet": time.monotonic()},
                )
                item["user"] = user
                item["chunks"].append(bytes(pcm))
                item["last_packet"] = time.monotonic()

        def cleanup(self) -> None:
            """Stop the background silence flush loop."""
            self._closed = True
            if self._flush_task and not self._flush_task.done():
                self._flush_task.cancel()

        async def _flush_loop(self) -> None:
            """Periodically flush users whose speech stream has gone quiet."""
            try:
                while not self._closed:
                    await asyncio.sleep(0.2)
                    due: list[tuple[discord.User | discord.Member, bytes]] = []
                    now = time.monotonic()
                    with self._lock:
                        for user_id, item in list(self._buffers.items()):
                            if not item["chunks"]:
                                continue
                            if now - float(item["last_packet"]) < SEGMENT_SILENCE_SECONDS:
                                continue
                            pcm = b"".join(item["chunks"])
                            self._buffers.pop(user_id, None)
                            if len(pcm) >= int(SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * MIN_SEGMENT_SECONDS):
                                due.append((item["user"], _wav_from_pcm(pcm)))
                    for user, wav_audio in due:
                        await self.cog.process_voice_segment(self.ctx, user, wav_audio)
            except asyncio.CancelledError:
                return

    return DiscordAudioSink()


class Voz(commands.Cog):
    """Discord voice commands and voice-call transport for Hana."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.backend = HanaBackendClient()
        self.guild_locks: dict[int, asyncio.Lock] = {}
        self.sinks: dict[int, Any] = {}
        self.listen_enabled = False

    def _guild_lock(self, guild_id: int) -> asyncio.Lock:
        """Return a queue lock so one guild cannot overlap Hana responses."""
        lock = self.guild_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self.guild_locks[guild_id] = lock
        return lock

    async def _load_voice_recv(self) -> Any | None:
        """Import discord-ext-voice-recv only when the user joins a call."""
        try:
            import discord.ext.voice_recv as voice_recv
        except ImportError as exc:
            logger.warning("discord-ext-voice-recv is not installed: %s", exc)
            return None
        return voice_recv

    async def _refresh_listen_state(self) -> bool:
        """Refresh the local listen flag from backend connection settings."""
        config = await self.backend.get_connections()
        self.listen_enabled = bool(config.get("discord") and config.get("discordListen"))
        return self.listen_enabled

    @commands.group(name="voz", invoke_without_command=True)
    async def voz(self, ctx: commands.Context, state: str | None = None) -> None:
        """Controla a voz da Hana no Discord."""
        if state is None or state.lower() == "status":
            await self._send_status(ctx)
            return
        value = state.lower() in {"on", "ligar", "liga", "true", "1", "sim"}
        if state.lower() not in {"on", "off", "ligar", "desligar", "liga", "desliga", "true", "false", "1", "0", "sim", "nao", "não"}:
            await ctx.send("Use `!voz on`, `!voz off`, `!voz falar on/off`, `!voz ouvir on/off` ou `!voz status`.")
            return
        saved = await self.backend.update_connections({"discord": value, "discordSpeak": value, "discordListen": value})
        self.listen_enabled = bool(saved.get("discord") and saved.get("discordListen"))
        await ctx.send(f"Voz Discord {'ligada' if value else 'desligada'}: falar={saved.get('discordSpeak')} ouvir={saved.get('discordListen')}.")

    @voz.command(name="falar")
    async def falar(self, ctx: commands.Context, state: str) -> None:
        """Liga ou desliga a TTS da Hana dentro da call."""
        enabled = state.lower() in {"on", "ligar", "liga", "true", "1", "sim"}
        saved = await self.backend.update_connections({"discord": True, "discordSpeak": enabled})
        await ctx.send(f"Fala no Discord {'ativada' if saved.get('discordSpeak') else 'desativada'}.")

    @voz.command(name="ouvir")
    async def ouvir(self, ctx: commands.Context, state: str) -> None:
        """Liga ou desliga a escuta/STT da call."""
        enabled = state.lower() in {"on", "ligar", "liga", "true", "1", "sim"}
        saved = await self.backend.update_connections({"discord": True, "discordListen": enabled})
        self.listen_enabled = bool(saved.get("discord") and saved.get("discordListen"))
        await ctx.send(f"Escuta do Discord {'ativada' if self.listen_enabled else 'desativada'}.")

    @voz.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        """Mostra o estado persistido da voz Discord."""
        await self._send_status(ctx)

    async def _send_status(self, ctx: commands.Context) -> None:
        """Send the persisted Discord voice status to the current text channel."""
        saved = await self.backend.get_connections()
        await ctx.send(
            "Discord voice: "
            f"master={bool(saved.get('discord'))} "
            f"falar={bool(saved.get('discordSpeak'))} "
            f"ouvir={bool(saved.get('discordListen'))}."
        )

    @commands.command(name="entrar", aliases=["join"])
    async def entrar(self, ctx: commands.Context) -> None:
        """Entra no canal de voz atual e prepara receive por usuario."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Voce precisa estar em um canal de voz primeiro.")
            return
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.disconnect(force=True)
        voice_recv = await self._load_voice_recv()
        if voice_recv is None:
            await channel.connect()
            await self._refresh_listen_state()
            await ctx.send(
                f"Entrei em **{channel.name}** em modo fala. "
                "Para ouvir usuarios da call, instale `discord-ext-voice-recv==0.5.2a179` e reinicie o bot."
            )
            return

        voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        if not hasattr(voice_client, "listen"):
            await voice_client.disconnect(force=True)
            await ctx.send(
                "Entrei com VoiceClient normal, sem suporte a `listen()`. "
                "Atualize para `discord.py[voice]>=2.4` e `discord-ext-voice-recv==0.5.2a179`, depois reinicie o bot."
            )
            return
        sink = make_discord_audio_sink(self, ctx, voice_recv)
        self.sinks[int(ctx.guild.id)] = sink
        voice_client.listen(sink)
        await self._refresh_listen_state()
        await ctx.send(f"Entrei em **{channel.name}**. Use `!voz on` para falar e ouvir pela call.")

    @commands.command(name="sair", aliases=["leave", "stop"])
    async def sair(self, ctx: commands.Context) -> None:
        """Sai do canal de voz e limpa a sink de receive."""
        guild_id = int(ctx.guild.id) if ctx.guild else 0
        sink = self.sinks.pop(guild_id, None)
        if sink:
            sink.cleanup()
        if not ctx.voice_client:
            await ctx.send("Nao estou em nenhum canal de voz.")
            return
        channel_name = ctx.voice_client.channel.name
        await ctx.voice_client.disconnect(force=True)
        await ctx.send(f"Sai de **{channel_name}**.")

    async def process_voice_segment(self, ctx: commands.Context, user: discord.User | discord.Member, wav_audio: bytes) -> None:
        """Send one user-specific Discord audio segment through backend STT and Hana."""
        if not ctx.guild:
            return
        async with self._guild_lock(int(ctx.guild.id)):
            try:
                result = await self.backend.send_audio(
                    wav_audio,
                    fields={
                        "userId": user.id,
                        "displayName": getattr(user, "display_name", user.name),
                        "guildId": ctx.guild.id,
                        "textChannelId": ctx.channel.id,
                        "voiceChannelId": ctx.voice_client.channel.id if ctx.voice_client else "",
                    },
                )
            except Exception as exc:
                logger.exception("[Discord] Failed to process voice segment.")
                await ctx.channel.send(f"Falha ao processar audio do Discord: `{exc}`")
                return
            if not result.get("transcribed"):
                return
            await ctx.channel.send(f"**{getattr(user, 'display_name', user.name)}:** {result.get('text')}")
            assistant_text = str(result.get("assistantText") or result.get("text") or "").strip()
            if assistant_text:
                await ctx.channel.send(assistant_text[:1900])
            audio = result.get("audio")
            if isinstance(audio, dict) and audio.get("audioBase64") and ctx.voice_client:
                await self._play_audio(ctx.voice_client, audio)

    async def _play_audio(self, voice_client: discord.VoiceClient, audio: dict[str, Any]) -> None:
        """Decode backend TTS bytes and play them in the Discord voice channel."""
        suffix = ".mp3"
        mime = str(audio.get("mimeType") or "")
        if "wav" in mime:
            suffix = ".wav"
        fd, raw_path = tempfile.mkstemp(prefix="hana-discord-tts-", suffix=suffix)
        os.close(fd)
        path = Path(raw_path)
        path.write_bytes(base64.b64decode(str(audio["audioBase64"])))
        done = asyncio.Event()

        def _after(error: Exception | None) -> None:
            if error:
                logger.warning("[Discord] Playback failed: %s", error)
            self.bot.loop.call_soon_threadsafe(done.set)

        try:
            while voice_client.is_playing():
                await asyncio.sleep(0.05)
            source = discord.FFmpegPCMAudio(str(path), executable=_ffmpeg_path())
            voice_client.play(source, after=_after)
            await done.wait()
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Voz(bot))
