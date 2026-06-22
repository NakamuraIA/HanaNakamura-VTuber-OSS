from __future__ import annotations

import os
from typing import Any

import httpx


DEFAULT_BACKEND_URL = "http://127.0.0.1:8042"


class HanaBackendClient:
    """Small async HTTP client used by Discord cogs to talk to the local Hana backend."""

    def __init__(self, backend_url: str | None = None) -> None:
        self.backend_url = str(backend_url or os.environ.get("HANA_BACKEND_URL") or DEFAULT_BACKEND_URL).rstrip("/")

    async def send_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a Discord text message to Hana and return the backend response."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.backend_url}/api/discord/message", json=payload)
            response.raise_for_status()
            return response.json()

    async def generate_image(self, prompt: str) -> dict[str, Any]:
        """Ask the backend to generate one image from a text prompt."""
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{self.backend_url}/api/image/generate", json={"prompt": prompt})
            response.raise_for_status()
            return response.json()

    async def edit_image(self, prompt: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
        """Ask the backend to edit an image given base64 attachments."""
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{self.backend_url}/api/image/edit",
                json={"prompt": prompt, "attachments": attachments},
            )
            response.raise_for_status()
            return response.json()

    async def fetch_media_bytes(self, url_or_path: str) -> bytes:
        """Download generated media bytes from a backend media URL (e.g. /api/media/image/x.png)."""
        url = url_or_path if url_or_path.startswith("http") else f"{self.backend_url}{url_or_path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

    async def get_discord_outbox(self) -> dict[str, Any]:
        """Fetch pending DMs Hana queued for the owner (ownerId + pending list)."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.backend_url}/api/discord/outbox")
            response.raise_for_status()
            return response.json()

    async def mark_discord_delivered(self, ids: list[str]) -> dict[str, Any]:
        """Tell the backend which outbox entries were delivered, so they don't repeat."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.backend_url}/api/discord/outbox/delivered", json={"ids": ids})
            response.raise_for_status()
            return response.json()
