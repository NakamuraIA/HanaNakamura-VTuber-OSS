from __future__ import annotations

import os
from typing import Any

import httpx


DEFAULT_BACKEND_URL = "http://127.0.0.1:8042"


class HanaBackendClient:
    """Small async HTTP client used by Discord cogs to talk to the local Hana backend."""

    def __init__(self, backend_url: str | None = None) -> None:
        self.backend_url = str(backend_url or os.environ.get("HANA_BACKEND_URL") or DEFAULT_BACKEND_URL).rstrip("/")

    async def get_connections(self) -> dict[str, Any]:
        """Fetch persisted connection toggles from the backend."""
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(f"{self.backend_url}/api/config/conexoes")
            response.raise_for_status()
            return response.json()

    async def update_connections(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge connection toggles in the backend runtime config."""
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(f"{self.backend_url}/api/config/conexoes", json=patch)
            response.raise_for_status()
            return response.json()

    async def send_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a Discord text message to Hana and return the backend response."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.backend_url}/api/discord/message", json=payload)
            response.raise_for_status()
            return response.json()

    async def send_audio(self, audio: bytes, *, fields: dict[str, Any]) -> dict[str, Any]:
        """Send one WAV segment captured from Discord voice to the backend."""
        form_fields = {key: str(value) for key, value in fields.items() if value is not None}
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{self.backend_url}/api/discord/audio",
                data=form_fields,
                files={"audio": ("discord.wav", audio, "audio/wav")},
            )
            response.raise_for_status()
            return response.json()
