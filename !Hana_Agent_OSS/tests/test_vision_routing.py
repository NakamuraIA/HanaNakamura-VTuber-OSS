from __future__ import annotations

from hana_agent_oss.api.services.catalog import (
    catalog_provider_for_model,
    model_supports_vision,
    resolve_vision_target,
)


def test_infers_provider_from_vision_model() -> None:
    # so o visionModel setado -> infere o provider dono (qwen3.5-flash pertence ao qwen)
    assert catalog_provider_for_model("qwen3.5-flash") == "qwen"


def test_resolve_vision_target_variants() -> None:
    # inferido pelo modelo
    assert resolve_vision_target({"visionModel": "qwen3.5-flash"}) == ("qwen", "qwen3.5-flash")
    # provider explicito ganha
    assert resolve_vision_target({"visionModel": "qwen3.5-flash", "visionProvider": "qwen"}) == ("qwen", "qwen3.5-flash")
    # gemini (fallback final quando nao infere)
    assert resolve_vision_target({"visionModel": "gemini-3-flash-preview"})[0] == "gemini_api"
    # sem visionModel -> nao ha alvo
    assert resolve_vision_target({}) == ("", "")


def test_routing_decision_deepseek_to_qwen() -> None:
    # deepseek (so-texto) nao ve; qwen3.5-flash ve -> deve rotear
    provider, model = "deepseek", "deepseek-v4-flash"
    assert model_supports_vision(provider, model) is False
    vp, vm = resolve_vision_target({"visionModel": "qwen3.5-flash"})
    should_route = bool(vm) and (vp, vm) != (provider, model) and model_supports_vision(vp, vm)
    assert should_route is True
    assert (vp, vm) == ("qwen", "qwen3.5-flash")


def test_no_routing_when_chat_already_sees() -> None:
    # gemini_api sempre ve -> nao precisa rotear
    assert model_supports_vision("gemini_api", "gemini-3.1-pro-preview") is True


# 1x1 PNG valido em base64 (pra simular anexo de imagem real).
_PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def test_run_text_turn_routes_image_to_vision_provider(monkeypatch, tmp_path) -> None:
    """Imagem + provider do chat que nao ve -> o turno roda no provider de visao."""
    import asyncio

    from hana_agent_oss.api.services import chat as chat_service
    from hana_agent_oss.memory.store import MemoryStore
    from hana_agent_oss.providers.contracts import ProviderResponse

    memory = MemoryStore(db_path=tmp_path / "m.sqlite3", events_path=tmp_path / "e.jsonl")
    # chat no deepseek (so-texto); visao configurada no qwen3.5-flash
    memory.set_setting("llm_config", {"visionModel": "qwen3.5-flash"})
    captured: dict = {}

    def fake_provider(request):
        captured["provider"] = request.provider
        captured["model"] = request.model
        return ProviderResponse(ok=True, text="Vi a imagem.", meta={"nativeSearch": False})

    monkeypatch.setattr(chat_service.PROVIDER_SELECTOR, "generate", fake_provider)

    result = asyncio.run(
        chat_service.run_text_turn(
            {
                "text": "o que tem nessa imagem?",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "channel": "discord",
                "attachments": [{"name": "foto.png", "type": "image/png", "data": _PNG_1X1}],
            },
            core=object(),
            memory=memory,
        )
    )

    assert result["ok"] is True
    # roteou pro provider/modelo de visao em vez do deepseek
    assert captured["provider"] == "qwen"
    assert captured["model"] == "qwen3.5-flash"


def test_run_text_turn_keeps_provider_when_it_sees(monkeypatch, tmp_path) -> None:
    """Sem imagem (ou provider ja ve), nao mexe no provider do chat."""
    import asyncio

    from hana_agent_oss.api.services import chat as chat_service
    from hana_agent_oss.memory.store import MemoryStore
    from hana_agent_oss.providers.contracts import ProviderResponse

    memory = MemoryStore(db_path=tmp_path / "m.sqlite3", events_path=tmp_path / "e.jsonl")
    memory.set_setting("llm_config", {"visionModel": "qwen3.5-flash"})
    captured: dict = {}

    def fake_provider(request):
        captured["provider"] = request.provider
        return ProviderResponse(ok=True, text="ok", meta={"nativeSearch": False})

    monkeypatch.setattr(chat_service.PROVIDER_SELECTOR, "generate", fake_provider)

    asyncio.run(
        chat_service.run_text_turn(
            {"text": "oi sem imagem", "provider": "deepseek", "model": "deepseek-v4-flash", "channel": "discord"},
            core=object(),
            memory=memory,
        )
    )
    assert captured["provider"] == "deepseek"  # nao roteou
