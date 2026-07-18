from __future__ import annotations

import base64
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

    async def synthesize_speech(self, text: str) -> bytes | None:
        """Pede o áudio TTS da resposta da Hana usando o perfil de "TTS do Chat".

        Devolve os bytes do áudio (mp3/wav) ou None se vier vazio. Usado pela voz do
        Discord pra tocar a fala dela. useChatTts=True faz o backend usar a voz do
        Chat do Controle (llm_config), nao a do Terminal Agente.
        """
        clean = str(text or "").strip()
        if not clean:
            return None
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.backend_url}/api/voice/tts/synthesize",
                json={"text": clean, "useChatTts": True},
            )
            response.raise_for_status()
            data = response.json()
        b64 = data.get("audioBase64")
        return base64.b64decode(b64) if b64 else None

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

    # --- Config (usado pelo /provider e /status) --------------------------- #
    # Todos os POST de config no backend fazem merge/PATCH: mandar so os campos
    # que mudam. Config aplica na hora (todo turno le memory.get_setting fresco).

    async def get_catalog(self) -> dict[str, Any]:
        """Fetch the model catalog (llmProviders, models, imageProviders, imageModels)."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{self.backend_url}/api/catalog")
            response.raise_for_status()
            return response.json()

    async def get_chat_config(self) -> dict[str, Any]:
        """Read the chat config (provider/model usados pelo turno do Discord)."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.backend_url}/api/config/chat")
            response.raise_for_status()
            return response.json()

    async def update_chat_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Merge-patch the chat config (ex: {'provider','model'})."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.backend_url}/api/config/chat", json=payload)
            response.raise_for_status()
            return response.json()

    async def get_llm_config(self) -> dict[str, Any]:
        """Read the full LLM config (llmProvider/Model, agentProvider/Model, visionModel...)."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.backend_url}/api/config/llm")
            response.raise_for_status()
            return response.json()

    async def update_llm_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Merge-patch the LLM config (ex: {'agentProvider','agentModel'})."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.backend_url}/api/config/llm", json=payload)
            response.raise_for_status()
            return response.json()

    async def get_image_config(self) -> dict[str, Any]:
        """Read the image-generation config (imageProvider, openrouterImageModel)."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.backend_url}/api/config/image")
            response.raise_for_status()
            return response.json()

    async def update_image_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Merge-patch the image config (ex: {'imageProvider','openrouterImageModel'})."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.backend_url}/api/config/image", json=payload)
            response.raise_for_status()
            return response.json()
