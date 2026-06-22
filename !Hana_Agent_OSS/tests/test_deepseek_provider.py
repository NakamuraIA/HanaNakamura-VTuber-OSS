from __future__ import annotations


def test_deepseek_registered_in_selector() -> None:
    from hana_agent_oss.providers.provider_selector.selector import ProviderSelector

    sel = ProviderSelector()
    assert "deepseek" in sel._providers
    assert sel.normalize_provider_id("deepseek") == "deepseek"
    assert sel.normalize_provider_id("deep_seek") == "deepseek"
    assert "deepseek" in [d.provider_id for d in sel.list_definitions()]


def test_deepseek_provider_config() -> None:
    from hana_agent_oss.providers.provider_selector.deepseek.provider import DeepSeekProvider

    p = DeepSeekProvider()
    assert p.provider_id == "deepseek"
    assert p.api_key_env == "DEEPSEEK_API_KEY"
    assert p.chat_completions_url.startswith("https://api.deepseek.com")
    # herda o streaming OpenAI-compat do OpenRouterProvider
    assert hasattr(p, "generate_stream")


def test_deepseek_is_streamable() -> None:
    from hana_agent_oss.api.services.chat import STREAMING_PROVIDERS
    from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider

    assert {"openrouter", "groq", "deepseek"} <= STREAMING_PROVIDERS
    assert type(OpenRouterProvider._provider_for("deepseek")).__name__ == "DeepSeekProvider"


def test_deepseek_catalog_models() -> None:
    from hana_agent_oss.providers.provider_selector.deepseek.catalog import (
        get_deepseek_catalog,
        get_deepseek_model,
    )

    models, _error = get_deepseek_catalog()
    ids = {m["id"] for m in models}
    assert {"deepseek-v4-flash", "deepseek-v4-pro"} <= ids
    assert get_deepseek_model("deepseek-v4-flash")["supportsTools"] is True
    # preco em per-token (string pequena), pra o formatter x1M do painel exibir certo
    assert float(get_deepseek_model("deepseek-v4-flash")["pricing"]["prompt"]) < 0.001


def test_deepseek_in_catalog_payload() -> None:
    import os
    import tempfile

    from hana_agent_oss.api.services.catalog import catalog_payload
    from hana_agent_oss.memory.store import MemoryStore

    d = tempfile.mkdtemp()
    memory = MemoryStore(os.path.join(d, "m.sqlite3"), os.path.join(d, "e.jsonl"))
    cat = catalog_payload(memory)
    assert "deepseek" in cat["llmProviders"]
    assert any(m.get("provider") == "deepseek" for m in cat["models"])
    assert "deepseek" in cat["catalogStatus"]
