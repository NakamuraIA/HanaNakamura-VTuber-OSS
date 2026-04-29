import threading
import shutil
from pathlib import Path

import pytest

import src.modules.media.media_jobs as media_jobs
from src.modules.media.media_jobs import MediaJobError, MediaJobManager, _parse_music_prompt_payload


def test_friendly_job_error_for_music_without_audio_is_not_key_blame():
    manager = MediaJobManager()

    message = manager._friendly_job_error(
        "music",
        "A resposta do Lyria nao retornou audio. Resposta textual: blocked",
    )

    assert "sem audio" in message.lower() or "sem áudio" in message.lower()
    assert "chave" not in message.lower()


def test_video_generation_jobs_are_rejected():
    manager = MediaJobManager()

    with pytest.raises(MediaJobError):
        manager.submit("video", "trailer da Hana", "test")


def test_music_prompt_payload_accepts_title_json():
    payload = _parse_music_prompt_payload('{"title":"Milene Debt Blues","prompt":"sad cinematic 90s rock"}')

    assert payload["title"] == "Milene Debt Blues"
    assert payload["prompt"] == "sad cinematic 90s rock"


def test_music_prompt_payload_extracts_title_from_text():
    payload = _parse_music_prompt_payload("Title: Hana Working Overtime\nsad cinematic 90s rock")

    assert payload["title"] == "Hana Working Overtime"
    assert "sad cinematic" in payload["prompt"]


def test_music_output_filename_uses_title(monkeypatch):
    output_dir = Path("temp") / "test_media_jobs_output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    class FakePart:
        text = ""

        class inline_data:
            data = b"audio"
            mime_type = "audio/mp3"

    class FakeContent:
        parts = [FakePart()]

    class FakeCandidate:
        content = FakeContent()

    class FakeResponse:
        candidates = [FakeCandidate()]

    class FakeModels:
        def generate_content(self, **_kwargs):
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    class FakeGenAI:
        def Client(self, **_kwargs):
            return FakeClient()

    monkeypatch.setattr(media_jobs, "get_media_settings", lambda: {
        "enabled": True,
        "music": {
            "enabled": True,
            "backend": "gemini_api",
            "model": "lyria-test",
            "output_dir": str(output_dir),
            "api_key": "fake",
        },
        "queue": {"max_concurrent_jobs": 1},
        "auto_open_terminal_outputs": False,
    })
    monkeypatch.setattr(media_jobs, "get_media_runtime_capabilities", lambda: {"music_generation_enabled": True})
    monkeypatch.setattr("google.genai.Client", FakeGenAI().Client)

    result = media_jobs._MusicGenerationBackend().generate(
        '{"title":"Milene Debt Blues","prompt":"sad cinematic 90s rock"}',
        cancel_event=threading.Event(),
    )

    assert Path(result["output_path"]).name.endswith("_music_Milene_Debt_Blues.mp3")
    assert result["details"]["title"] == "Milene Debt Blues"
    shutil.rmtree(output_dir)
