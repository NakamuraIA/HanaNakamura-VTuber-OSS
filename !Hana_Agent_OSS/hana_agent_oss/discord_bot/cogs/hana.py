from __future__ import annotations

import base64
import io
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from hana_agent_oss.discord_bot.backend_client import HanaBackendClient
from hana_agent_oss.discord_bot.delivery import build_payloads, code_file_to_discord
from hana_agent_oss.discord_bot.owner import is_owner

logger = logging.getLogger(__name__)


_MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024  # 8 MB: evita baixar arquivos enormes


async def _attachment_to_image_payload(attachment: discord.Attachment) -> dict[str, Any] | None:
    """Baixa um anexo de imagem do Discord e devolve no formato do backend (base64)."""
    content_type = str(getattr(attachment, "content_type", "") or "")
    if not content_type.startswith("image/"):
        return None
    data = await attachment.read()
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "type": content_type,
        "name": attachment.filename or "imagem.png",
        "data": f"data:{content_type};base64,{b64}",
    }


async def _attachment_to_payload(attachment: discord.Attachment) -> dict[str, Any] | None:
    """Baixa QUALQUER anexo (imagem, PDF, texto) no formato do backend (base64).

    Imagem vira visão; PDF/texto o backend extrai como contexto. Arquivos grandes
    demais são pulados pra não estourar memória/tempo.
    """
    if int(getattr(attachment, "size", 0) or 0) > _MAX_ATTACHMENT_BYTES:
        return None
    content_type = str(getattr(attachment, "content_type", "") or "").split(";")[0].strip()
    if not content_type:
        content_type = "application/octet-stream"
    data = await attachment.read()
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "type": content_type,
        "name": attachment.filename or "anexo",
        "data": f"data:{content_type};base64,{b64}",
    }


class SpeakResponseView(discord.ui.View):
    """Botão '🔊 Gerar áudio' embaixo da resposta da Hana.

    Gera o TTS DAQUELA resposta sob demanda e devolve o arquivo. Só o dono pode
    clicar. O texto fica guardado na própria view (não passa de novo pela IA).
    """

    def __init__(self, backend: HanaBackendClient, text: str, *, timeout: float = 900.0) -> None:
        super().__init__(timeout=timeout)
        self.backend = backend
        self.text = text

    @discord.ui.button(label="Gerar áudio", emoji="🔊", style=discord.ButtonStyle.secondary)
    async def gerar_audio(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("🔒 Só o dono pode gerar o áudio.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            audio = await self.backend.synthesize_speech(self.text)
        except Exception as exc:
            logger.exception("Falha ao gerar áudio da resposta")
            await interaction.followup.send(f"Não consegui gerar o áudio: `{exc}`", ephemeral=True)
            return
        if not audio:
            await interaction.followup.send("Veio áudio vazio. 🤔", ephemeral=True)
            return
        file = discord.File(io.BytesIO(audio), filename="hana-tts.mp3")
        await interaction.followup.send(content="Aqui o áudio da minha resposta. 🔊", file=file)


class HanaCog(commands.Cog):
    """Slash /hana + chatbot natural (DM/menção) ligando o Discord ao cérebro local."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.backend = HanaBackendClient()

    # ---- backend ---------------------------------------------------------- #

    async def _ask_backend(
        self,
        *,
        text: str,
        author: discord.User | discord.Member,
        channel: Any,
        guild: discord.Guild | None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Manda um turno de texto do Discord para a Hana e devolve a resposta."""
        payload: dict[str, Any] = {
            "text": text,
            "userId": author.id,
            "displayName": getattr(author, "display_name", author.name),
            "guildId": guild.id if guild else "",
            "textChannelId": getattr(channel, "id", ""),
        }
        if attachments:
            payload["attachments"] = attachments
        return await self.backend.send_message(payload)

    async def _media_files(self, result: dict[str, Any]) -> list[discord.File]:
        """Baixa as imagens geradas/editadas pelo backend como discord.File."""
        files: list[discord.File] = []
        for item in result.get("media") or []:
            url = str(item.get("url") or "")
            if not url:
                continue
            try:
                data = await self.backend.fetch_media_bytes(url)
            except Exception:
                logger.warning("Falha ao baixar mídia do backend: %s", url)
                continue
            files.append(discord.File(io.BytesIO(data), filename=str(item.get("name") or "imagem.png")))
        return files

    # ---- entrega de texto ------------------------------------------------- #

    async def _deliver_followup(
        self, interaction: discord.Interaction, text: str, *, view: discord.ui.View | None = None
    ) -> None:
        chunks, code_file = build_payloads(text)
        file = code_file_to_discord(code_file) if code_file else None
        last = len(chunks) - 1
        for index, chunk in enumerate(chunks):
            kwargs: dict[str, Any] = {"content": chunk or "​"}
            if index == last and file is not None:
                kwargs["file"] = file
            if index == last and view is not None:
                kwargs["view"] = view
            await interaction.followup.send(**kwargs)

    async def _deliver_channel(
        self, message: discord.Message, text: str, *, view: discord.ui.View | None = None
    ) -> None:
        chunks, code_file = build_payloads(text)
        file = code_file_to_discord(code_file) if code_file else None
        last = len(chunks) - 1
        first = True
        for index, chunk in enumerate(chunks):
            kwargs: dict[str, Any] = {"content": chunk or "​"}
            if index == last and file is not None:
                kwargs["file"] = file
            if index == last and view is not None:
                kwargs["view"] = view
            if first:
                await message.reply(**kwargs)
                first = False
            else:
                await message.channel.send(**kwargs)

    async def _maybe_speak(self, guild: Any, text: str) -> None:
        """Fala a resposta na call quando a Hana está conectada (cog de voz)."""
        voz = self.bot.get_cog("Voz")
        if voz is None:
            return
        try:
            await voz.speak(guild, text)
        except Exception:
            logger.debug("Falha ao acionar a voz no Discord", exc_info=True)

    # ---- slash /hana ------------------------------------------------------ #

    @app_commands.command(name="hana", description="Fale com a Hana (IA)")
    @app_commands.describe(
        conteudo="Mensagem para a Hana",
        arquivo="Imagem, PDF ou texto para contexto",
        url="URL pública para contexto",
        criar_imagem="Gera uma imagem",
        editar_imagem="Edita a imagem anexada",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def hana(
        self,
        interaction: discord.Interaction,
        conteudo: str,
        arquivo: discord.Attachment | None = None,
        url: str | None = None,
        criar_imagem: bool = False,
        editar_imagem: bool = False,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            # 1) Gerar imagem nova
            if criar_imagem:
                result = await self.backend.generate_image(conteudo)
                if not result.get("ok"):
                    await interaction.followup.send(f"Não consegui gerar a imagem: `{result.get('error') or 'erro'}`")
                    return
                files = await self._media_files(result)
                await interaction.followup.send(content=(result.get("text") or "Imagem gerada.")[:1900], files=files or None)
                return

            # 2) Editar imagem anexada
            if editar_imagem:
                if arquivo is None:
                    await interaction.followup.send("Pra editar, anexe a imagem em `arquivo`. 🙏")
                    return
                img_payload = await _attachment_to_image_payload(arquivo)
                if img_payload is None:
                    await interaction.followup.send("O anexo precisa ser uma imagem pra eu editar.")
                    return
                result = await self.backend.edit_image(conteudo, [img_payload])
                if not result.get("ok"):
                    await interaction.followup.send(f"Não consegui editar a imagem: `{result.get('error') or 'erro'}`")
                    return
                files = await self._media_files(result)
                await interaction.followup.send(content=(result.get("text") or "Imagem editada.")[:1900], files=files or None)
                return

            # 3) Conversa de texto (com arquivo/url como contexto)
            text = conteudo
            if url:
                text = f"{conteudo}\n\n[Contexto — URL fornecida: {url}]"
            attachments: list[dict[str, Any]] = []
            if arquivo is not None:
                att = await _attachment_to_payload(arquivo)
                if att is not None:
                    attachments.append(att)
                else:
                    text = f"{text}\n\n[Anexo grande demais ignorado: {arquivo.filename}]"
            result = await self._ask_backend(
                text=text,
                author=interaction.user,
                channel=interaction.channel,
                guild=interaction.guild,
                attachments=attachments or None,
            )
            response_text = str(result.get("text") or "(sem resposta)")
            speak_view = SpeakResponseView(self.backend, response_text)
            await self._deliver_followup(interaction, response_text, view=speak_view)
            await self._maybe_speak(interaction.guild, response_text)
        except Exception as exc:
            logger.exception("Erro no slash /hana")
            await interaction.followup.send(f"Erro ao falar com a Hana: `{exc}`")

    # ---- chatbot natural (DM/menção) ------------------------------------- #

    async def handle_natural_message(self, message: discord.Message, content: str) -> None:
        """Responde uma mensagem natural (já validada como da dona em DM/menção)."""
        attachments: list[dict[str, Any]] = []
        for att in message.attachments:
            payload = await _attachment_to_payload(att)
            if payload is not None:
                attachments.append(payload)
        if not content.strip() and not attachments:
            return
        try:
            async with message.channel.typing():
                result = await self._ask_backend(
                    text=content or "(imagem anexada)",
                    author=message.author,
                    channel=message.channel,
                    guild=message.guild,
                    attachments=attachments or None,
                )
            response_text = str(result.get("text") or "(sem resposta)")
            speak_view = SpeakResponseView(self.backend, response_text)
            await self._deliver_channel(message, response_text, view=speak_view)
            await self._maybe_speak(message.guild, response_text)
        except Exception as exc:
            logger.exception("Erro ao responder mensagem natural do Discord")
            try:
                await message.reply(f"Erro ao falar com a Hana: `{exc}`")
            except Exception:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HanaCog(bot))
