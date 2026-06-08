from __future__ import annotations

import json
from typing import Any

import pytest

from hana_agent_oss.core.protocol import AgentRequest
from hana_agent_oss.core.runtime import HanaAgentCore
from hana_agent_oss.core.protocol import ToolResult
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.memory.storage import RuntimeStore
from hana_agent_oss.providers.contracts import ProviderRequest
from hana_agent_oss.providers.provider_selector.gemini_api import provider as gemini_provider_module
from hana_agent_oss.providers.provider_selector.gemini_api.provider import GeminiApiProvider
from hana_agent_oss.tools import omni_tools
from hana_agent_oss.tools.omni_tools import omni_delegate, omni_supervise, parse_omni_report


class _FakeHttpResponse:
    """Minimal context manager used to fake urllib HTTP responses."""

    def __init__(self, body: dict[str, Any]) -> None:
        self._payload = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_omni_delegate_requires_task() -> None:
    result = omni_delegate({})

    assert result.ok is False
    assert result.tool == "omni.delegate"
    assert result.error == "task is required."


def test_omni_delegate_posts_to_local_omni(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse({"status": "success", "response": "STATUS: done\nRESUMO: ok"})

    monkeypatch.setattr(omni_tools.urllib.request, "urlopen", fake_urlopen)

    result = omni_delegate({"task": "listar processos da Steam", "mode": "inspect", "timeout_seconds": 30})

    assert result.ok is True
    assert captured["url"] == "http://127.0.0.1:8060/api/command"
    assert captured["timeout"] == 30
    assert "listar processos da Steam" in captured["body"]["command"]
    assert "Hana is the supervising assistant" in captured["body"]["command"]
    assert "Respect the requested mode: inspect" in captured["body"]["command"]
    assert result.output["backend"] == "omni"
    assert result.output["status"] == "success"
    assert "STATUS: done" in result.output["response"]
    assert result.output["completion_status"] == "done"


def test_omni_delegate_normalizes_repair_alias_to_review(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse({"status": "success", "response": "STATUS: done\nRESUMO: ok"})

    monkeypatch.setattr(omni_tools.urllib.request, "urlopen", fake_urlopen)

    result = omni_delegate({"task": "revisar resultado anterior", "mode": "repair"})

    assert result.ok is True
    assert result.output["mode"] == "review"
    assert "Mode: review" in captured["body"]["command"]


def test_parse_omni_report_keeps_structured_fields() -> None:
    report = parse_omni_report(
        "\n".join(
            [
                "STATUS: needs_review",
                "RESUMO: encontrou parte do problema",
                "EVIDENCIAS: arquivo A",
                "arquivo B",
                "PENDENCIAS: falta testar",
                "PROXIMO_PASSO: rodar validacao",
            ]
        )
    )

    assert report["status"] == "needs_review"
    assert report["summary"] == "encontrou parte do problema"
    assert report["evidence"] == "arquivo A\narquivo B"
    assert report["pending"] == "falta testar"
    assert report["next_step"] == "rodar validacao"


def test_omni_supervise_runs_follow_up_until_done(monkeypatch) -> None:
    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(body["command"])
        if len(calls) == 1:
            return _FakeHttpResponse(
                {
                    "status": "success",
                    "response": "STATUS: needs_review\nRESUMO: achei o arquivo\nPENDENCIAS: falta validar",
                }
            )
        return _FakeHttpResponse(
            {
                "status": "success",
                "response": "STATUS: done\nRESUMO: validado\nEVIDENCIAS: teste passou",
            }
        )

    monkeypatch.setattr(omni_tools.urllib.request, "urlopen", fake_urlopen)

    result = omni_supervise({"task": "validar app", "mode": "inspect", "max_rounds": 3})

    assert result.ok is True
    assert len(calls) == 2
    assert "Previous report" in calls[1]
    assert "If you hit an internal action limit" in calls[1]
    assert result.output["completion_status"] == "done"
    assert result.output["round_count"] == 2
    assert result.output["needs_follow_up"] is False


def test_agent_core_registers_and_runs_omni_delegate(tmp_path, monkeypatch) -> None:
    def fake_urlopen(_request, timeout=None):
        return _FakeHttpResponse({"status": "success", "response": "STATUS: done\nRESUMO: Omni inspecionou."})

    monkeypatch.setattr(omni_tools.urllib.request, "urlopen", fake_urlopen)
    core = HanaAgentCore(store=RuntimeStore(tmp_path / "runtime.sqlite3"))

    response = core.run(AgentRequest("omni.delegate verificar a pasta Downloads", channel="terminal_agent"))

    tool_names = {tool.name for tool in core.tools.list()}
    capability_ids = {capability.id for capability in core.capabilities.list()}
    assert "omni.delegate" in tool_names
    assert "omni.supervise" in tool_names
    assert "omni.bridge" in capability_ids
    assert response.ok is True
    assert response.tool_result is not None
    assert response.tool_result.tool == "omni.delegate"
    assert "Omni retornou (success, done)" in response.response
    assert "Omni inspecionou" in response.response


def test_agent_core_omni_schema_uses_string_acceptance(tmp_path) -> None:
    core = HanaAgentCore(store=RuntimeStore(tmp_path / "runtime.sqlite3"))

    omni_tool = next(tool for tool in core.tools.list() if tool.name == "omni.supervise")

    assert omni_tool.input_schema["properties"]["acceptance"] == {"type": "string"}
    assert omni_tool.input_schema["properties"]["mode"]["enum"] == ["execute", "inspect", "review"]


def test_gemini_provider_omni_callable_runs_supervision_and_logs(tmp_path, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_omni_supervise(args: dict[str, Any]) -> ToolResult:
        captured.update(args)
        return ToolResult(
            ok=True,
            tool="omni.supervise",
            output={
                "status": "success",
                "completion_status": "done",
                "needs_follow_up": False,
                "response": "STATUS: done\nRESUMO: pronto",
            },
        )

    monkeypatch.setattr(gemini_provider_module, "run_omni_supervise", fake_run_omni_supervise)
    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    memory.set_setting("connections_config", {"omni": True, "omniUrl": "http://127.0.0.1:8060"})
    request = ProviderRequest(
        provider="gemini_api",
        model="gemini-3.5-flash",
        messages=[{"role": "user", "content": "delegue ao Omni"}],
        memory=memory,
    )
    callable_tool = GeminiApiProvider()._omni_supervise_callable(request)
    assert callable_tool is not None

    result = callable_tool("verificar processos da Steam", mode="inspect", acceptance="relatar evidencias", max_rounds=2)

    assert captured["task"] == "verificar processos da Steam"
    assert captured["mode"] == "inspect"
    assert captured["acceptance"] == "relatar evidencias"
    assert captured["max_rounds"] == 2
    assert result["ok"] is True
    assert result["tool"] == "omni.supervise"
    events = memory.recent_events(limit=5, channel="terminal_agent")
    assert any(item["metadata"].get("toolName") == "omni.supervise" and item["metadata"].get("status") == "running" for item in events)
    assert any(item["metadata"].get("toolName") == "omni.supervise" and item["metadata"].get("status") == "success" for item in events)


def test_gemini_provider_omni_callable_uses_runtime_safe_annotations(tmp_path) -> None:
    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    memory.set_setting("connections_config", {"omni": True, "omniUrl": "http://127.0.0.1:8060"})
    request = ProviderRequest(provider="gemini_api", model="gemini-3.5-flash", messages=[], memory=memory)

    callable_tool = GeminiApiProvider()._omni_supervise_callable(request)

    assert callable_tool is not None
    assert callable_tool.__annotations__ == {
        "task": str,
        "mode": str,
        "acceptance": str,
        "max_rounds": int,
        "return": dict,
    }


def test_gemini_provider_omni_callable_generates_string_acceptance_schema(tmp_path) -> None:
    genai = pytest.importorskip("google.genai")
    types = pytest.importorskip("google.genai.types")

    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    memory.set_setting("connections_config", {"omni": True, "omniUrl": "http://127.0.0.1:8060"})
    request = ProviderRequest(provider="gemini_api", model="gemini-3.5-flash", messages=[], memory=memory)
    callable_tool = GeminiApiProvider()._omni_supervise_callable(request)
    assert callable_tool is not None

    client = genai.Client(api_key="dummy")
    declaration = types.FunctionDeclaration.from_callable(client=client._api_client, callable=callable_tool)
    schema = declaration.model_dump()

    acceptance = schema["parameters"]["properties"]["acceptance"]
    assert acceptance["type"] == "STRING"
    assert acceptance.get("items") is None


def test_gemini_provider_omni_callable_is_disabled_by_config(tmp_path) -> None:
    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    memory.set_setting("connections_config", {"omni": False, "omniUrl": "http://127.0.0.1:8060"})
    request = ProviderRequest(provider="gemini_api", model="gemini-3.5-flash", messages=[], memory=memory)

    assert GeminiApiProvider()._omni_supervise_callable(request) is None


def test_gemini_provider_configures_function_calling_for_omni_tools() -> None:
    class FakeFunctionCallingConfig:
        """Capture the mode passed to Gemini function calling configuration."""

        def __init__(self, *, mode: str) -> None:
            self.mode = mode

    class FakeToolConfig:
        """Require the SDK camelCase field used by google-genai."""

        def __init__(
            self,
            *,
            functionCallingConfig: FakeFunctionCallingConfig | None = None,
            includeServerSideToolInvocations: bool | None = None,
        ) -> None:
            self.functionCallingConfig = functionCallingConfig
            self.includeServerSideToolInvocations = includeServerSideToolInvocations

    class FakeTypes:
        """Minimal google-genai types replacement for tool config tests."""

        FunctionCallingConfig = FakeFunctionCallingConfig
        ToolConfig = FakeToolConfig

    server_tool = object()
    local_tool = lambda: None

    tools, tool_config, has_function_calling = GeminiApiProvider._prepare_tool_config(
        FakeTypes,
        [server_tool, local_tool],
    )

    assert tools == [server_tool, local_tool]
    assert has_function_calling is True
    assert tool_config.functionCallingConfig.mode == "AUTO"
    assert tool_config.includeServerSideToolInvocations is True


def test_gemini_provider_configures_server_side_tool_invocations_without_omni() -> None:
    class FakeToolConfig:
        """Capture the server-side invocation flag passed to Gemini."""

        def __init__(self, *, includeServerSideToolInvocations: bool) -> None:
            self.includeServerSideToolInvocations = includeServerSideToolInvocations

    class FakeTypes:
        """Minimal google-genai types replacement for Google Search only."""

        ToolConfig = FakeToolConfig

    server_tool = object()

    tools, tool_config, has_function_calling = GeminiApiProvider._prepare_tool_config(FakeTypes, [server_tool])

    assert tools == [server_tool]
    assert has_function_calling is False
    assert tool_config.includeServerSideToolInvocations is True


def test_gemini_provider_drops_omni_tool_if_function_config_is_unavailable() -> None:
    class BrokenTypes:
        """Simulate an older SDK that cannot create function-calling config."""

        class FunctionCallingConfig:
            def __init__(self, *, mode: str) -> None:
                self.mode = mode

        class ToolConfig:
            def __init__(self, **_kwargs: Any) -> None:
                raise TypeError("unsupported")

    server_tool = object()
    local_tool = lambda: None

    tools, tool_config, has_function_calling = GeminiApiProvider._prepare_tool_config(
        BrokenTypes,
        [server_tool, local_tool],
    )

    assert tools == [server_tool]
    assert tool_config is None
    assert has_function_calling is False
