from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.mcp.client import McpEnvMissing, McpSessionClosed, McpStdioClient
from backend.mcp.config import MCP_PRESETS, McpConfigStore
from backend.mcp.contracts import McpServerConfig
from backend.mcp.manager import McpManager
from backend.tools.mcp_provider_tools import mcp_openai_runners


def _config(
    *,
    enabled: bool = True,
    command: str = "fake",
    server_id: str = "tavily",
    timeout: float = 1,
) -> McpServerConfig:
    return McpServerConfig(
        id=server_id,
        name="Tavily",
        enabled=enabled,
        command=command,
        timeout=timeout,
        allowed_tools=["tavily_search"],
    )


class _Session:
    def __init__(self, *, fail_call: bool = False) -> None:
        self.fail_call = fail_call
        self.calls = 0

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> Any:
        return SimpleNamespace(tools=[SimpleNamespace(name="tavily_search")])

    async def call_tool(self, _tool: str, _arguments: dict[str, Any]) -> Any:
        self.calls += 1
        if self.fail_call:
            raise RuntimeError("transport_closed")
        return SimpleNamespace(content=[], structuredContent={}, isError=False)


class _Context:
    def __init__(self, session: _Session, tasks: dict[str, int] | None = None) -> None:
        self.session = session
        self.tasks = tasks

    async def __aenter__(self) -> _Session:
        if self.tasks is not None:
            self.tasks["enter"] = id(asyncio.current_task())
        return self.session

    async def __aexit__(self, *_args: Any) -> None:
        if self.tasks is not None:
            self.tasks["exit"] = id(asyncio.current_task())


def test_shutdown_fecha_contexto_na_mesma_tarefa_que_abriu() -> None:
    client = McpStdioClient()
    tasks: dict[str, int] = {}
    client._session = lambda _server: _Context(_Session(), tasks)  # type: ignore[method-assign]

    async def scenario() -> None:
        await client.warmup(_config())
        await client.shutdown()

    asyncio.run(scenario())

    assert tasks["enter"] == tasks["exit"]
    assert not any(
        thread.name == "hana-mcp-runtime" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_servidores_diferentes_mantem_sessoes_independentes() -> None:
    client = McpStdioClient()
    openings: list[str] = []

    def factory(server: McpServerConfig) -> _Context:
        openings.append(server.id)
        return _Context(_Session())

    client._session = factory  # type: ignore[method-assign]

    async def scenario() -> None:
        try:
            await asyncio.gather(
                client.warmup(_config(server_id="tavily")),
                client.warmup(_config(server_id="outro")),
            )
        finally:
            await client.shutdown()

    asyncio.run(scenario())

    assert sorted(openings) == ["outro", "tavily"]


def test_warmup_de_sessao_pronta_nao_volta_status_para_aquecendo() -> None:
    client = McpStdioClient()
    client._session = lambda _server: _Context(_Session())  # type: ignore[method-assign]
    config = _config()

    async def scenario() -> None:
        await client.warmup(config)
        assert client.runtime_status(config.id)["status"] == "ready"
        client.warmup_background(config)
        assert client.runtime_status(config.id)["status"] == "ready"
        await client.shutdown()

    asyncio.run(scenario())


class _BlockingSession(_Session):
    def __init__(self, started: threading.Event) -> None:
        super().__init__()
        self.started = started

    async def call_tool(self, _tool: str, _arguments: dict[str, Any]) -> Any:
        self.started.set()
        while True:
            await asyncio.sleep(0.01)


def test_desligar_durante_chamada_nao_reabre_o_servidor() -> None:
    client = McpStdioClient()
    started = threading.Event()
    openings: list[int] = []

    def factory(_server: McpServerConfig) -> _Context:
        openings.append(1)
        return _Context(_BlockingSession(started))

    client._session = factory  # type: ignore[method-assign]
    config = _config()

    async def scenario() -> None:
        first = asyncio.create_task(client.call_tool(config, "tavily_search", {"query": "um"}))
        assert await asyncio.to_thread(started.wait, 1)
        queued = asyncio.create_task(client.call_tool(config, "tavily_search", {"query": "dois"}))
        await asyncio.sleep(0.02)
        await client.close_server(config.id)
        for call in (first, queued):
            with pytest.raises(McpSessionClosed, match="mcp_session_closed"):
                await call
        with pytest.raises(McpSessionClosed, match="mcp_server_stopped_or_reconfigured"):
            await client.call_tool(config, "tavily_search", {"query": "tres"})
        assert client.runtime_status(config.id)["status"] == "disabled"
        await client.shutdown()

    asyncio.run(scenario())

    assert openings == [1]


class _HangingInitializeSession(_Session):
    def __init__(self, started: threading.Event) -> None:
        super().__init__()
        self.started = started

    async def initialize(self) -> None:
        self.started.set()
        while True:
            await asyncio.sleep(0.01)


def test_desligar_durante_aquecimento_cancela_sem_reabrir() -> None:
    client = McpStdioClient()
    started = threading.Event()
    openings: list[int] = []

    def factory(_server: McpServerConfig) -> _Context:
        openings.append(1)
        return _Context(_HangingInitializeSession(started))

    client._session = factory  # type: ignore[method-assign]
    config = _config(timeout=5)

    async def scenario() -> None:
        warmup = asyncio.create_task(client.warmup(config))
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.wait_for(client.close_server(config.id), timeout=0.5)
        with pytest.raises(asyncio.CancelledError):
            await warmup
        assert client.runtime_status(config.id)["status"] == "disabled"
        await client.shutdown()

    asyncio.run(scenario())

    assert openings == [1]


class _HangingContext:
    async def __aenter__(self) -> _Session:
        while True:
            await asyncio.sleep(0.01)

    async def __aexit__(self, *_args: Any) -> None:
        return None


def test_timeout_cobre_tambem_a_abertura_do_transporte() -> None:
    client = McpStdioClient()
    client._session = lambda _server: _HangingContext()  # type: ignore[method-assign]
    config = _config(timeout=0.05)

    async def scenario() -> None:
        started_at = asyncio.get_running_loop().time()
        with pytest.raises(TimeoutError):
            await client.warmup(config)
        assert asyncio.get_running_loop().time() - started_at < 0.5
        assert client.runtime_status(config.id)["status"] == "error"
        await client.shutdown()

    asyncio.run(scenario())


def test_config_antiga_nao_reabre_servidor_apos_reconfiguracao() -> None:
    client = McpStdioClient()
    openings: list[str] = []

    def factory(server: McpServerConfig) -> _Context:
        openings.append(server.command)
        return _Context(_Session())

    client._session = factory  # type: ignore[method-assign]
    old = _config(command="antigo")
    new = _config(command="novo")

    async def scenario() -> None:
        await client.warmup(old)
        await client.warmup(new)
        with pytest.raises(McpSessionClosed, match="mcp_server_stopped_or_reconfigured"):
            await client.call_tool(old, "tavily_search", {"query": "velha"})
        result = await client.call_tool(new, "tavily_search", {"query": "nova"})
        assert result.ok is True
        await client.shutdown()

    asyncio.run(scenario())

    assert openings == ["antigo", "novo"]


def test_recuperacao_atrasada_da_config_antiga_nao_derruba_sessao_nova() -> None:
    client = McpStdioClient()
    openings: list[str] = []

    def factory(server: McpServerConfig) -> _Context:
        openings.append(server.command)
        return _Context(_Session())

    client._session = factory  # type: ignore[method-assign]
    old = _config(command="antigo")
    new = _config(command="novo")

    async def scenario() -> None:
        await client.warmup(old)
        await client.warmup(new)
        with pytest.raises(McpSessionClosed, match="mcp_server_stopped_or_reconfigured"):
            await client._dispatch(client._recover(old))
        result = await client.call_tool(new, "tavily_search", {"query": "nova"})
        assert result.ok is True
        await client.shutdown()

    asyncio.run(scenario())

    assert openings == ["antigo", "novo"]


def test_queda_reconecta_sem_repetir_a_chamada_incerta() -> None:
    client = McpStdioClient()
    sessions = [_Session(fail_call=True), _Session()]
    openings: list[int] = []

    def factory(_server: McpServerConfig) -> _Context:
        index = len(openings)
        openings.append(index)
        return _Context(sessions[index])

    client._session = factory  # type: ignore[method-assign]

    async def scenario() -> None:
        try:
            with pytest.raises(RuntimeError, match="transport_closed"):
                await client.call_tool(_config(), "tavily_search", {"query": "um"})
            result = await client.call_tool(_config(), "tavily_search", {"query": "dois"})
            assert result.ok is True
        finally:
            await client.shutdown()

    asyncio.run(scenario())

    assert len(openings) == 2
    assert sessions[0].calls == 1
    assert sessions[1].calls == 1


def test_chave_ausente_vira_erro_do_mcp_sem_bloquear_o_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = McpStdioClient()
    missing_name = "HANA_TEST_MCP_KEY_THAT_DOES_NOT_EXIST"
    monkeypatch.delenv(missing_name, raising=False)
    config = _config()
    config.env = {"TOKEN": f"${{{missing_name}}}"}

    def factory(server: McpServerConfig) -> _Context:
        McpStdioClient._resolved_env(server.env)
        return _Context(_Session())

    client._session = factory  # type: ignore[method-assign]

    async def scenario() -> None:
        client.warmup_background(config)
        for _ in range(100):
            if client.runtime_status(config.id).get("status") == "error":
                break
            await asyncio.sleep(0.01)
        assert client.runtime_status(config.id)["status"] == "error"
        assert missing_name in client.runtime_status(config.id)["error"]
        await client.shutdown()

    asyncio.run(scenario())


class _LifecycleClient:
    def __init__(self) -> None:
        self.warmed: list[str] = []
        self.restarted: list[str] = []
        self.closed: list[str] = []
        self.disabled: list[str] = []

    def warmup_background(self, server: McpServerConfig) -> None:
        self.warmed.append(server.id)

    def restart_background(self, server: McpServerConfig) -> None:
        self.restarted.append(server.id)

    def close_server_background(self, server_id: str) -> None:
        self.closed.append(server_id)

    def mark_disabled(self, server_id: str) -> None:
        self.disabled.append(server_id)

    def runtime_status(self, _server_id: str) -> dict[str, str]:
        return {"status": "ready"}

    async def shutdown(self) -> None:
        return None


def test_manager_aquece_so_ativos_e_reinicia_so_config_de_processo(tmp_path: Path) -> None:
    store = McpConfigStore(tmp_path / "mcp.json")
    store.save_payload(
        {
            "servers": [
                _config(enabled=True).to_dict(),
                {**_config(enabled=False).to_dict(), "id": "outro"},
            ]
        }
    )
    client = _LifecycleClient()
    manager = McpManager(config_store=store, client=client)  # type: ignore[arg-type]

    manager.start_enabled_background()
    manager.update_server_config(
        "tavily",
        {"command": "fake", "args": [], "env": {}, "cwd": None, "timeout": 9},
    )
    manager.update_server_config("tavily", {"command": "novo"})
    manager.enable_server("tavily", False)

    assert client.warmed == ["tavily", "tavily"]
    assert client.disabled == ["outro"]
    assert client.restarted == ["tavily"]
    assert client.closed == ["tavily"]


def test_reaplicar_preset_inalterado_nao_reinicia_processo(tmp_path: Path) -> None:
    store = McpConfigStore(tmp_path / "mcp.json")
    store.save_payload({"servers": [{**MCP_PRESETS["tavily"], "enabled": True}]})
    client = _LifecycleClient()
    manager = McpManager(config_store=store, client=client)  # type: ignore[arg-type]

    manager.upsert_preset("tavily")

    assert client.warmed == ["tavily"]
    assert client.restarted == []


def test_provider_usa_o_manager_injetado() -> None:
    class InjectedManager:
        def __init__(self) -> None:
            self.calls = 0

        async def discover(self, _server_id: str | None = None) -> dict[str, Any]:
            self.calls += 1
            return {"servers": []}

    manager = InjectedManager()
    runners = mcp_openai_runners(None, manager=manager)  # type: ignore[arg-type]

    assert runners["mcp_discover"]({})["ok"] is True
    assert runners["mcp_discover"]({})["ok"] is True
    assert manager.calls == 2


def test_lifespan_aquece_e_fecha_o_mesmo_manager() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "api"
        / "server.py"
    ).read_text(encoding="utf-8")

    assert "app.state.core.mcp.start_enabled_background()" in source
    assert "await app.state.core.mcp.shutdown()" in source
