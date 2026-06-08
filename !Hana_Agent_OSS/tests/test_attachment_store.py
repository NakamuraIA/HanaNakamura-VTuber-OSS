from __future__ import annotations

from hana_agent_oss.api.services import chat
from hana_agent_oss.memory.store import MemoryStore
from hana_agent_oss.modules.attachments import AttachmentStore, attachment_reference_mime_prefixes, attachment_reference_requested

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


def test_chat_resolves_recent_attachment_when_user_references_file(monkeypatch, tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3", tmp_path / "events.jsonl")
    store = AttachmentStore(tmp_path / "attachments")
    monkeypatch.setattr(chat, "ATTACHMENT_STORE", store)

    first = chat.resolve_chat_attachments(
        {"attachments": [{"name": "plano.pdf", "type": "application/pdf", "data": _data_url("application/pdf", b"%PDF test")}]},
        memory=memory,
        text="analisa esse pdf",
    )
    second = chat.resolve_chat_attachments({}, memory=memory, text="quais eram os valores do PDF?")

    assert first[0]["path"] == second[0]["path"]
    assert attachment_reference_requested("quais eram os valores do PDF?")


def test_attachment_reference_filters_recent_files_by_requested_type(monkeypatch, tmp_path) -> None:
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

    resolved = chat.resolve_chat_attachments({}, memory=memory, text="raciocinio em cima da imagem")

    assert attachment_reference_mime_prefixes("raciocinio em cima da imagem") == ("image/",)
    assert [item["type"] for item in resolved] == ["image/png"]


def test_attachment_reference_does_not_mix_audio_into_image_followup(monkeypatch, tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.db")
    store = AttachmentStore(tmp_path / "attachments")
    monkeypatch.setattr(chat, "ATTACHMENT_STORE", store)
    store.save_many(
        [{"name": "voice.mp3", "type": "audio/mpeg", "data": _data_url("audio/mpeg", b"mp3")}],
        memory=memory,
        channel="control_center",
        user_text="audio anterior",
    )

    resolved = chat.resolve_chat_attachments({}, memory=memory, text="ela esta boa em raciocinio em cima da imagem")

    assert resolved == []


def test_gemini_attachment_parts_can_read_persisted_path(tmp_path) -> None:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF from disk")

    parts = GeminiApiProvider._attachment_parts(
        _FakeClient(),
        _FakeTypes,
        [{"name": "doc.pdf", "type": "application/pdf", "path": str(path), "size": path.stat().st_size}],
    )

    assert parts == [{"kind": "bytes", "data": b"%PDF from disk", "mime_type": "application/pdf"}]
