import sys
import types

from chromadb.utils import embedding_functions

from src.brain.tool_manager import ToolManager
from src.core.provider_catalog import normalize_model_id
from src.memory.rag_engine import HanaRAGEngine
from src.utils.text import limpar_texto_tts, sanitize_visible_response_text


def test_rag_engine_fallback_roundtrip(monkeypatch, tmp_path):
    def raise_embedding_error(*_args, **_kwargs):
        raise RuntimeError("embedding unavailable for test")

    monkeypatch.setattr(
        embedding_functions,
        "SentenceTransformerEmbeddingFunction",
        raise_embedding_error,
    )

    engine = HanaRAGEngine(persist_directory=str(tmp_path / "chroma"))
    engine.upsert_memory(
        "cat-memory",
        "Meu gato Mimi dorme na janela da sala toda tarde.",
        {"source": "test"},
    )

    results = engine.query_memories("gato mimi janela", n_results=3)

    assert results
    assert any("Mimi" in item for item in results)


class _DummySnippet:
    def __init__(self, start: float, text: str):
        self.start = start
        self.text = text


class _DummyApi:
    def fetch(self, video_id, languages=None, preserve_formatting=False):
        assert video_id == "abc123xyz00"
        assert languages == ["pt", "en", "es"]
        assert preserve_formatting is False
        return [
            _DummySnippet(0.0, "linha 1"),
            _DummySnippet(3.5, "linha 2"),
        ]


def test_normalize_google_legacy_preview_model_ids():
    assert normalize_model_id("google_cloud", "gemini-3.1-pro-preview") == "gemini-3-pro-preview"
    assert normalize_model_id("google_cloud", "gemini-3.1-flash-preview") == "gemini-3-flash-preview"
    assert normalize_model_id("google_cloud", "gemini-3.1-flash-lite-preview") == "gemini-2.5-flash-lite"


def test_normalize_openrouter_invalid_flash_preview_alias():
    assert normalize_model_id("openrouter", "google/gemini-3.1-flash-preview") == "google/gemini-3-flash-preview"


def test_sanitize_visible_response_text_removes_internal_meta_checklist():
    raw = "/XML tags correct?\nYes.\n*   1 to 4 sentences max?\nPerfect.\nResposta real."

    result = sanitize_visible_response_text(raw)

    assert result == "Resposta real."


def test_sanitize_visible_response_text_removes_partial_emotion_tag():
    raw = "Texto visivel. [EMOTION:NE"

    result = sanitize_visible_response_text(raw)

    assert result == "Texto visivel."


def test_limpar_texto_tts_uses_visible_sanitizer():
    raw = "Modelos com Image. [EMOTION:NE"

    result = limpar_texto_tts(raw)

    assert result == "Modelos com Image."


def test_tool_manager_youtube_uses_fetch_api(monkeypatch):
    fake_module = types.SimpleNamespace(YouTubeTranscriptApi=lambda: _DummyApi())
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_module)

    manager = ToolManager(memory_manager=None)
    contexto, resumo = manager.executar_tool("analisar_youtube", {"url": "https://youtu.be/abc123xyz00"})

    assert "TRANSCRICAO YOUTUBE (abc123xyz00)" in contexto
    assert "[0.0s] linha 1" in contexto
    assert "[3.5s] linha 2" in contexto
    assert "transcricao do video inteiro" in resumo.lower()
