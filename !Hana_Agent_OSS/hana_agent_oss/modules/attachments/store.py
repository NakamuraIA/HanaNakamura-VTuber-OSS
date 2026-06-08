from __future__ import annotations

import base64
import binascii
import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hana_agent_oss.memory.store import MemoryStore


from hana_agent_oss.paths import ATTACHMENTS_DIR as DEFAULT_ATTACHMENT_ROOT
ATTACHMENT_REFERENCE_PATTERN = re.compile(
    r"\b(pdf|anexo|anexos|arquivo|documento|imagem|foto|audio|áudio|video|vídeo|planilha)\b",
    re.IGNORECASE,
)
ATTACHMENT_REFERENCE_GROUPS = {
    "image": re.compile(r"\b(imagem|foto)\b", re.IGNORECASE),
    "audio": re.compile(r"\b(audio|Ã¡udio)\b", re.IGNORECASE),
    "video": re.compile(r"\b(video|vÃ­deo)\b", re.IGNORECASE),
    "document": re.compile(r"\b(pdf|documento|planilha)\b", re.IGNORECASE),
}


def now_utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def clean_filename(name: str | None) -> str:
    value = str(name or "attachment").replace("\\", "/").split("/")[-1].strip()
    value = re.sub(r"[^\w.\- ()\[\]]+", "_", value, flags=re.UNICODE).strip(" .")
    return value[:140] or "attachment"


def decode_data_url(data_url: str) -> bytes:
    value = str(data_url or "")
    if "," in value and value.lower().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=False)
    except binascii.Error as exc:
        raise ValueError("invalid_base64_attachment") from exc


def attachment_reference_requested(text: str) -> bool:
    return bool(ATTACHMENT_REFERENCE_PATTERN.search(str(text or "")))


def attachment_reference_mime_prefixes(text: str) -> tuple[str, ...]:
    """Return MIME groups explicitly referenced by the user's current text."""
    value = str(text or "")
    prefixes: list[str] = []
    if ATTACHMENT_REFERENCE_GROUPS["image"].search(value):
        prefixes.append("image/")
    if ATTACHMENT_REFERENCE_GROUPS["audio"].search(value):
        prefixes.append("audio/")
    if ATTACHMENT_REFERENCE_GROUPS["video"].search(value):
        prefixes.append("video/")
    if ATTACHMENT_REFERENCE_GROUPS["document"].search(value):
        prefixes.extend(("application/pdf", "text/", "application/vnd."))
    return tuple(prefixes)


class AttachmentStore:
    """Persist chat attachments and expose metadata for later provider reuse."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or DEFAULT_ATTACHMENT_ROOT).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save_many(
        self,
        attachments: list[dict[str, Any]],
        *,
        memory: MemoryStore,
        channel: str,
        user_text: str,
    ) -> list[dict[str, Any]]:
        saved = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            saved.append(self.save(item, memory=memory, channel=channel, user_text=user_text))
        return saved

    def save(self, attachment: dict[str, Any], *, memory: MemoryStore, channel: str, user_text: str) -> dict[str, Any]:
        raw = decode_data_url(str(attachment.get("data") or ""))
        if not raw:
            raise ValueError("empty_attachment")

        attachment_id = str(uuid.uuid4())
        filename = clean_filename(str(attachment.get("name") or "attachment"))
        mime_type = str(attachment.get("type") or "application/octet-stream").strip() or "application/octet-stream"
        digest = hashlib.sha256(raw).hexdigest()
        folder = self.root / now_utc_slug()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{attachment_id}_{filename}"
        path.write_bytes(raw)

        metadata = {
            "attachment_id": attachment_id,
            "name": filename,
            "type": mime_type,
            "size": len(raw),
            "sha256": digest,
            "path": str(path),
            "channel": channel,
        }
        memory.add_memory(
            self._memory_text(metadata, user_text=user_text),
            kind="attachment",
            source="chat_attachment",
            metadata=metadata,
            memory_id=f"attachment:{attachment_id}",
        )
        return {
            "id": attachment_id,
            "name": filename,
            "type": mime_type,
            "size": len(raw),
            "path": str(path),
            "sha256": digest,
        }

    def recent(
        self,
        memory: MemoryStore,
        *,
        channel: str,
        limit: int = 3,
        mime_prefixes: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        """Return recent user attachments, optionally restricted to referenced MIME groups."""
        items = memory.list_memories(limit=200)
        attachments = []
        for item in items:
            metadata = item.get("metadata") or {}
            if metadata.get("kind") != "attachment" and metadata.get("source") != "chat_attachment":
                continue
            if metadata.get("channel") not in {None, channel}:
                continue
            mime_type = str(metadata.get("type") or "application/octet-stream")
            if mime_prefixes and not any(mime_type.startswith(prefix) for prefix in mime_prefixes):
                continue
            path = Path(str(metadata.get("path") or ""))
            if not path.exists() or not path.is_file():
                continue
            attachments.append(
                {
                    "id": str(metadata.get("attachment_id") or item.get("id") or ""),
                    "name": str(metadata.get("name") or path.name),
                    "type": mime_type,
                    "size": int(metadata.get("size") or path.stat().st_size),
                    "path": str(path),
                    "sha256": str(metadata.get("sha256") or ""),
                }
            )
            if len(attachments) >= limit:
                break
        return attachments

    @staticmethod
    def _memory_text(metadata: dict[str, Any], *, user_text: str) -> str:
        return (
            "Anexo salvo para consulta futura: "
            f"{metadata['name']} ({metadata['type']}, {metadata['size']} bytes). "
            f"Pergunta original: {str(user_text or '').strip()}"
        ).strip()
