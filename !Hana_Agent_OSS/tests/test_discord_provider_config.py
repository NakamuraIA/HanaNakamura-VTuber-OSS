from __future__ import annotations

import asyncio

from hana_agent_oss.discord_bot.cogs.config import (
    SAME_AS_CHAT_VALUE,
    apply_config,
    build_config_calls,
    model_ids_for,
    provider_ids_for,
)


CATALOG = {
    "llmProviders": ["gemini_api", "openrouter", "groq", "deepseek", "qwen", "maritaca"],
    "imageProviders": ["gemini_api", "openrouter"],
    "models": [
        {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3", "provider": "groq", "outputModalities": ["text"]},
        {"id": "qwen-plus", "label": "Qwen Plus", "provider": "qwen", "outputModalities": ["text"]},
        # modelo so-imagem do openrouter nao deve entrar na lista de texto
        {"id": "x-ai/grok-imagine", "label": "Grok Imagine", "provider": "openrouter", "outputModalities": ["image"]},
    ],
    "imageModels": [
        {"id": "x-ai/grok-imagine", "label": "Grok Imagine", "provider": "openrouter"},
    ],
}


# --- build_config_calls: o coracao do mapeamento --------------------------- #

def test_chat_writes_both_configs() -> None:
    # Chat precisa escrever em chat_config (o que o Discord le) E llm_config (painel).
    calls = build_config_calls("chat", "groq", "llama-3.3-70b-versatile")
    assert calls == [
        ("update_chat_config", {"provider": "groq", "model": "llama-3.3-70b-versatile"}),
        ("update_llm_config", {"llmProvider": "groq", "llmModel": "llama-3.3-70b-versatile"}),
    ]


def test_agente_normal_and_same_as_chat() -> None:
    assert build_config_calls("agente", "deepseek", "deepseek-v4-flash") == [
        ("update_llm_config", {"agentProvider": "deepseek", "agentModel": "deepseek-v4-flash"}),
    ]
    # "mesmo do chat" zera o provider do agente
    assert build_config_calls("agente", SAME_AS_CHAT_VALUE, "") == [
        ("update_llm_config", {"agentProvider": "", "agentModel": ""}),
    ]


def test_imagem_openrouter_carries_model_but_gemini_does_not() -> None:
    assert build_config_calls("imagem", "openrouter", "x-ai/grok-imagine") == [
        ("update_image_config", {"imageProvider": "openrouter", "openrouterImageModel": "x-ai/grok-imagine"}),
    ]
    assert build_config_calls("imagem", "gemini_api", "") == [
        ("update_image_config", {"imageProvider": "gemini_api"}),
    ]


# --- helpers de catalogo --------------------------------------------------- #

def test_provider_ids_for_category() -> None:
    assert provider_ids_for("chat", CATALOG) == CATALOG["llmProviders"]
    assert provider_ids_for("agente", CATALOG) == CATALOG["llmProviders"]
    assert provider_ids_for("imagem", CATALOG) == CATALOG["imageProviders"]


def test_model_ids_filters_by_provider_and_modality() -> None:
    groq = model_ids_for("chat", "groq", CATALOG)
    assert groq == [{"id": "llama-3.3-70b-versatile", "label": "Llama 3.3"}]
    # openrouter no chat: o unico modelo dele e so-imagem -> filtrado fora
    assert model_ids_for("chat", "openrouter", CATALOG) == []
    # mas na categoria imagem, aparece
    assert model_ids_for("imagem", "openrouter", CATALOG) == [
        {"id": "x-ai/grok-imagine", "label": "Grok Imagine"},
    ]


# --- apply_config despacha pros metodos certos do backend ------------------ #

def test_apply_config_dispatches_to_backend() -> None:
    class FakeBackend:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def update_chat_config(self, payload):
            self.calls.append(("chat", payload))

        async def update_llm_config(self, payload):
            self.calls.append(("llm", payload))

        async def update_image_config(self, payload):
            self.calls.append(("image", payload))

    backend = FakeBackend()
    asyncio.run(apply_config(backend, "chat", "groq", "llama-3.3-70b-versatile"))
    assert backend.calls == [
        ("chat", {"provider": "groq", "model": "llama-3.3-70b-versatile"}),
        ("llm", {"llmProvider": "groq", "llmModel": "llama-3.3-70b-versatile"}),
    ]
