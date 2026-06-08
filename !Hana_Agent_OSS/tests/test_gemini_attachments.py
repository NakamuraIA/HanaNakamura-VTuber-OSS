from __future__ import annotations

import base64

from hana_agent_oss.providers.provider_selector.gemini_api.provider import GeminiApiProvider


class _FakePart:
    @staticmethod
    def from_bytes(*, data: bytes, mime_type: str, media_resolution=None):
        return {"kind": "bytes", "data": data, "mime_type": mime_type}

    @staticmethod
    def from_uri(*, file_uri: str, mime_type: str | None = None, media_resolution=None):
        return {"kind": "uri", "file_uri": file_uri, "mime_type": mime_type}


class _FakeTypes:
    Part = _FakePart


class _FakeUploadedFile:
    name = "files/test"
    uri = "gemini://files/test"
    mime_type = "application/pdf"
    state = "ACTIVE"


class _FakeFiles:
    def __init__(self) -> None:
        self.uploads = []

    def upload(self, *, file, config):
        self.uploads.append({"file": file, "config": config})
        return _FakeUploadedFile()

    def get(self, *, name: str):
        return _FakeUploadedFile()


class _FakeClient:
    def __init__(self) -> None:
        self.files = _FakeFiles()


def _data_url(mime_type: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def test_gemini_attachment_parts_accept_inline_pdf_image_audio_video_and_text() -> None:
    attachments = [
        {"name": "doc.pdf", "type": "application/pdf", "data": _data_url("application/pdf", b"%PDF")},
        {"name": "image.png", "type": "image/png", "data": _data_url("image/png", b"png")},
        {"name": "audio.wav", "type": "audio/wav", "data": _data_url("audio/wav", b"wav")},
        {"name": "video.mp4", "type": "video/mp4", "data": _data_url("video/mp4", b"mp4")},
        {"name": "code.py", "type": "text/x-python", "data": _data_url("text/x-python", b"print('oi')")},
    ]

    parts = GeminiApiProvider._attachment_parts(_FakeClient(), _FakeTypes, attachments)

    assert [part["kind"] for part in parts] == ["bytes", "bytes", "bytes", "bytes", "bytes"]
    assert [part["mime_type"] for part in parts] == [
        "application/pdf",
        "image/png",
        "audio/wav",
        "video/mp4",
        "text/x-python",
    ]


def test_gemini_large_attachment_uses_files_api(monkeypatch) -> None:
    monkeypatch.setattr(
        "hana_agent_oss.providers.provider_selector.gemini_api.provider.INLINE_ATTACHMENT_LIMIT_BYTES",
        2,
    )
    client = _FakeClient()
    attachment = {"name": "big.pdf", "type": "application/pdf", "data": _data_url("application/pdf", b"large-pdf")}

    parts = GeminiApiProvider._attachment_parts(client, _FakeTypes, [attachment])

    assert parts == [{"kind": "uri", "file_uri": "gemini://files/test", "mime_type": "application/pdf"}]
    assert client.files.uploads[0]["config"]["mime_type"] == "application/pdf"
    assert client.files.uploads[0]["config"]["display_name"] == "big.pdf"
