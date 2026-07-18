from __future__ import annotations

import importlib.util
import json
import logging
import math
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


logger = logging.getLogger(__name__)

# Local ONNX default (fastembed). Small, multilingual, offline after first download.
DEFAULT_EMBED_MODEL = "intfloat/multilingual-e5-small"

# Remote default (OpenRouter). text-embedding-3-small: mais rapido e estavel que
# bge-m3/qwen na medicao real (~650ms/busca), multilingue e barato ($0.02/M).
# Trocavel por HANA_MEMORY_EMBED_MODEL (ex: baai/bge-m3). Evite modelos 8B: ~12s/busca.
OPENROUTER_EMBED_URL = "https://openrouter.ai/api/v1/embeddings"
DEFAULT_OPENROUTER_EMBED_MODEL = "openai/text-embedding-3-small"


def _active_backend() -> str:
    """Which embedding backend to use: 'local' (fastembed ONNX) or 'openrouter'.

    Default 'local'. Setting HANA_MEMORY_EMBED_BACKEND=openrouter offloads the
    embedding to the OpenRouter API (zero local CPU cost — ideal em maquina fraca).
    """
    return os.environ.get("HANA_MEMORY_EMBED_BACKEND", "local").strip().lower()


@dataclass(frozen=True)
class SemanticMemoryStatus:
    """Small status payload for the optional local semantic memory layer."""

    enabled: bool
    model: str
    lazy: bool
    fastembed_available: bool
    sqlite_vec_available: bool
    openrouter_available: bool
    backend: str
    mode: str

    def to_dict(self) -> dict[str, object]:
        """Return the frontend/API shape without importing optional packages."""
        return {
            "enabled": self.enabled,
            "model": self.model,
            "lazy": self.lazy,
            "fastembedAvailable": self.fastembed_available,
            "sqliteVecAvailable": self.sqlite_vec_available,
            "openrouterAvailable": self.openrouter_available,
            "backend": self.backend,
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

    backend = "fastembed"

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


class OpenRouterEmbeddingProvider:
    """Remote embedding provider via the OpenRouter /embeddings API (OpenAI-shaped).

    Zero local CPU: a maquina fraca nao roda ONNX. Cada busca vira 1 chamada de
    rede curta. Barato ($0.01-0.02/M). Never raises inside embed() — devolve [] e
    o store cai pra FTS.
    """

    backend = "openrouter"

    def __init__(self, model: str = DEFAULT_OPENROUTER_EMBED_MODEL) -> None:
        self.model = model

    @staticmethod
    def available() -> bool:
        """True when an OpenRouter key exists (no package to install)."""
        return bool(os.environ.get("OPENROUTER_API_KEY"))

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch through OpenRouter. Preserves order via the 'index' field."""
        clean_texts = [str(text or "").strip() for text in texts if str(text or "").strip()]
        if not clean_texts:
            return []
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return []
        body = json.dumps({"model": self.model, "input": clean_texts}).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        site_url = os.environ.get("OPENROUTER_SITE_URL")
        if site_url:
            headers["HTTP-Referer"] = site_url
        headers["X-OpenRouter-Title"] = os.environ.get("OPENROUTER_APP_NAME") or "Hana Agent OSS"
        request = urllib.request.Request(OPENROUTER_EMBED_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            logger.warning("[EMBED OPENROUTER] HTTP %s: %s", exc.code, detail[:300])
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("[EMBED OPENROUTER] request failed: %s", exc)
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        ordered = sorted(data, key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0)
        vectors = [list(item.get("embedding") or []) for item in ordered if isinstance(item, dict)]
        # Só devolve se veio 1 vetor por texto; senão o indexador descarta o lote.
        return vectors if len(vectors) == len(clean_texts) else []


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


def _default_model_for(backend: str) -> str:
    """Default embedding model per backend, overridable by HANA_MEMORY_EMBED_MODEL."""
    fallback = DEFAULT_OPENROUTER_EMBED_MODEL if backend == "openrouter" else DEFAULT_EMBED_MODEL
    return os.environ.get("HANA_MEMORY_EMBED_MODEL", fallback)


def semantic_memory_status() -> SemanticMemoryStatus:
    """Build optional semantic-memory status from env and installed packages."""
    backend = _active_backend()
    model = _default_model_for(backend)
    lazy = os.environ.get("HANA_MEMORY_EMBED_LAZY", "1") != "0"
    fastembed_available = FastEmbedProvider.available()
    sqlite_vec_available = SQLiteVecIndex.available()
    openrouter_available = OpenRouterEmbeddingProvider.available()
    enabled = is_semantic_enabled()
    if not enabled:
        mode = "fts"
    elif backend == "openrouter":
        mode = "openrouter_api"
    else:
        mode = "hybrid_local"
    return SemanticMemoryStatus(
        enabled=enabled,
        model=model,
        lazy=lazy,
        fastembed_available=fastembed_available,
        sqlite_vec_available=sqlite_vec_available,
        openrouter_available=openrouter_available,
        backend=backend,
        mode=mode,
    )


def is_semantic_enabled() -> bool:
    """True only when the user opted in AND the active backend is usable.

    Default OFF. Requires HANA_MEMORY_SEMANTIC=1 plus:
    - backend 'local': fastembed instalado (paga custo ONNX na maquina).
    - backend 'openrouter': OPENROUTER_API_KEY presente (custo vai pra nuvem).
    Everything else in the store falls back to FTS when this returns False.
    """
    if os.environ.get("HANA_MEMORY_SEMANTIC", "0") != "1":
        return False
    if _active_backend() == "openrouter":
        return OpenRouterEmbeddingProvider.available()
    return FastEmbedProvider.available()


_PROVIDER_LOCK = threading.Lock()
_PROVIDER: FastEmbedProvider | OpenRouterEmbeddingProvider | None = None


def get_embedding_provider() -> FastEmbedProvider | OpenRouterEmbeddingProvider | None:
    """Return a process-wide warm embedding provider, or None when disabled.

    Picks local (fastembed ONNX) or remote (OpenRouter) per HANA_MEMORY_EMBED_BACKEND.
    Returns None (never raises) when semantic memory is off so callers degrade to FTS.
    """
    global _PROVIDER
    if not is_semantic_enabled():
        return None
    with _PROVIDER_LOCK:
        if _PROVIDER is None:
            backend = _active_backend()
            model = _default_model_for(backend)
            if backend == "openrouter":
                _PROVIDER = OpenRouterEmbeddingProvider(model=model)
            else:
                _PROVIDER = FastEmbedProvider(model=model)
        return _PROVIDER


def active_embed_model() -> str | None:
    """Model id of the active embedding provider, or None when disabled.

    Used by the store to compare a query only against stored vectors from the
    SAME model — vetores de modelos diferentes vivem em espacos diferentes e
    dariam similaridade sem sentido se misturados.
    """
    provider = get_embedding_provider()
    return provider.model if provider is not None else None


def embed_query(text: str) -> list[float] | None:
    """Embed a single search query, or None when disabled/unavailable.

    This is the only embedding call that runs inline during a turn; it is one
    short string and the model is warm after the first use. Never raises.
    """
    provider = get_embedding_provider()
    if provider is None:
        return None
    clean = str(text or "").strip()
    if not clean:
        return None
    try:
        vectors = provider.embed([clean])
    except Exception:
        return None
    return vectors[0] if vectors else None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Plain cosine similarity in [-1, 1]; 0.0 on shape mismatch or zero norm."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
