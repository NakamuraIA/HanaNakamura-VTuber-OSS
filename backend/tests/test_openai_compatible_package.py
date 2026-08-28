"""Travas estruturais da fase 8 sem chamar APIs externas."""

from __future__ import annotations

from pathlib import Path

from backend.providers.contracts import ProviderRequest
from backend.providers.provider_selector.groq.provider import GroqProvider
from backend.providers.provider_selector.openai_compatible import OpenAICompatibleProvider
from backend.providers.provider_selector.openai_compatible.memory_skills import register_memory_skills
from backend.providers.provider_selector.openai_compatible.tools_builder import build_tool_schemas_and_runners


def test_openai_compatible_e_um_pacote_compartilhado() -> None:
    root = Path("backend/providers/provider_selector")
    assert (root / "openai_compatible" / "__init__.py").is_file()
    assert not (root / "openai_compatible.py").exists()
    assert not (root / "openrouter" / "tools_builder.py").exists()


def test_builder_agregado_entrega_runner_para_cada_schema() -> None:
    provider = OpenAICompatibleProvider()
    request = ProviderRequest(provider="groq", model="teste", messages=[{"role": "user", "content": "teste"}], memory=None)

    schemas, runners = build_tool_schemas_and_runners(provider, request, supports_tools=True)
    names = {schema["function"]["name"] for schema in schemas}

    assert names
    assert names <= runners.keys()


def test_memory_update_preserva_tipo_da_memoria_existente() -> None:
    class FakeMemory:
        def __init__(self) -> None:
            self.items = {"mem-1": {"id": "mem-1", "text": "antigo", "kind": "long_term"}}

        def get_memory(self, memory_id: str):
            return self.items.get(memory_id)

        def add_memory(self, text: str, *, memory_id: str, kind: str, source: str):
            self.items[memory_id] = {"id": memory_id, "text": text, "kind": kind, "source": source}
            return self.items[memory_id]

    memory = FakeMemory()
    provider = OpenAICompatibleProvider()
    request = ProviderRequest(provider="groq", model="teste", messages=[], memory=memory)
    tools: list[dict] = []
    runners: dict = {}

    register_memory_skills(provider, request, {}, tools, runners)
    result = runners["memory_update"]({"id": "mem-1", "text": "corrigido"})

    assert result["ok"] is True
    assert memory.items["mem-1"]["text"] == "corrigido"
    assert memory.items["mem-1"]["kind"] == "long_term"


def test_groq_qwen_usa_niveis_de_raciocinio_aceitos_pela_api() -> None:
    provider = GroqProvider.__new__(GroqProvider)

    ligado: dict = {}
    provider._apply_thinking_control(
        ligado,
        model="qwen/qwen3.6-27b",
        channel="terminal_agent",
        thinking_enabled=True,
    )
    desligado: dict = {}
    provider._apply_thinking_control(
        desligado,
        model="qwen/qwen3.6-27b",
        channel="terminal_agent",
        thinking_enabled=False,
    )

    assert ligado["reasoning_effort"] == "default"
    assert desligado["reasoning_effort"] == "none"
