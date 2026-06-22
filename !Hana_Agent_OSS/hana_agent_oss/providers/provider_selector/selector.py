from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hana_agent_oss.providers.contracts import ProviderRequest, ProviderResponse
from hana_agent_oss.providers.provider_selector.deepseek.provider import DeepSeekProvider
from hana_agent_oss.providers.provider_selector.gemini_api.provider import GeminiApiProvider
from hana_agent_oss.providers.provider_selector.groq.provider import GroqProvider
from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider


@dataclass(frozen=True)
class ProviderCapabilities:
    multimodal_input: bool = True
    supports_image: bool = True
    supports_audio: bool = True
    supports_video: bool = True
    supports_pdf: bool = True
    supports_native_web_search: bool = True
    supports_streaming: bool = True
    supports_structured_output: bool = True
    supports_function_calling: bool = True
    supports_code_execution: bool = True
    supports_image_generation: bool = True
    supports_video_generation: bool = True
    supports_tts: bool = True
    supports_live_voice: bool = True
    supports_memory_embeddings: bool = True
    supports_rag: bool = True

    def to_dict(self) -> dict[str, bool]:
        return {
            "multimodal_input": self.multimodal_input,
            "supports_image": self.supports_image,
            "supports_audio": self.supports_audio,
            "supports_video": self.supports_video,
            "supports_pdf": self.supports_pdf,
            "supports_native_web_search": self.supports_native_web_search,
            "supports_streaming": self.supports_streaming,
            "supports_structured_output": self.supports_structured_output,
            "supports_function_calling": self.supports_function_calling,
            "supports_code_execution": self.supports_code_execution,
            "supports_image_generation": self.supports_image_generation,
            "supports_video_generation": self.supports_video_generation,
            "supports_tts": self.supports_tts,
            "supports_live_voice": self.supports_live_voice,
            "supports_memory_embeddings": self.supports_memory_embeddings,
            "supports_rag": self.supports_rag,
        }


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    display_name: str
    default_model: str
    rules: tuple[str, ...]
    capabilities: ProviderCapabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "default_model": self.default_model,
            "rules": list(self.rules),
            "capabilities": self.capabilities.to_dict(),
        }


class ProviderSelector:
    """Selects the active provider and routes generation requests."""

    def __init__(self) -> None:
        self._providers = {
            "gemini_api": GeminiApiProvider(),
            "openrouter": OpenRouterProvider(),
            "groq": GroqProvider(),
            "deepseek": DeepSeekProvider(),
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
                capabilities=ProviderCapabilities(),
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
                capabilities=ProviderCapabilities(
                    multimodal_input=True,
                    supports_image=True,
                    supports_audio=False,
                    supports_video=False,
                    supports_pdf=True,
                    supports_native_web_search=False,
                    supports_streaming=True,
                    supports_structured_output=True,
                    supports_function_calling=True,
                    supports_code_execution=False,
                    supports_image_generation=False,
                    supports_video_generation=False,
                    supports_tts=False,
                    supports_live_voice=False,
                    supports_memory_embeddings=False,
                    supports_rag=False,
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
                capabilities=ProviderCapabilities(
                    multimodal_input=False,
                    supports_image=False,
                    supports_audio=False,
                    supports_video=False,
                    supports_pdf=False,
                    supports_native_web_search=False,
                    supports_streaming=True,
                    supports_structured_output=True,
                    supports_function_calling=True,
                    supports_code_execution=False,
                    supports_image_generation=False,
                    supports_video_generation=False,
                    supports_tts=False,
                    supports_live_voice=False,
                    supports_memory_embeddings=False,
                    supports_rag=False,
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
                capabilities=ProviderCapabilities(
                    multimodal_input=True,
                    supports_image=True,
                    supports_audio=False,
                    supports_video=False,
                    supports_pdf=False,
                    supports_native_web_search=True,
                    supports_streaming=True,
                    supports_structured_output=True,
                    supports_function_calling=True,
                    supports_code_execution=True,
                    supports_image_generation=False,
                    supports_video_generation=False,
                    supports_tts=False,
                    supports_live_voice=False,
                    supports_memory_embeddings=False,
                    supports_rag=False,
                ),
            ),
        }

    @staticmethod
    def normalize_provider_id(provider: str) -> str:
        """Normalize legacy/spoken provider IDs before dispatching requests."""
        raw = str(provider or "").strip().lower()
        return {
            "google_platform": "gemini_api",
            "google_cloud": "gemini_api",
            "google": "gemini_api",
            "google_ai_studio": "gemini_api",
            "gemini": "gemini_api",
            "open_router": "openrouter",
            "openrouters": "openrouter",
            "groq_cloud": "groq",
            "groqcloud": "groq",
            "glock": "groq",
            "deepseek_official": "deepseek",
            "deep_seek": "deepseek",
        }.get(raw, raw or "gemini_api")

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        provider_id = self.normalize_provider_id(request.provider or "gemini_api")
        provider = self._providers.get(provider_id)
        if provider is None:
            return ProviderResponse(ok=False, error=f"provider_not_supported:{provider_id}")
        return provider.generate(request)

    def list_definitions(self) -> list[ProviderDefinition]:
        return list(self._definitions.values())
