from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from hana_agent_oss.modules.vision.image_service import ImageGenerationService

router = APIRouter(tags=["Image Generation"])


def _service(request: Request) -> ImageGenerationService:
    """Build the image service with the app MemoryStore."""
    return ImageGenerationService(memory=request.app.state.memory)


@router.post("/api/image/generate")
async def generate_image(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Generate one image from a text prompt using Gemini Flash Image."""
    result = _service(request).generate(str(payload.get("prompt") or ""))
    return result.to_payload()


@router.post("/api/image/edit")
async def edit_image(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Edit an image from source image or image attachments."""
    result = _service(request).edit(
        str(payload.get("prompt") or ""),
        attachments=payload.get("attachments") if isinstance(payload.get("attachments"), list) else [],
        source_image=str(payload.get("sourceImage") or payload.get("source_image") or ""),
        references=payload.get("references") if isinstance(payload.get("references"), list) else [],
    )
    return result.to_payload()


@router.post("/api/image/character/generate")
async def generate_character_image(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Generate one or more registered character images."""
    result = _service(request).generate_character(
        payload,
        character_id=str(payload.get("characterId") or payload.get("character_id") or "hana"),
        mode=str(payload.get("mode") or "scene"),
        references=payload.get("references") if isinstance(payload.get("references"), list) else [],
    )
    return result.to_payload()


@router.post("/api/image/character/edit")
async def edit_character_image(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Edit one or more registered character images."""
    result = _service(request).edit_character(
        payload,
        character_id=str(payload.get("characterId") or payload.get("character_id") or "hana"),
        source_image=str(payload.get("sourceImage") or payload.get("source_image") or "latest"),
        mode=str(payload.get("mode") or "scene"),
        references=payload.get("references") if isinstance(payload.get("references"), list) else [],
        attachments=payload.get("attachments") if isinstance(payload.get("attachments"), list) else [],
    )
    return result.to_payload()
