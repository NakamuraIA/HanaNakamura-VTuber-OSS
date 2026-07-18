from __future__ import annotations

import asyncio

from hana_agent_oss.modules.voice.tts_fishaudio import FishAudioTTSProvider


def _collect(provider: FishAudioTTSProvider, text: str) -> list[bytes]:
    async def run() -> list[bytes]:
        return [chunk async for chunk in provider.stream_audio_chunks(text)]
    return asyncio.run(run())


def test_ws_events_shape() -> None:
    p = FishAudioTTSProvider(model="s2-pro", voice="v1", latency="low")
    events = p._ws_events("oi")
    assert events[0]["event"] == "start"
    assert events[0]["request"]["reference_id"] == "v1"
    assert events[0]["request"]["latency"] == "low"
    assert events[1] == {"event": "text", "text": "oi"}
    assert events[2]["event"] == "flush"
    assert events[3]["event"] == "stop"


def test_falls_back_to_http_when_ws_fails(monkeypatch) -> None:
    p = FishAudioTTSProvider(model="s2.1-pro-free")

    async def bad_ws(self, text):
        raise RuntimeError("modelo free nao suporta WS")
        yield b""  # torna a funcao um async generator

    async def good_http(self, text):
        yield b"AUDIO1"
        yield b"AUDIO2"

    monkeypatch.setattr(FishAudioTTSProvider, "_stream_ws_chunks", bad_ws)
    monkeypatch.setattr(FishAudioTTSProvider, "_stream_http_chunks", good_http)
    assert _collect(p, "oi") == [b"AUDIO1", b"AUDIO2"]


def test_uses_ws_when_it_works(monkeypatch) -> None:
    p = FishAudioTTSProvider(model="s2-pro")

    async def good_ws(self, text):
        yield b"WS1"
        yield b"WS2"

    async def http_should_not_run(self, text):
        raise AssertionError("HTTP nao devia rodar quando o WS funciona")
        yield b""

    monkeypatch.setattr(FishAudioTTSProvider, "_stream_ws_chunks", good_ws)
    monkeypatch.setattr(FishAudioTTSProvider, "_stream_http_chunks", http_should_not_run)
    assert _collect(p, "oi") == [b"WS1", b"WS2"]


def test_ws_disabled_uses_http(monkeypatch) -> None:
    monkeypatch.setenv("HANA_FISH_WS", "0")
    p = FishAudioTTSProvider()

    async def ws_should_not_run(self, text):
        raise AssertionError("WS desligado nao devia rodar")
        yield b""

    async def good_http(self, text):
        yield b"HTTP1"

    monkeypatch.setattr(FishAudioTTSProvider, "_stream_ws_chunks", ws_should_not_run)
    monkeypatch.setattr(FishAudioTTSProvider, "_stream_http_chunks", good_http)
    assert _collect(p, "oi") == [b"HTTP1"]
