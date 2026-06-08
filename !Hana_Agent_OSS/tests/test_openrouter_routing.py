from __future__ import annotations

import json

from hana_agent_oss.api.routers.config import normalize_openrouter_routing_by_model
from hana_agent_oss.providers.provider_selector.openrouter import catalog
from hana_agent_oss.providers.provider_selector.openrouter.provider import OpenRouterProvider


class _Response:
    """Minimal urllib response used by endpoint catalog tests."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_openrouter_endpoint_catalog_maps_and_caches(monkeypatch) -> None:
    calls: list[str] = []
    catalog._ENDPOINT_CACHE.clear()

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return _Response({"data": {"endpoints": [{
            "name": "DeepInfra Turbo",
            "tag": "deepinfra/turbo",
            "provider_name": "DeepInfra",
            "status": "online",
            "quantization": "fp8",
            "uptime_last_30m": 99.9,
            "supported_parameters": ["tools"],
            "pricing": {"prompt": "0.1", "completion": "0.2"},
        }]}})

    monkeypatch.setattr(catalog.urllib.request, "urlopen", fake_urlopen)
    first, error = catalog.get_openrouter_endpoints("openai/gpt-oss", force_refresh=True)
    second, _ = catalog.get_openrouter_endpoints("openai/gpt-oss")

    assert error is None
    assert first == second
    assert first[0]["slug"] == "deepinfra/turbo"
    assert first[0]["supportedParameters"] == ["tools"]
    assert len(calls) == 1


def test_openrouter_routing_normalization_rejects_unknown_fields() -> None:
    normalized = normalize_openrouter_routing_by_model({
        "openai/gpt-oss": {
            "preferredEndpoint": "DeepInfra/Turbo",
            "allowFallbacks": False,
            "requireParameters": True,
            "dataCollection": "deny",
            "zdr": True,
            "unexpected": "ignored",
        },
    })
    assert normalized["openai/gpt-oss"] == {
        "preferredEndpoint": "deepinfra/turbo",
        "allowFallbacks": False,
        "requireParameters": True,
        "dataCollection": "deny",
        "zdr": True,
    }


def test_openrouter_provider_builds_request_routing_object() -> None:
    routing = OpenRouterProvider._provider_routing_payload({
        "preferredEndpoint": "deepinfra/turbo",
        "allowFallbacks": True,
        "requireParameters": True,
        "dataCollection": "deny",
        "zdr": True,
    })
    assert routing == {
        "order": ["deepinfra/turbo"],
        "allow_fallbacks": True,
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
    }


def test_openrouter_default_routing_preserves_legacy_stream_payload() -> None:
    assert OpenRouterProvider._provider_routing_payload({
        "preferredEndpoint": "",
        "allowFallbacks": True,
        "requireParameters": False,
        "dataCollection": "allow",
        "zdr": False,
    }) == {}
