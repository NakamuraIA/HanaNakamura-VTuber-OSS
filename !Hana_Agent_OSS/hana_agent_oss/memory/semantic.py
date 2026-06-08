from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Protocol


DEFAULT_EMBED_MODEL = "intfloat/multilingual-e5-small"


@dataclass(frozen=True)
class SemanticMemoryStatus:
    """Small status payload for the optional local semantic memory layer."""

    enabled: bool
    model: str
    lazy: bool
    fastembed_available: bool
    sqlite_vec_available: bool
    mode: str

    def to_dict(self) -> dict[str, object]:
        """Return the frontend/API shape without importing optional packages."""
        return {
            "enabled": self.enabled,
            "model": self.model,
            "lazy": self.lazy,
            "fastembedAvailable": self.fastembed_available,
            "sqliteVecAvailable": self.sqlite_vec_available,
            "mode": self.mode,
        }


class EmbeddingProvider(Protocol):
    """Protocol implemented by lazy local embedding providers."""

    model: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed text batches for background indexing, never inline TTS turns."""
        ...


class FastEmbedProvider:
    """Lazy ONNX embedding provider used only when semantic memory is enabled."""

    def __init__(self, model: str = DEFAULT_EMBED_MODEL) -> None:
        self.model = model
        self._model = None

    @staticmethod
    def available() -> bool:
        """Check whether fastembed is installed without importing the runtime."""
        return importlib.util.find_spec("fastembed") is not None

    def _load(self):
        """Load FastEmbed only when a background indexing job actually needs it."""
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for a batch using FastEmbed's local ONNX runtime."""
        clean_texts = [str(text or "").strip() for text in texts if str(text or "").strip()]
        if not clean_texts:
            return []
        return [list(vector) for vector in self._load().embed(clean_texts)]


class VectorIndex(Protocol):
    """Protocol for SQLite-backed vector index implementations."""

    def available(self) -> bool:
        """Return whether the vector extension is usable in this runtime."""
        ...


class SQLiteVecIndex:
    """Availability wrapper for sqlite-vec; actual indexing stays lazy/background."""

    @staticmethod
    def available() -> bool:
        """Check sqlite-vec without loading an extension or touching the DB."""
        return importlib.util.find_spec("sqlite_vec") is not None


def semantic_memory_status() -> SemanticMemoryStatus:
    """Build optional semantic-memory status from env and installed packages."""
    enabled = os.environ.get("HANA_MEMORY_SEMANTIC", "0") == "1"
    model = os.environ.get("HANA_MEMORY_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    lazy = os.environ.get("HANA_MEMORY_EMBED_LAZY", "1") != "0"
    fastembed_available = FastEmbedProvider.available()
    sqlite_vec_available = SQLiteVecIndex.available()
    mode = "hybrid_optional" if enabled and fastembed_available and sqlite_vec_available else "fts"
    return SemanticMemoryStatus(
        enabled=enabled,
        model=model,
        lazy=lazy,
        fastembed_available=fastembed_available,
        sqlite_vec_available=sqlite_vec_available,
        mode=mode,
    )
