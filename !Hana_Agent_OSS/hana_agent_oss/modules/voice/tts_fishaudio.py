"""Fish Audio TTS provider for the Hana OSS voice runtime.

REST API used directly (no official SDK dependency), same pattern as the
ElevenLabs provider. Fish Audio offers a genuinely free tier (``s2.1-pro-free``)
plus paid tiers (``s2.1-pro``, ``s2-pro``, ``s1``) that are cheaper than
ElevenLabs -- good for testing/streamer-mode without burning ElevenLabs credits.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from hana_agent_oss.modules.voice.tts_edge import EdgeTTSResult, TTSConfigurationError
from hana_agent_oss.modules.voice.tts_readable import sanitize_tts_text

logger = logging.getLogger(__name__)

FISHAUDIO_TTS_URL = "https://api.fish.audio/v1/tts"
# WebSocket bidirecional (menor latencia). A doc oficial diz "so modelos pagos",
# mas teste ao vivo provou que o s2.1-pro-free FUNCIONA no WS. Se algum modelo
# nao rolar, cai pro HTTP via fallback. Desligavel com HANA_FISH_WS=0.
FISHAUDIO_WS_URL = "wss://api.fish.audio/v1/tts/live"
FISHAUDIO_API_KEY_ENV = "FISH_API_KEY"
DEFAULT_FISHAUDIO_MODEL = "s2.1-pro-free"
DEFAULT_FISHAUDIO_VOICE = ""
FISHAUDIO_TTS_MODELS = (
    "s2.1-pro-free",
    "s2.1-pro",
    "s2-pro",
    "s1",
)
FISHAUDIO_TTS_MIME = "audio/mpeg"
FISHAUDIO_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class FishAudioTTSProvider:
    """Generate speech via the Fish Audio REST API (free + paid tiers)."""

    voice: str = DEFAULT_FISHAUDIO_VOICE
    model: str = DEFAULT_FISHAUDIO_MODEL
    speed: float = 1.0
    # latency: "normal" (melhor qualidade), "balanced" ou "low" (menor time-to-first-audio,
    # ideal pro modo streamer). Streaming usa "balanced" por padrao pra cortar latencia.
    latency: str = "balanced"

    async def synthesize(self, text: str) -> EdgeTTSResult:
        """Generate audio bytes via Fish Audio TTS REST API (buffered, non-stream)."""
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise ValueError("TTS text is empty after sanitization.")

        headers = self._headers()
        payload = self._build_payload(clean_text)

        async with httpx.AsyncClient(timeout=FISHAUDIO_TIMEOUT_SECONDS) as client:
            response = await client.post(FISHAUDIO_TTS_URL, headers=headers, json=payload)

        if response.status_code >= 400:
            raise TTSConfigurationError(f"Fish Audio TTS failed: {_response_error(response)}")

        audio = response.content
        if not audio:
            raise TTSConfigurationError("Fish Audio TTS returned empty audio.")

        return self._result(clean_text, audio)

    async def stream_audio_chunks(self, text: str):
        """Yield MP3 chunks as they arrive: tenta WebSocket (menor latencia) e cai
        pro HTTP se o WS nao rolar (ex: modelo free nao suportado).

        O fallback so acontece ANTES do 1o chunk (peek): se o WS ja comecou a
        mandar audio e depois quebrar, propaga o erro (o runtime entao volta pro
        playback por arquivo), pra nunca tocar audio duplicado.
        """
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            return

        if self._ws_enabled():
            agen = self._stream_ws_chunks(clean_text)
            try:
                first = await agen.__anext__()
            except StopAsyncIteration:
                return  # WS ok, mas sem audio
            except Exception as exc:  # noqa: BLE001 - qualquer falha de WS -> HTTP
                logger.info("[FISH WS] indisponivel (%s); usando streaming HTTP.", exc)
            else:
                yield first
                async for chunk in agen:
                    yield chunk
                return

        async for chunk in self._stream_http_chunks(clean_text):
            yield chunk

    async def _stream_http_chunks(self, clean_text: str):
        """Streaming via HTTP chunked (funciona em qualquer modelo, inclusive free)."""
        headers = self._headers()
        payload = self._build_payload(clean_text)
        async with httpx.AsyncClient(timeout=FISHAUDIO_TIMEOUT_SECONDS) as client:
            async with client.stream("POST", FISHAUDIO_TTS_URL, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    detail = body.decode("utf-8", errors="replace")[:400] if body else f"HTTP {response.status_code}"
                    raise TTSConfigurationError(f"Fish Audio TTS streaming failed: {detail}")
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk

    async def _stream_ws_chunks(self, clean_text: str):
        """Streaming via WebSocket bidirecional (MessagePack). Menor latencia.

        Manda o texto completo (o runtime ja entrega a resposta pronta) + flush +
        stop, e devolve os ChunkEvents de audio conforme chegam. Levanta em
        qualquer erro pra o chamador decidir o fallback.
        """
        import msgpack  # noqa: PLC0415 - lazy: so quando o WS e usado
        import websockets  # noqa: PLC0415

        api_key = os.environ.get(FISHAUDIO_API_KEY_ENV)
        if not api_key:
            raise TTSConfigurationError(f"{FISHAUDIO_API_KEY_ENV} ausente.")
        model_id = str(self.model or DEFAULT_FISHAUDIO_MODEL).strip() or DEFAULT_FISHAUDIO_MODEL
        headers = {"Authorization": f"Bearer {api_key}", "model": model_id}

        async with websockets.connect(
            FISHAUDIO_WS_URL, additional_headers=headers, max_size=None, open_timeout=10
        ) as ws:
            for event in self._ws_events(clean_text):
                await ws.send(msgpack.packb(event, use_bin_type=True))
            async for message in ws:
                data = msgpack.unpackb(message, raw=False)
                event = data.get("event") if isinstance(data, dict) else None
                if event == "audio":
                    audio = data.get("audio")
                    if audio:
                        yield bytes(audio)
                elif event == "finish":
                    if str(data.get("reason") or "").lower() == "error":
                        raise TTSConfigurationError(f"Fish WS finish com erro: {data}")
                    return

    def _ws_events(self, clean_text: str) -> list[dict[str, Any]]:
        """Sequencia de eventos client->server do WebSocket (puro, testavel)."""
        latency = str(self.latency or "balanced").strip().lower()
        if latency not in {"low", "normal", "balanced"}:
            latency = "balanced"
        request: dict[str, Any] = {
            "text": "",
            "format": "mp3",
            "mp3_bitrate": 128,
            "latency": latency,
            "prosody": {"speed": max(0.5, min(2.0, float(self.speed)))},
        }
        voice_id = str(self.voice or "").strip()
        if voice_id:
            request["reference_id"] = voice_id
        return [
            {"event": "start", "request": request},
            {"event": "text", "text": clean_text},
            {"event": "flush"},
            {"event": "stop"},
        ]

    @staticmethod
    def _ws_enabled() -> bool:
        """WebSocket ligado por padrao; HANA_FISH_WS=0 forca so HTTP."""
        return os.environ.get("HANA_FISH_WS", "1").strip().lower() not in {"0", "false", "no"}

    def _headers(self) -> dict[str, str]:
        api_key = os.environ.get(FISHAUDIO_API_KEY_ENV)
        if not api_key:
            raise TTSConfigurationError(
                f"{FISHAUDIO_API_KEY_ENV} is required for Fish Audio TTS. "
                "Get your API key at https://fish.audio/app/developers/"
            )
        model_id = str(self.model or DEFAULT_FISHAUDIO_MODEL).strip() or DEFAULT_FISHAUDIO_MODEL
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "model": model_id,
        }

    def _build_payload(self, clean_text: str) -> dict[str, Any]:
        latency = str(self.latency or "balanced").strip().lower()
        if latency not in {"low", "normal", "balanced"}:
            latency = "balanced"
        payload: dict[str, Any] = {
            "text": clean_text,
            "format": "mp3",
            "mp3_bitrate": 128,
            "latency": latency,
            "prosody": {"speed": max(0.5, min(2.0, float(self.speed)))},
        }
        voice_id = str(self.voice or "").strip()
        if voice_id:
            payload["reference_id"] = voice_id
        return payload

    def _result(self, text: str, audio: bytes) -> EdgeTTSResult:
        return EdgeTTSResult(
            provider="fishaudio",
            voice=str(self.voice or "default"),
            rate=str(self.speed),
            pitch="default",
            volume="default",
            text=text,
            audio=audio,
            mime_type=FISHAUDIO_TTS_MIME,
        )


def _response_error(response: httpx.Response) -> str:
    """Compact error without leaking full key material."""
    try:
        data = response.json()
    except Exception:
        return response.text[:400] or f"HTTP {response.status_code}"
    if isinstance(data, dict):
        err = data.get("detail") or data.get("error") or data.get("message") or data
        if isinstance(err, dict):
            return str(err.get("message") or err)[:400]
        return str(err)[:400]
    return str(data)[:400]
