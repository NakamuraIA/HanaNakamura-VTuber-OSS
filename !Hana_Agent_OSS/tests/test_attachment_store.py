from __future__ import annotations

from hana_agent_oss.api.services import chat
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.attachments import AttachmentStore

from hana_agent_oss.providers.provider_selector.gemini_api.provider import GeminiApiProvider


class _FakePart:
    @staticmethod
    def from_bytes(*, data: bytes, mime_type: str, media_resolution=None):
        return {"kind": "bytes", "data": data, "mime_type": mime_type}


class _FakeTypes:
    Part = _FakePart


class _FakeClient:
    pass


def _data_url(mime_type: str, payload: bytes) -> str:
    import base64

    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def test_attachment_store_saves_file_and_recovers_recent(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    store = AttachmentStore(tmp_path / "attachments")
    attachment = {
        "name": "plano.pdf",
        "type": "application/pdf",
        "data": _data_url("application/pdf", b"%PDF test"),
    }

    saved = store.save_many([attachment], memory=memory, channel="control_center", user_text="o que tem nesse pdf?")
    recent = store.recent(memory, channel="control_center")

    assert saved[0]["name"] == "plano.pdf"
    assert recent[0]["name"] == "plano.pdf"
    assert recent[0]["type"] == "application/pdf"
    assert recent[0]["path"].endswith("plano.pdf")


def test_chat_resolves_only_uploaded_attachments(monkeypatch, tmp_path) -> None:
    """Uploaded attachments are persisted; nothing is auto-recovered by words."""
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    store = AttachmentStore(tmp_path / "attachments")
    monkeypatch.setattr(chat, "ATTACHMENT_STORE", store)

    first = chat.resolve_chat_attachments(
        {"attachments": [{"name": "plano.pdf", "type": "application/pdf", "data": _data_url("application/pdf", b"%PDF test")}]},
        memory=memory,
        text="analisa esse pdf",
    )
    assert first[0]["name"] == "plano.pdf"

    # A follow-up that merely MENTIONS the file must NOT pull it back (no keyword trigger).
    second = chat.resolve_chat_attachments({}, memory=memory, text="quais eram os valores do PDF?")
    assert second == []


def test_no_keyword_trigger_pulls_stored_media(monkeypatch, tmp_path) -> None:
    """Typing 'imagem'/'áudio' must never auto-attach stored media (user forbids triggers)."""
    memory = MemoryStore(tmp_path / "memory.db")
    store = AttachmentStore(tmp_path / "attachments")
    monkeypatch.setattr(chat, "ATTACHMENT_STORE", store)
    store.save_many(
        [
            {"name": "voice.mp3", "type": "audio/mpeg", "data": _data_url("audio/mpeg", b"mp3")},
            {"name": "screen.png", "type": "image/png", "data": _data_url("image/png", b"png")},
        ],
        memory=memory,
        channel="control_center",
        user_text="arquivos de teste",
    )

    assert chat.resolve_chat_attachments({}, memory=memory, text="raciocinio em cima da imagem") == []
    assert chat.resolve_chat_attachments({}, memory=memory, text="me manda o audio") == []
    assert chat.resolve_chat_attachments({}, memory=memory, text="ve se tem arquivo .py") == []


def test_gemini_attachment_parts_can_read_persisted_path(tmp_path) -> None:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF from disk")

    parts = GeminiApiProvider._attachment_parts(
        _FakeClient(),
        _FakeTypes,
        [{"name": "doc.pdf", "type": "application/pdf", "path": str(path), "size": path.stat().st_size}],
    )

    assert parts == [{"kind": "bytes", "data": b"%PDF from disk", "mime_type": "application/pdf"}]
