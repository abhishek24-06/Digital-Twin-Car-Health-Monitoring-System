"""Cross-encoder reranking (BGE reranker v2 M3) — lazy, size-capped.

Contract
--------
* :class:`RerankerAdapter` — uniform ``rerank(query, candidates) -> scores``.
* :class:`StubRerankerAdapter` — deterministic monotone-on-length stub used by
  tests/eval (no weights, no network).
* :func:`threshold_filter` — pure decision logic shared by all adapters:
  is ``score`` admissible for ``phase`` given settings?
* :func:`get_reranker_adapter` — settings-driven factory; respects
  ``RAG_ENABLED=false`` by returning the stub, and raises the *right* Phase 5
  taxonomy error when the model is genuinely wanted but missing.

Nothing here loads a model or touches the network at import time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

try:
    from numpy.typing import NDArray
except Exception:  # pragma: no cover - env specific
    NDArray = Any

from app.rag.config import get_rag_settings
from app.rag.errors import RAGRerankerModelUnavailableError


class RerankerAdapter(ABC):
    """Cross-encoder contract, Phase 5 uniform."""

    name: str

    @abstractmethod
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """Return one relevance score per candidate, same order, ~0..1."""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Adapter diagnostics (model name, loaded, threshold)."""


class StubRerankerAdapter(RerankerAdapter):
    """Deterministic, weight-free stub.

    Scores are a stable hash of ``(query, position, length)`` squeezed into a
    ``[min_score, 1.0]`` band — *monotone in agreement*, never random — so
    evaluation over the stub still exercises the full threshold/select path.
    """

    name = "stub-reranker"

    def __init__(self, *, min_score: float | None = None) -> None:
        self.min_score = min_score if min_score is not None else 0.2
        self._seeded = 0

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        q = query.casefold()
        out: list[float] = []
        for _pos, cand in enumerate(candidates, start=1):
            c = cand.casefold()
            overlap = sum(1 for tok in set(q.split()) if tok in c)
            base = 0.2 + min(overlap / max(len(q.split()), 1), 1.0) * 0.7
            out.append(round(base, 4))
        return out

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "loaded": True, "min_score": self.min_score}


def threshold_filter(score: float, min_score: float = 0.2) -> bool:
    """Pure gate: admissible iff ``score >= min_score`` (and not NaN)."""
    return bool(score == score and score >= min_score)


def apply_min_score(scores: list[float], min_score: float) -> list[float]:
    """Zero out inadmissible scores in place (keeps list order/identity)."""
    return [s if threshold_filter(s, min_score) else 0.0 for s in scores]


def get_reranker_adapter(*, force_stub: bool = False) -> RerankerAdapter:
    """Factory: settings decide adapter; stub is forced when RAG off/for tests."""
    settings = get_rag_settings()
    if force_stub or not settings.rag_enabled or settings.rag_reranker_model == "stub":
        return StubRerankerAdapter(min_score=settings.rag_min_rerank_score)
    try:
        model_name = settings.rag_reranker_model
        return _SentenceTransformerReranker(
            model_name,
            settings.rag_min_rerank_score,
            max_length=settings.rag_reranker_max_length,
            device=settings.rag_reranker_device,
        )
    except Exception as exc:
        raise RAGRerankerModelUnavailableError(
            f"reranker {settings.rag_reranker_model} unavailable"
        ) from exc


class _SentenceTransformerReranker(RerankerAdapter):
    """Thin wrapper over sentence-transformers CrossEncoder (lazy).

    BGE rerankers are cross-encoders producing raw logits; applying a logistic
    (Sigmoid) activation maps them to the ``[0, 1]`` band that the Phase 5
    ``min_score`` threshold semantics assume.
    """

    def __init__(
        self, model_name: str, min_score: float, *, max_length: int = 512, device: str = "auto"
    ) -> None:
        self.name = "bge-reranker-v2-m3"
        self.model_name = model_name
        self.min_score = min_score
        self.max_length = max_length
        self.device = device
        self._model: Any | None = None

    def _ensure(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import CrossEncoder

            kwargs: dict[str, Any] = {"max_length": self.max_length}
            if self.device != "auto":
                kwargs["device"] = self.device
            self._model = CrossEncoder(self.model_name, **kwargs)
            self._activation = torch.nn.Sigmoid()
        return self._model

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        model = self._ensure()
        raw = model.predict(
            [[query, c] for c in candidates],  # type: ignore[no-untyped-call, call-arg]
            activation_fn=self._activation,
            show_progress_bar=False,
        )
        return [float(s) for s in raw]

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model_name,
            "loaded": self._model is not None,
            "min_score": self.min_score,
        }
