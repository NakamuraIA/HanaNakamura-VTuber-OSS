from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

import hana_agent_oss.modules.voice.tts_azure as azure_module
import hana_agent_oss.modules.voice.tts_cartesia as cartesia_module
import hana_agent_oss.modules.voice.tts_elevenlabs as elevenlabs_module
import hana_agent_oss.modules.voice.tts_minimax as minimax_module
from hana_agent_oss.modules.voice.tts_azure import AzureTTSProvider
from hana_agent_oss.modules.voice.tts_cartesia import CartesiaTTSProvider
from hana_agent_oss.modules.voice.tts_edge import TTSConfigurationError
from hana_agent_oss.modules.voice.tts_elevenlabs import ElevenlabsTTSProvider
from hana_agent_oss.modules.voice.tts_minimax import MinimaxTTSProvider
from hana_agent_oss.providers.contracts import ProviderRequest
from hana_agent_oss.providers.provider_selector.groq.provider import GroqProvider


VALID_CARTESIA_VOICE = "700d1ee3-a641-4018-ba6e-899dcadc9e2b"


class _FakeAsyncClient:
    """Small async httpx client stand-in that records provider request payloads."""

    def __init__(self, response: httpx.Response, calls: list[dict[str, Any]], **kwargs: Any) -> None:
        """Store the response returned by post calls and the client options."""
        self.response = response
        self.calls = calls
        self.kwargs = kwargs

    async def __aenter__(self) -> "_FakeAsyncClient":
        """Return the fake client for async context-manager usage."""
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Match httpx.AsyncClient context-manager cleanup without side effects."""
        return None

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Record the outbound request and return the configured response."""
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_groq_provider_reports_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Groq LLM should fail clearly before any network call when the key is absent."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    response = GroqProvider().generate(
        ProviderRequest(
            provider="groq",
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "oi"}],
        )
    )

    assert response.ok is False
    assert response.error == "missing_credentials:GROQ_API_KEY"


def test_groq_provider_uses_chat_completion_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Groq LLM should build an OpenAI-compatible payload and parse the response."""
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    provider = GroqProvider()
    calls: list[dict[str, Any]] = []

    def _fake_post_chat_completion(payload: dict[str, Any]) -> dict[str, Any]:
        """Return a Groq-like completion without using the SDK or network."""
        calls.append(payload)
        return {
            "choices": [{"message": {"content": "Oi, Nakamura."}}],
            "usage": {"total_tokens": 12},
        }

    provider._custom_model_info = lambda memory, model: None  # type: ignore[method-assign]
    provider._catalog_model = lambda model: None  # type: ignore[method-assign]
    provider._tool_schemas_and_runners = lambda request, *, supports_tools: ([], {})  # type: ignore[method-assign]
    provider._post_chat_completion = _fake_post_chat_completion  # type: ignore[method-assign]

    response = provider.generate(
        ProviderRequest(
            provider="groq",
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "oi"}],
        )
    )

    assert response.ok is True
    assert response.text == "Oi, Nakamura."
    assert response.meta["provider"] == "groq"
    assert response.meta["model"] == "llama-3.3-70b-versatile"
    assert response.meta["tokens"] == 12
    assert calls[0]["model"] == "llama-3.3-70b-versatile"
    assert calls[0]["stream"] is False
    assert calls[0]["messages"][0]["role"] == "system"
    assert calls[0]["messages"][-1]["content"] == "oi"


def test_cartesia_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cartesia should report the missing CARTESIA_API_KEY explicitly."""
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)

    with pytest.raises(TTSConfigurationError, match="CARTESIA_API_KEY"):
        asyncio.run(CartesiaTTSProvider(voice=VALID_CARTESIA_VOICE).synthesize("oi"))


def test_cartesia_synthesize_with_mock_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cartesia should send sanitized text and return provider-neutral audio."""
    monkeypatch.setenv("CARTESIA_API_KEY", "test-cartesia-key")
    calls: list[dict[str, Any]] = []
    response = httpx.Response(200, content=b"cartesia-mp3")
    monkeypatch.setattr(
        cartesia_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response, calls, **kwargs),
    )

    result = asyncio.run(
        CartesiaTTSProvider(voice=VALID_CARTESIA_VOICE, speed=1.25).synthesize("Oi **Hana**")
    )

    assert result.provider == "cartesia"
    assert result.voice == VALID_CARTESIA_VOICE
    assert result.audio == b"cartesia-mp3"
    assert result.mime_type == "audio/mpeg"
    assert result.rate == "1.25"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-cartesia-key"
    assert calls[0]["json"]["transcript"] == "Oi Hana"
    assert calls[0]["json"]["voice"]["id"] == VALID_CARTESIA_VOICE
    assert calls[0]["json"]["generation_config"]["speed"] == 1.25


def test_minimax_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimax should report the missing MINIMAX_API_KEY explicitly."""
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    with pytest.raises(TTSConfigurationError, match="MINIMAX_API_KEY"):
        asyncio.run(MinimaxTTSProvider().synthesize("oi"))


def test_minimax_synthesize_with_mock_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimax should parse the non-streaming hex response into MP3 bytes."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    calls: list[dict[str, Any]] = []
    response = httpx.Response(
        200,
        json={
            "base_resp": {"status_code": 0},
            "data": {"audio": "6d7033"},
        },
    )
    monkeypatch.setattr(
        minimax_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response, calls, **kwargs),
    )

    result = asyncio.run(MinimaxTTSProvider(voice="Portuguese_ConfidentWoman").synthesize("Oi **Hana**"))

    assert result.provider == "minimax"
    assert result.audio == b"mp3"
    assert result.mime_type == "audio/mpeg"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-minimax-key"
    assert calls[0]["json"]["text"] == "Oi Hana"
    assert calls[0]["json"]["stream"] is False
    assert calls[0]["json"]["output_format"] == "hex"
    assert calls[0]["json"]["voice_setting"]["voice_id"] == "Portuguese_ConfidentWoman"
    assert calls[0]["json"]["language_boost"] == "Portuguese"


def test_elevenlabs_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """ElevenLabs should report the missing provider key before using HTTP."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    with pytest.raises(TTSConfigurationError, match="ELEVENLABS_API_KEY"):
        asyncio.run(ElevenlabsTTSProvider().synthesize("oi"))


def test_elevenlabs_synthesize_with_custom_voice_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """ElevenLabs should pass custom IDs and all supported voice controls."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    calls: list[dict[str, Any]] = []
    response = httpx.Response(200, content=b"elevenlabs-mp3")
    monkeypatch.setattr(
        elevenlabs_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response, calls, **kwargs),
    )

    result = asyncio.run(
        ElevenlabsTTSProvider(
            voice="custom-voice-id",
            model="eleven_flash_v2_5",
            language="pt-BR",
            speed=1.12,
            stability=0.42,
            similarity_boost=0.81,
            style=0.2,
            speaker_boost=False,
        ).synthesize("Oi **Hana**")
    )

    assert result.provider == "elevenlabs"
    assert result.voice == "custom-voice-id"
    assert result.audio == b"elevenlabs-mp3"
    assert calls[0]["url"].endswith("/custom-voice-id")
    assert calls[0]["headers"]["xi-api-key"] == "test-elevenlabs-key"
    assert calls[0]["params"]["output_format"] == "mp3_44100_128"
    assert calls[0]["json"]["text"] == "Oi Hana"
    assert calls[0]["json"]["model_id"] == "eleven_flash_v2_5"
    assert calls[0]["json"]["language_code"] == "pt"
    assert calls[0]["json"]["voice_settings"] == {
        "stability": 0.42,
        "similarity_boost": 0.81,
        "style": 0.2,
        "use_speaker_boost": False,
        "speed": 1.12,
    }


def test_azure_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Azure should report missing speech key env vars before calling HTTP."""
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_TTS_KEY", raising=False)

    with pytest.raises(TTSConfigurationError, match="AZURE_SPEECH_KEY"):
        asyncio.run(AzureTTSProvider().synthesize("oi"))


def test_azure_synthesize_with_mock_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Azure should send sanitized SSML content and return provider-neutral audio."""
    monkeypatch.setenv("AZURE_SPEECH_KEY", "test-azure-key")
    monkeypatch.setenv("AZURE_REGION", "brazilsouth")
    calls: list[dict[str, Any]] = []
    response = httpx.Response(200, content=b"azure-mp3")
    monkeypatch.setattr(
        azure_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response, calls, **kwargs),
    )

    result = asyncio.run(AzureTTSProvider(speed=1.2, pitch=2).synthesize("Oi & Hana"))

    assert result.provider == "azure"
    assert result.audio == b"azure-mp3"
    assert result.mime_type == "audio/mpeg"
    assert "brazilsouth.tts.speech.microsoft.com" in calls[0]["url"]
    assert calls[0]["headers"]["Ocp-Apim-Subscription-Key"] == "test-azure-key"
    ssml = calls[0]["content"].decode("utf-8")
    assert "Oi Hana" in ssml
    assert 'rate="+19%"' in ssml
    assert 'pitch="+2st"' in ssml
