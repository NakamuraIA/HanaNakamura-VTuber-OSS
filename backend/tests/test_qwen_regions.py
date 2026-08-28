from __future__ import annotations

from backend.api.routers.config import normalize_llm_config
from backend.providers.provider_selector.qwen.catalog import (
    QWEN_BASE_URL,
    QWEN_SINGAPORE_BASE_URL_ENV,
    qwen_base_url,
    qwen_chat_completions_url,
)
from backend.providers.provider_selector.qwen.provider import QwenProvider


class _Memory:
    def __init__(self, region: str) -> None:
        self.region = region

    def get_setting(self, key: str, default: object = None) -> object:
        return {"qwenRegion": self.region} if key == "llm_config" else default


def test_qwen_region_defaults_to_virginia() -> None:
    config = normalize_llm_config({"qwenRegion": "desconhecida"})
    assert config["qwenRegion"] == "virginia"
    assert qwen_base_url("virginia") == QWEN_BASE_URL


def test_qwen_singapore_uses_workspace_endpoint_from_environment(monkeypatch) -> None:
    endpoint = "https://workspace.ap-southeast-1.example/compatible-mode/v1"
    monkeypatch.setenv(QWEN_SINGAPORE_BASE_URL_ENV, endpoint)

    assert qwen_base_url("singapore") == endpoint
    assert qwen_chat_completions_url("singapore") == f"{endpoint}/chat/completions"


def test_qwen_provider_reads_region_from_saved_config(monkeypatch) -> None:
    endpoint = "https://workspace.ap-southeast-1.example/compatible-mode/v1"
    monkeypatch.setenv(QWEN_SINGAPORE_BASE_URL_ENV, endpoint)
    provider = QwenProvider(model_repository=object())

    assert provider._request_url(_Memory("virginia")) == f"{QWEN_BASE_URL}/chat/completions"
    assert provider._request_url(_Memory("singapore")) == f"{endpoint}/chat/completions"
