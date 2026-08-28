from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.api.routers.config import update_llm_config, update_ui_config
from backend.mcp.client import McpStdioClient
from backend.mcp.config import McpConfigStore
from backend.mcp.contracts import McpServerConfig


class _Memory:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = dict(values or {})

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set_setting(self, key: str, value: Any) -> Any:
        self.values[key] = value
        return value


def _request(memory: _Memory) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(memory=memory)))


def test_backend_preserva_agente_e_multimodal_em_update_parcial_da_llm() -> None:
    """Isola o backend: a troca indevida observada nasce no frontend."""

    memory = _Memory(
        {
            "llm_config": {
                "llmProvider": "groq",
                "llmModel": "modelo-principal-a",
                "llmModelByProvider": {"groq": "modelo-principal-a"},
                "agentProvider": "qwen",
                "agentModel": "modelo-agente-fixo",
                "agentModelByProvider": {"qwen": "modelo-agente-fixo"},
                "visionProvider": "openrouter",
                "visionModel": "modelo-visao-fixo",
                "visionModelByProvider": {"openrouter": "modelo-visao-fixo"},
            }
        }
    )

    result = asyncio.run(
        update_llm_config(
            _request(memory),
            {"llmProvider": "deepseek", "llmModel": "modelo-principal-b"},
        )
    )

    assert result["agentProvider"] == "qwen"
    assert result["agentModel"] == "modelo-agente-fixo"
    assert result["visionProvider"] == "openrouter"
    assert result["visionModel"] == "modelo-visao-fixo"
    assert result["llmModelByProvider"] == {"groq": "modelo-principal-a"}
    assert result["agentModelByProvider"] == {"qwen": "modelo-agente-fixo"}
    assert result["visionModelByProvider"] == {"openrouter": "modelo-visao-fixo"}


def test_personalizacao_compartilhada_inclui_acessibilidade() -> None:
    """Toda personalização durável chega ao mesmo registro do banco."""

    memory = _Memory({"ui_config": {}})

    asyncio.run(
        update_ui_config(
            _request(memory),
            {"accessibility": {"font": "verdana", "spacing": True}},
        )
    )

    assert memory.values["ui_config"]["accessibility"] == {
        "font": "verdana",
        "spacing": True,
    }


def test_frontend_mantem_personalizacao_pendente_sem_fingir_sucesso() -> None:
    api_source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "api"
        / "aparencia.ts"
    ).read_text(encoding="utf-8")
    page_source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "views"
        / "pages"
        / "TabPersonalizacao.tsx"
    ).read_text(encoding="utf-8")

    assert 'PENDING_KEY = "hana_ui_config_pending"' in api_source
    assert 'const UI_KEYS = ["theme", "identity", "accessibility"]' in api_source
    assert "if (hasPendingAppearance()) await flushPending()" in api_source
    assert "setShowToast(await saveTheme(theme))" in page_source
    assert '"personalization.syncPending"' in page_source


def test_provider_principal_nao_muda_multimodal_explicito() -> None:
    """Prova mínima do acoplamento sem instalar um framework frontend."""

    source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "views"
        / "pages"
        / "TabLLM.tsx"
    ).read_text(encoding="utf-8")
    handler = source.split("const selectLlmProvider", 1)[1].split(
        "const selectVisionProvider", 1
    )[0]

    assert "if (!prev.visionProvider)" in handler
    assert "next.visionModel" in handler
    assert "if (!prev.agentProvider && prev.agentModel)" in handler


def test_seletores_lembram_ultimo_modelo_de_cada_provider() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "views"
        / "pages"
        / "TabLLM.tsx"
    ).read_text(encoding="utf-8")

    assert "llmModelByProvider: rememberProviderModel" in source
    assert "visionModelByProvider: rememberProviderModel" in source
    assert "agentModelByProvider: rememberProviderModel" in source
    assert "onChange={selectLlmModel}" in source
    assert "onChange={selectVisionModel}" in source
    assert "onChange={selectAgentModel}" in source


def test_update_parcial_da_llm_nao_reenvia_cache_antigo_inteiro() -> None:
    """Uma aba antiga não pode sobrescrever agente/visão ao mudar só um campo."""

    source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "api"
        / "config.ts"
    ).read_text(encoding="utf-8")
    update = source.split("updateLlmConfig: async", 1)[1].split(
        "getChatConfig: async", 1
    )[0]

    assert "postPendingLlmConfig(pending)" in update
    assert "body: JSON.stringify(pending)" in source
    assert "changedLlmFields(config)" in update


def test_falha_de_sincronizacao_da_llm_fica_pendente_e_visivel() -> None:
    config_source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "api"
        / "config.ts"
    ).read_text(encoding="utf-8")
    chat_source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "views"
        / "pages"
        / "TabChat.tsx"
    ).read_text(encoding="utf-8")

    assert 'LLM_CONFIG_PENDING_KEY = "hana_llm_config_pending"' in config_source
    assert "writePendingLlmConfig(pending)" in config_source
    assert "será sincronizada quando a Hana voltar" in chat_source


def test_permissao_mcp_e_compartilhada_por_novas_instancias_do_backend(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mcp.json"
    first = McpConfigStore(config_path)
    first.save_payload(
        {
            "servers": [
                {
                    "id": "tavily",
                    "name": "Tavily",
                    "enabled": True,
                    "command": "cmd",
                    "args": [],
                    "allowed_tools": ["tavily_search"],
                }
            ]
        }
    )
    first.set_tool_allowed("tavily", "tavily_extract", True)

    reloaded = McpConfigStore(config_path).get_server("tavily")

    assert reloaded is not None
    assert reloaded.enabled is True
    assert set(reloaded.allowed_tools) == {"tavily_search", "tavily_extract"}


class _FakeMcpSession:
    async def initialize(self) -> None:
        return None

    async def call_tool(self, _tool: str, _arguments: dict[str, Any]) -> Any:
        return SimpleNamespace(content=[], structuredContent={}, isError=False)


class _CountingSession(AbstractAsyncContextManager[_FakeMcpSession]):
    def __init__(self, counter: list[int]) -> None:
        self.counter = counter

    async def __aenter__(self) -> _FakeMcpSession:
        self.counter.append(1)
        return _FakeMcpSession()

    async def __aexit__(self, *_args: Any) -> None:
        return None


def test_duas_chamadas_mcp_reutilizam_a_mesma_sessao() -> None:
    client = McpStdioClient()
    openings: list[int] = []
    client._session = lambda _config: _CountingSession(openings)  # type: ignore[method-assign]
    config = McpServerConfig(
        id="tavily",
        name="Tavily",
        enabled=True,
        command="fake",
        timeout=1,
        allowed_tools=["tavily_search"],
    )

    async def call_twice() -> None:
        try:
            await client.call_tool(config, "tavily_search", {"query": "um"})
            await client.call_tool(config, "tavily_search", {"query": "dois"})
        finally:
            await client.shutdown()

    asyncio.run(call_twice())

    assert len(openings) == 1


class _SlowFakeMcpSession(_FakeMcpSession):
    async def initialize(self) -> None:
        await asyncio.sleep(0.01)


class _SlowCountingSession(_CountingSession):
    async def __aenter__(self) -> _FakeMcpSession:
        self.counter.append(1)
        return _SlowFakeMcpSession()


def test_chamadas_simultaneas_compartilham_o_mesmo_aquecimento() -> None:
    client = McpStdioClient()
    openings: list[int] = []
    client._session = lambda _config: _SlowCountingSession(openings)  # type: ignore[method-assign]
    config = McpServerConfig(
        id="tavily",
        name="Tavily",
        enabled=True,
        command="fake",
        timeout=1,
        allowed_tools=["tavily_search"],
    )

    async def call_together() -> None:
        try:
            await asyncio.gather(
                client.call_tool(config, "tavily_search", {"query": "um"}),
                client.call_tool(config, "tavily_search", {"query": "dois"}),
            )
        finally:
            await client.shutdown()

    asyncio.run(call_together())

    assert len(openings) == 1


def test_runners_de_provider_nao_criam_manager_mcp_por_chamada() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "mcp_provider_tools.py"
    ).read_text(encoding="utf-8")

    assert "McpManager().discover" not in source
    assert "McpManager().call_tool" not in source
