"""Slash /provider e /status — trocar provider/modelo da Hana pelo proprio Discord.

Menus em cascata (categoria -> provider -> modelo), tudo ephemeral e so pra dona.
As mudancas caem no backend (merge/PATCH) e valem no proximo turno, sem restart.

Categorias: Chat (o que o Discord usa), Agente (loop de ferramentas), Imagem.
Visao fica de fora de proposito — vem numa proxima leva com provider proprio.
"""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from hana_agent_oss.discord_bot.backend_client import HanaBackendClient
from hana_agent_oss.discord_bot.owner import is_owner

logger = logging.getLogger(__name__)

MANUAL_VALUE = "__manual__"
SAME_AS_CHAT_VALUE = "__same__"
MAX_MODEL_OPTIONS = 23  # +1 pra opcao "digitar manual" = 24, abaixo do teto de 25 do Discord

PROVIDER_LABELS = {
    "gemini_api": "Gemini",
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "maritaca": "Maritaca (Sabia)",
}

CATEGORY_META = {
    "chat": {"label": "Chat (texto)", "emoji": "💬"},
    "agente": {"label": "Agente (ferramentas)", "emoji": "🤖"},
    "imagem": {"label": "Imagem (geracao)", "emoji": "🎨"},
}


# --- Helpers puros (testaveis sem Discord) -------------------------------- #

def provider_ids_for(category: str, catalog: dict[str, Any]) -> list[str]:
    """Providers validos pra categoria, lidos do catalogo do backend."""
    if category == "imagem":
        return [str(p) for p in (catalog.get("imageProviders") or []) if p]
    return [str(p) for p in (catalog.get("llmProviders") or []) if p]


def model_ids_for(category: str, provider: str, catalog: dict[str, Any]) -> list[dict[str, str]]:
    """Modelos do provider escolhido (id + label), a partir do catalogo.

    Chat/Agente -> modelos de texto do provider. Imagem -> imageModels do provider.
    Retorna no maximo MAX_MODEL_OPTIONS itens (o resto entra via 'digitar manual').
    """
    if category == "imagem":
        source = catalog.get("imageModels") or []
    else:
        source = catalog.get("models") or []
    out: list[dict[str, str]] = []
    for item in source:
        if not isinstance(item, dict) or item.get("provider") != provider:
            continue
        if category != "imagem" and "text" not in (item.get("outputModalities") or ["text"]):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        label = str(item.get("label") or mid).strip()
        out.append({"id": mid, "label": label})
        if len(out) >= MAX_MODEL_OPTIONS:
            break
    return out


def build_config_calls(category: str, provider: str, model: str) -> list[tuple[str, dict[str, Any]]]:
    """Mapeia (categoria, provider, modelo) -> chamadas (metodo do backend, payload).

    Puro de proposito, pra dar pra testar sem subir Discord nem backend.
    - Chat escreve nos DOIS configs (chat_config manda no Discord; llm_config no painel).
    - Agente com provider vazio ("__same__") = usar o mesmo do chat.
    - Imagem so manda openrouterImageModel quando o provider e openrouter.
    """
    p = str(provider or "").strip()
    m = str(model or "").strip()
    if category == "chat":
        return [
            ("update_chat_config", {"provider": p, "model": m}),
            ("update_llm_config", {"llmProvider": p, "llmModel": m}),
        ]
    if category == "agente":
        if p == SAME_AS_CHAT_VALUE:
            return [("update_llm_config", {"agentProvider": "", "agentModel": ""})]
        return [("update_llm_config", {"agentProvider": p, "agentModel": m})]
    if category == "imagem":
        payload: dict[str, Any] = {"imageProvider": p}
        if p == "openrouter":
            payload["openrouterImageModel"] = m
        return [("update_image_config", payload)]
    raise ValueError(f"categoria desconhecida: {category!r}")


async def apply_config(backend: HanaBackendClient, category: str, provider: str, model: str) -> None:
    """Executa as chamadas de config no backend pra aquela escolha."""
    for method_name, payload in build_config_calls(category, provider, model):
        await getattr(backend, method_name)(payload)


def _provider_label(provider_id: str) -> str:
    return PROVIDER_LABELS.get(provider_id, provider_id.upper())


# --- Componentes de UI ---------------------------------------------------- #

class CategorySelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label=meta["label"], value=key, emoji=meta["emoji"])
            for key, meta in CATEGORY_META.items()
        ]
        super().__init__(placeholder="Trocar o provider de quê?", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ProviderConfigView = self.view  # type: ignore[assignment]
        if not await view.guard(interaction):
            return
        view.category = self.values[0]
        view.show_providers()
        meta = CATEGORY_META[view.category]
        await interaction.response.edit_message(
            content=f"{meta['emoji']} **{meta['label']}** — escolhe o provider:", view=view
        )


class ProviderSelect(discord.ui.Select):
    def __init__(self, category: str, provider_ids: list[str]) -> None:
        options = [
            discord.SelectOption(label=_provider_label(pid), value=pid)
            for pid in provider_ids[:24]
        ]
        if category == "agente":
            options.insert(0, discord.SelectOption(label="Mesmo do chat", value=SAME_AS_CHAT_VALUE, emoji="↔️"))
        super().__init__(placeholder="Escolhe o provider...", options=options)
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ProviderConfigView = self.view  # type: ignore[assignment]
        if not await view.guard(interaction):
            return
        view.provider = self.values[0]
        # Agente "mesmo do chat" e Imagem/Gemini nao precisam escolher modelo.
        if view.provider == SAME_AS_CHAT_VALUE or (view.category == "imagem" and view.provider != "openrouter"):
            await view.finish(interaction, model="")
            return
        view.show_models()
        await interaction.response.edit_message(
            content=f"Provider **{_provider_label(view.provider)}** — agora o modelo:", view=view
        )


class ModelSelect(discord.ui.Select):
    def __init__(self, models: list[dict[str, str]]) -> None:
        options: list[discord.SelectOption] = []
        for item in models[:MAX_MODEL_OPTIONS]:
            label = item["label"][:100]
            options.append(discord.SelectOption(label=label, value=item["id"][:100], description=item["id"][:100]))
        options.append(discord.SelectOption(label="Digitar modelo manualmente", value=MANUAL_VALUE, emoji="✏️"))
        super().__init__(placeholder="Escolhe o modelo...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ProviderConfigView = self.view  # type: ignore[assignment]
        if not await view.guard(interaction):
            return
        if self.values[0] == MANUAL_VALUE:
            await interaction.response.send_modal(ManualModelModal(view))
            return
        await view.finish(interaction, model=self.values[0])


class ManualModelModal(discord.ui.Modal, title="Digitar ID do modelo"):
    model_id: discord.ui.TextInput = discord.ui.TextInput(
        label="ID do modelo",
        placeholder="ex: openrouter/auto, google/gemma-4-31b-it",
        required=True,
        max_length=200,
    )

    def __init__(self, view: "ProviderConfigView") -> None:
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("🔒 Só a dona pode configurar.", ephemeral=True)
            return
        await self._view.finish(interaction, model=str(self.model_id.value).strip())


class ProviderConfigView(discord.ui.View):
    """View com estado: guarda categoria/provider e troca os Selects em cascata."""

    def __init__(self, backend: HanaBackendClient, catalog: dict[str, Any], *, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.backend = backend
        self.catalog = catalog
        self.category: str = ""
        self.provider: str = ""
        self.add_item(CategorySelect())

    async def guard(self, interaction: discord.Interaction) -> bool:
        """Dono-only tambem nos componentes (o gate do tree nao cobre interacao de componente)."""
        if is_owner(interaction.user.id):
            return True
        await interaction.response.send_message("🔒 Só a dona pode configurar.", ephemeral=True)
        return False

    def show_providers(self) -> None:
        self.clear_items()
        self.add_item(ProviderSelect(self.category, provider_ids_for(self.category, self.catalog)))

    def show_models(self) -> None:
        self.clear_items()
        self.add_item(ModelSelect(model_ids_for(self.category, self.provider, self.catalog)))

    async def finish(self, interaction: discord.Interaction, *, model: str) -> None:
        """Aplica a config e fecha o menu com a confirmacao."""
        try:
            await apply_config(self.backend, self.category, self.provider, model)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao aplicar config via Discord")
            msg = f"❌ Não consegui aplicar: `{exc}`"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.edit_message(content=msg, view=None)
            return
        meta = CATEGORY_META.get(self.category, {"label": self.category, "emoji": "⚙️"})
        if self.provider == SAME_AS_CHAT_VALUE:
            detail = "usando o **mesmo provider do chat**"
        else:
            detail = f"agora usa **{_provider_label(self.provider)}**" + (f" / `{model}`" if model else "")
        content = f"{meta['emoji']} **{meta['label']}** {detail} ✅"
        self.clear_items()
        self.stop()
        # Modal submit vem sem a mensagem original; manda confirmacao nova nesse caso.
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.edit_message(content=content, view=None)


class ConfigCog(commands.Cog):
    """Slash /provider (trocar provider/modelo) e /status (ver config atual)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.backend = HanaBackendClient()

    @app_commands.command(name="provider", description="Trocar o provider/modelo da Hana (chat, agente ou imagem)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def provider(self, interaction: discord.Interaction) -> None:
        try:
            catalog = await self.backend.get_catalog()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao buscar catalogo pro /provider")
            await interaction.response.send_message(f"❌ Não consegui ler o catálogo: `{exc}`", ephemeral=True)
            return
        view = ProviderConfigView(self.backend, catalog)
        await interaction.response.send_message("⚙️ O que você quer trocar?", view=view, ephemeral=True)

    @app_commands.command(name="status", description="Ver o provider e modelos ativos agora")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            chat = await self.backend.get_chat_config()
            llm = await self.backend.get_llm_config()
            image = await self.backend.get_image_config()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao ler config pro /status")
            await interaction.followup.send(f"❌ Não consegui ler a config: `{exc}`", ephemeral=True)
            return
        agent_provider = str(llm.get("agentProvider") or "").strip()
        agent_line = (
            f"{_provider_label(agent_provider)} / `{llm.get('agentModel') or 'padrão'}`"
            if agent_provider else "mesmo do chat"
        )
        lines = [
            "**⚙️ Config atual da Hana**",
            f"💬 **Chat:** {_provider_label(str(chat.get('provider') or ''))} / `{chat.get('model') or '?'}`",
            f"🤖 **Agente:** {agent_line}",
            f"🎨 **Imagem:** {_provider_label(str(image.get('imageProvider') or ''))}"
            + (f" / `{image.get('openrouterImageModel')}`" if image.get("openrouterImageModel") else ""),
            f"👁️ **Visão:** `{llm.get('visionModel') or '?'}` (informativo)",
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ConfigCog(bot))
