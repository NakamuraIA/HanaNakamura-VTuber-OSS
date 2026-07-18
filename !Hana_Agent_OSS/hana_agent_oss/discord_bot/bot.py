from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

from hana_agent_oss.discord_bot.backend_client import HanaBackendClient
from hana_agent_oss.discord_bot.owner import is_owner

logger = logging.getLogger(__name__)


class OwnerOnlyTree(app_commands.CommandTree):
    """Command tree que bloqueia QUALQUER slash command de não-donos.

    A Hana é privada: só a Operador pode usar. Outros recebem uma resposta
    efêmera explicando, e o comando nem chega a rodar.
    """

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_owner(interaction.user.id):
            return True
        try:
            await interaction.response.send_message(
                "🔒 Esse bot é privado da Operador. Você não tem acesso.",
                ephemeral=True,
            )
        except Exception:
            pass
        return False


class HanaBot(commands.Bot):
    """Bot do Discord da Hana: chatbot privado por slash, DM natural e menção."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # ler o texto das mensagens (DM/menção)
        intents.members = True

        super().__init__(
            command_prefix="!",  # legado; o uso real é slash + DM/menção
            intents=intents,
            help_command=None,
            tree_cls=OwnerOnlyTree,
            description="Hana AI - chatbot privado da Operador",
        )
        self.backend = HanaBackendClient()

    async def setup_hook(self) -> None:
        """Carrega cogs e sincroniza os slash commands globalmente (user-install)."""
        for cog in ("geral", "hana", "voz", "config"):
            try:
                await self.load_extension(f"hana_agent_oss.discord_bot.cogs.{cog}")
                logger.info("Cog '%s' carregado.", cog)
            except Exception:
                logger.exception("Falha ao carregar cog '%s'.", cog)
        if not self._outbox_poller.is_running():
            self._outbox_poller.start()
        # Sync dos slash. Global pode levar ~1h pra propagar. Se HANA_DEV_GUILD_ID
        # estiver setado, copia os comandos pra esse servidor e sincroniza lá também,
        # onde aparecem NA HORA — ideal pra testar comando novo sem esperar.
        try:
            dev_guild_id = str(os.environ.get("HANA_DEV_GUILD_ID") or "").strip()
            if dev_guild_id.isdigit():
                guild = discord.Object(id=int(dev_guild_id))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info("Slash sincronizados NA HORA no servidor de dev %s: %s", dev_guild_id, [c.name for c in synced])
            else:
                synced = await self.tree.sync()
                logger.info("Slash commands sincronizados (global, pode levar ~1h): %s", [c.name for c in synced])
        except Exception:
            logger.exception("Falha ao sincronizar slash commands.")

    async def on_ready(self) -> None:
        logger.info("Bot logado como %s (ID: %s)", self.user, getattr(self.user, "id", "?"))
        print(f"[ON] Hana Discord bot online como {self.user}", flush=True)

    @tasks.loop(seconds=20.0)
    async def _outbox_poller(self) -> None:
        """Deliver DMs Hana queued in the backend outbox, mentioning Operador."""
        try:
            data = await self.backend.get_discord_outbox()
        except Exception:
            return  # backend offline / transient: try again next tick
        pending = data.get("pending") or []
        if not pending:
            return
        owner_id = str(data.get("ownerId") or "").strip()
        if not owner_id:
            return
        try:
            owner = self.get_user(int(owner_id)) or await self.fetch_user(int(owner_id))
        except Exception:
            return
        delivered: list[str] = []
        for entry in pending:
            message = str(entry.get("message") or "").strip()
            if not message:
                delivered.append(str(entry.get("id")))
                continue
            try:
                await owner.send(f"<@{owner_id}> {message}")
                delivered.append(str(entry.get("id")))
            except Exception:
                logger.exception("Falha ao entregar DM da outbox %s", entry.get("id"))
        if delivered:
            try:
                await self.backend.mark_discord_delivered(delivered)
            except Exception:
                logger.exception("Falha ao marcar outbox como entregue.")

    @_outbox_poller.before_loop
    async def _before_outbox_poller(self) -> None:
        await self.wait_until_ready()

    async def on_message(self, message: discord.Message) -> None:
        """Chatbot natural: responde em DM (sem prefixo) e quando mencionada.

        Só a dona é atendida; mensagens de outros são ignoradas em silêncio
        (a trava efêmera fica para os slash commands). Imagens/anexos e o
        roteamento real ficam no cog Hana, reaproveitado aqui.
        """
        if message.author.bot or message.author.id == getattr(self.user, "id", None):
            return
        is_dm = message.guild is None
        mentioned = self.user in message.mentions if self.user else False
        if not (is_dm or mentioned):
            return
        if not is_owner(message.author.id):
            return  # bot privado: ignora estranhos sem responder

        cog = self.get_cog("HanaCog")
        if cog is None:
            return
        # remove a menção do texto para não poluir o prompt
        content = message.content or ""
        if self.user:
            content = content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()
        await cog.handle_natural_message(message, content)
