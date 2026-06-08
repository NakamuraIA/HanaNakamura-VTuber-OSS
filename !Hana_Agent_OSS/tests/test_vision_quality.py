from __future__ import annotations

import pytest

from hana_agent_oss.api.routers.config import normalize_portability_config
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.vision.periodic_vision import (
    DEFAULT_VISION_QUALITY_PROFILE,
    VISION_QUALITY_PROFILES,
    VisaoNyra,
    normalize_vision_quality_profile,
)
from hana_agent_oss.providers.contracts import ProviderResponse


def test_portability_config_defaults_vision_quality_profile() -> None:
    """Old portability configs remain valid and receive the full-quality default."""
    normalized = normalize_portability_config({"activeMonitor": 2})

    assert normalized["visionQualityProfile"] == DEFAULT_VISION_QUALITY_PROFILE
    assert normalized["activeMonitor"] == 2


def test_invalid_vision_quality_profile_falls_back_to_default() -> None:
    """Invalid UI or database values cannot break screen capture."""
    assert normalize_vision_quality_profile("unknown") == DEFAULT_VISION_QUALITY_PROFILE
    normalized = normalize_portability_config({"visionQualityProfile": "unknown"})

    assert normalized["visionQualityProfile"] == DEFAULT_VISION_QUALITY_PROFILE


def test_vision_quality_profiles_encode_valid_images() -> None:
    """Every profile produces bytes with the declared MIME metadata."""
    pillow = pytest.importorskip("PIL.Image")
    image = pillow.new("RGB", (2200, 1200), color=(120, 80, 200))
    vision = VisaoNyra()

    for profile_id, profile in VISION_QUALITY_PROFILES.items():
        image_bytes, metadata = vision._encode_image(image, profile_id)

        assert image_bytes
        assert metadata["profile"] == profile_id
        assert metadata["mime_type"] == profile["mime_type"]
        assert metadata["extension"] == profile["extension"]
        assert metadata["width"] <= profile["max_width"]


def test_run_text_turn_attaches_capture_with_dynamic_mime(monkeypatch, tmp_path) -> None:
    """The chat turn forwards the capture MIME type instead of forcing PNG."""
    from hana_agent_oss.api.services import chat as chat_service
    from hana_agent_oss.modules.vision import periodic_vision

    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3", events_path=tmp_path / "events.jsonl")
    memory.set_setting("connections_config", {"visao": True})
    captured = {}

    class FakeVision:
        def __init__(self, memory=None):
            self.memory = memory

        def capturar(self):
            return {
                "sucesso": True,
                "b64": "ZmFrZS1qcGc=",
                "caminho": str(tmp_path / "screen.jpg"),
                "mime_type": "image/jpeg",
                "extension": ".jpg",
                "profile": "fast_jpeg",
                "width": 1280,
                "height": 720,
            }

    def fake_provider(request):
        captured["attachments"] = request.attachments
        return ProviderResponse(ok=True, text="Vi sua tela.", meta={"nativeSearch": False})

    monkeypatch.setattr(periodic_vision, "VisaoNyra", FakeVision)
    monkeypatch.setattr(chat_service.PROVIDER_SELECTOR, "generate", fake_provider)

    result = __import__("asyncio").run(
        chat_service.run_text_turn(
            {"text": "olha minha tela", "provider": "gemini_api", "model": "gemini-3.5-flash"},
            core=object(),
            memory=memory,
        )
    )

    assert result["ok"] is True
    assert captured["attachments"][0]["name"] == "screen_capture.jpg"
    assert captured["attachments"][0]["type"] == "image/jpeg"
