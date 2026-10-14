"""Embedding backend: lazy, size-checked, pgvector-ready (Phase 5).

Design invariants
-----------------
* **Nothing heavy at import time.** No torch, no model weights, no pgvector
  python import — this module is importable on a laptop with nothing installed.
* **Dimension is validated, never guessed.** Every embedder must declare the
  dimension it produces and the repository cross-checks it against the column
  (1024 for BGE-M3 per ``app.rag.config``). If they disagree the call fails
  with :class:`~app.rag.errors.RAGEmbeddingModelUnavailableError` rather than
  silently writing mis-cut vectors.
* **The backend is replaceable.** ``get_embedding_adapter`` returns whichever
  adapter matches config (local ``sentence-transformers``, an HTTP gateway, or
  a stub for offline/eval mode). Tests always get the deterministic stub.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from app.rag.config import get_rag_settings
from app.rag.errors import (
    RAGEmbeddingModelUnavailableError,
    RAGUnavailableErrorAlias,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - env specific
    from numpy.typing import NDArray
except Exception:  # pragma: no cover
    NDArray = Any


class EmbeddingAdapter(ABC):
    """Uniform contract for any embedding backend."""

    name: str
    dimension: int

    @abstractmethod
    def encode(self, texts: list[str], *, normalize: bool = True) -> NDArray:
        """Return a float32 array of shape ``(len(texts), dimension)``.

        Vectors are L2-normalised when ``normalize`` is true (pgvector cosine
        similarity then reduces to dot product, which keeps HNSW fast).
        """
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        """Cheap adapter diagnostics (no model load)."""
        return {"adapter": self.name, "dimension": self.dimension}


def _dimension_from_config() -> int:
    return get_rag_settings().rag_embedding_dimension


class StubEmbeddingAdapter(EmbeddingAdapter):
    """Deterministic stub for tests, evaluation, and smoke scripts.

    Produces **valid** vectors of the configured dimension from a seeded hash of
    the text. It is explicitly NOT a real embedder: used only where the contract
    matters (shape, normalisation, dimension agreement) and weights would be
    wasteful — e.g. retrieval unit tests, offline evaluation, CI.
    """

    name = "phase-5-stub"

    def __init__(self, dimension: int | None = None, *, seed: int = 0) -> None:
        self.dimension = dimension or _dimension_from_config()

    def encode(self, texts: list[str], *, normalize: bool = True) -> NDArray:
        import hashlib

        rng = None
        out = np.empty((len(texts), self.dimension), dtype=np.float32)
        for i, text in enumerate(texts):
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
            vec = rng.standard_normal(self.dimension).astype(np.float32)
            if normalize:
                vec /= np.linalg.norm(vec) + 1e-9
            out[i] = vec
        return out


class SentenceTransformerAdapter(EmbeddingAdapter):
    """Real BGE-M3 via :mod:`sentence_transformers` (lazy load).

    The model is loaded on the *first* :meth:`encode`, not at construction.
    ``device`` handling is left to sentence-transformers (auto/cuda/mps); we
    only assert the produced dimension matches config.
    """

    name = "bge-m3"

    def __init__(self, model_name: str | None = None, dimension: int | None = None) -> None:
        self.model_name = model_name or get_rag_settings().rag_embedding_model
        self.dimension = dimension or _dimension_from_config()
        self._model = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                settings = get_rag_settings()
                kwargs: dict[str, Any] = {}
                if settings.rag_embedding_device != "auto":
                    kwargs["device"] = settings.rag_embedding_device
                started = time.perf_counter()
                self._model = SentenceTransformer(self.model_name, **kwargs)
                self._model.max_seq_length = settings.rag_embedding_max_length
                logger.info(
                    "embedding weights loaded: model=%s elapsed_ms=%.0f",
                    self.model_name,
                    (time.perf_counter() - started) * 1000,
                )
            except Exception as exc:  # pragma: no cover - env specific
                raise RAGEmbeddingModelUnavailableError(
                    f"embedding model {self.model_name!r} could not load: {exc}"
                ) from exc
        return self._model

    def encode(self, texts: list[str], *, normalize: bool = True) -> NDArray:
        model = self._load()
        settings = get_rag_settings()
        try:
            vecs = model.encode(
                texts,
                batch_size=settings.rag_embedding_batch_size,
                normalize_embeddings=normalize,
                show_progress_bar=False,
            )
        except Exception as exc:  # pragma: no cover - env specific
            raise RAGEmbeddingModelUnavailableError(f"embedding encode failed: {exc}") from exc
        arr = np.asarray(vecs, dtype=np.float32)
        if arr.shape[1] != self.dimension:
            raise RAGEmbeddingModelUnavailableError(
                f"model produced dimension {arr.shape[1]} but config expects {self.dimension}"
            )
        return arr

    def health(self) -> dict[str, Any]:
        loaded = self._model is not None
        return {"adapter": self.name, "dimension": self.dimension, "loaded": loaded}


#: Process-wide adapter cache, keyed by the resolved configuration (see
#: :func:`get_embedding_adapter`).
_EMBEDDING_CACHE: dict[tuple[Any, ...], EmbeddingAdapter] = {}


def get_embedding_adapter(*, force_stub: bool = False) -> EmbeddingAdapter:
    """Return the adapter selected by configuration.

    ``force_stub`` is respected by tests/eval so deterministic vectors are
    guaranteed regardless of what ``RAG_EMBEDDING_MODEL`` says.

    Real adapters are cached process-wide by configuration, mirroring the
    reranker cache: every request builds its own ``RAGService``, so without
    this cache each query paid a full weight reload before encoding.
    """
    settings = get_rag_settings()
    if force_stub or settings.rag_embedding_model == "stub":
        key = ("stub", _dimension_from_config())
        adapter = _EMBEDDING_CACHE.get(key)
        if adapter is None:
            adapter = StubEmbeddingAdapter(dimension=_dimension_from_config())
            _EMBEDDING_CACHE[key] = adapter
        return adapter
    key = ("st", settings.rag_embedding_model, _dimension_from_config())
    adapter = _EMBEDDING_CACHE.get(key)
    if adapter is None:
        adapter = SentenceTransformerAdapter(
            model_name=settings.rag_embedding_model,
            dimension=_dimension_from_config(),
        )
        _EMBEDDING_CACHE[key] = adapter
    return adapter


__all__ = [
    "EmbeddingAdapter",
    "RAGUnavailableErrorAlias",
    "SentenceTransformerAdapter",
    "StubEmbeddingAdapter",
    "get_embedding_adapter",
]
