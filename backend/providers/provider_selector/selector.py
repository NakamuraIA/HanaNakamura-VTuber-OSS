from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.providers.contracts import ProviderRequest, ProviderResponse
from backend.providers.provider_aliases import normalize_provider_id as _normalize_provider_id
from backend.providers.provider_selector.deepseek.provider import DeepSeekProvider
from backend.providers.provider_selector.gemini_api.provider import GeminiApiProvider
from backend.providers.provider_selector.groq.provider import GroqProvider
from backend.providers.provider_selector.maritaca.provider import MaritacaProvider
from backend.providers.provider_selector.openrouter.provider import OpenRouterProvider
from backend.providers.provider_selector.qwen.provider import QwenProvider


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    display_name: str
    default_model: str
    rules: tuple[str, ...]
    # Fallback usado em list_models_capabilities() enquanto o catalogo de um
    # provider nao informa supportsStreaming por modelo (ver uso abaixo).
    supports_streaming: bool = True


class ProviderSelector:
    """Selects the active provider and routes generation requests."""

    def __init__(self) -> None:
        self._providers = {
            "gemini_api": GeminiApiProvider(),
            "openrouter": OpenRouterProvider(),
            "groq": GroqProvider(),
            "deepseek": DeepSeekProvider(),
            "qwen": QwenProvider(),
            "maritaca": MaritacaProvider(),
        }
        self._definitions = {
            "gemini_api": ProviderDefinition(
                provider_id="gemini_api",
                display_name="Gemini API (Google AI Studio)",
                default_model="gemini-3.1-pro-preview",
                rules=(
                    "Use GOOGLE_API_KEY or GEMINI_API_KEY.",
                    "Use native search when native_search_mode is auto or force.",
                    "No external search tool is required for grounded web search.",
                ),
            ),
            "openrouter": ProviderDefinition(
                provider_id="openrouter",
                display_name="OpenRouter",
                default_model="openrouter/auto",
                rules=(
                    "Use OPENROUTER_API_KEY.",
                    "Use dynamic model capabilities from the OpenRouter Models API.",
                    "Do not use Gemini-native search, XML image actions, or Gemini server-side tools.",
                ),
            ),
            "deepseek": ProviderDefinition(
                provider_id="deepseek",
                display_name="DeepSeek (oficial)",
                default_model="deepseek-v4-flash",
                rules=(
                    "Use DEEPSEEK_API_KEY.",
                    "API OpenAI-compativel em api.deepseek.com (chat + streaming + tools).",
                    "Sem busca nativa, XML de imagem ou tools server-side do Gemini.",
                ),
            ),
            "qwen": ProviderDefinition(
                provider_id="qwen",
                display_name="Qwen (Alibaba Cloud Model Studio)",
                default_model="qwen-plus",
                rules=(
                    "Use QWEN_API_KEY (ou DASHSCOPE_API_KEY).",
                    "API OpenAI-compativel em dashscope-us.aliyuncs.com (chat + streaming + tools).",
                    "Sem busca nativa, XML de imagem ou tools server-side do Gemini.",
                ),
            ),
            "maritaca": ProviderDefinition(
                provider_id="maritaca",
                display_name="Maritaca AI (Sabia)",
                default_model="sabia-4",
                rules=(
                    "Use MARITACA_API_KEY.",
                    "API OpenAI-compativel em chat.maritaca.ai/api (chat + streaming + tools).",
                    "Header de auth usa 'Key', nao 'Bearer'.",
                    "Sem busca nativa, XML de imagem ou tools server-side do Gemini.",
                ),
            ),
            "groq": ProviderDefinition(
                provider_id="groq",
                display_name="Groq",
                default_model="llama-3.3-70b-versatile",
                rules=(
                    "Use GROQ_API_KEY.",
                    "Use Groq OpenAI-compatible Chat Completions.",
                    "Do not use Gemini-native search, XML image actions, or Gemini server-side tools.",
                    "Compound models may use Groq-managed server-side search/code execution.",
                ),
            ),
        }

    @staticmethod
    def normalize_provider_id(provider: str) -> str:
        """Normalize legacy/spoken provider IDs before dispatching requests."""
        return _normalize_provider_id(provider)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        provider_id = self.normalize_provider_id(request.provider or "gemini_api")
        provider = self.get_provider(provider_id)
        if provider is None:
            return ProviderResponse(ok=False, error=f"provider_not_supported:{provider_id}")
        return provider.generate(request)

    def get_provider(self, provider: str) -> Any | None:
        """Retorna o provider selecionado para a política e para a execução."""
        return self._providers.get(self.normalize_provider_id(provider))

    def get_model_info(self, provider: str, model: str) -> dict[str, Any] | None:
        """Consulta capacidades do modelo para a política de execução.

        Durante a migração, alguns catálogos antigos ainda não informam as
        capacidades por modelo. Nesses casos, usamos temporariamente o
        padrão do provider. Isso preserva o comportamento antigo sem devolver
        ao ``chat.py`` a responsabilidade de decidir sobre streaming.
        """
        provider_id = self.normalize_provider_id(provider)
        selected = self.get_provider(provider_id)
        getter = getattr(selected, "_catalog_model", None)
        if not callable(getter):
            return None
        info = getter(str(model or "").strip())
        if not isinstance(info, dict):
            return None

        normalized = dict(info)
        definition = self._definitions.get(provider_id)
        used_legacy_fallback = False

        # Estes campos serão preenchidos pelo catálogo de cada provider após
        # a migração. Até lá, o padrão antigo mantém streaming funcionando.
        if "supportsStreaming" not in normalized and definition is not None:
            normalized["supportsStreaming"] = definition.supports_streaming
            used_legacy_fallback = True
        if "supportsStreamingTools" not in normalized:
            normalized["supportsStreamingTools"] = bool(
                normalized.get("supportsTools", False)
            )
            used_legacy_fallback = True
        if used_legacy_fallback:
            normalized["_legacyCapabilityFallback"] = True

        return normalized
