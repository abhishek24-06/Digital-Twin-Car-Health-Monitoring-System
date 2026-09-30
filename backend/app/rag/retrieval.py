"""Retrieval-stage fusion + rerank selection (pure, import-safe).

This module is the *service-level* half of hybrid retrieval: the repository
returns per-leg scores (dense/lexical/hybrid); here we apply scope tiering,
optional cross-encoder reranking, threshold filtering and the final top-k cut —
all deterministically, with no model loads and no database access.

``rerank_and_select`` is the one function the service calls; the rest are pure
helpers kept for unit testing the fusion/threshold logic.
"""

from __future__ import annotations

from app.rag.config import get_rag_settings
from app.rag.reranker.base import threshold_filter
from app.rag.schemas import RetrievedEvidence, VehicleScope
from app.rag.scope import tier_boost

TIEBREAK_EPS = 1e-9


def fusion_alpha() -> float:
    """Hybrid blend weight from settings (``RAG_HYBRID_ALPHA``)."""
    return get_rag_settings().rag_hybrid_alpha


def lexical_score(query_tokens: set[str], content: str) -> float:
    """Cheap lexical overlap score (intersection-over-query of terms)."""
    toks = {t for t in query_tokens if t}
    if not toks:
        return 0.0
    body = set(content.casefold().split())
    hits = sum(1 for t in toks if t in body)
    return hits / len(toks)


def scope_boost(chunk: RetrievedEvidence, query_scope: VehicleScope | None) -> float:
    """Additive scope-agreement boost from ``app.rag.scope.tier_boost``."""
    if not query_scope:
        return 0.0
    chunk_scope = VehicleScope(
        make=chunk.make,
        model=chunk.model,
        year=chunk.model_year_start if chunk.model_year_start == chunk.model_year_end else None,
    )
    return tier_boost(chunk_scope, query_scope)


def _apply_tier_order(
    evidence: list[RetrievedEvidence], query_scope: VehicleScope | None
) -> list[RetrievedEvidence]:
    """Re-sort stabilising on ``hybrid + scope_boost`` — never mutates input."""
    if not query_scope:
        return list(evidence)
    augmented = [(e, (e.hybrid_score or 0.0) + scope_boost(e, query_scope)) for e in evidence]
    keyed = sorted(augmented, key=lambda pair: pair[1], reverse=True)
    return [e for e, _ in keyed]


def rerank_and_select(
    evidence: list[RetrievedEvidence],
    query: str,
    reranker,
    *,
    top_k: int = 5,
    min_score: float | None = None,
    enabled: bool = True,
    query_scope: VehicleScope | None = None,
) -> list[RetrievedEvidence]:
    """Apply scope tiering, optional reranking, threshold, and the top-k cut.

    Order of operations (all scores stay on the evidence objects so the trail
    is audit-able):

    1. stabilise hybrid order with the scope tier boost,
    2. ask the reranker for one relevance score per candidate (when enabled),
    3. drop candidates below ``min_score``,
    4. keep the top ``top_k`` ordered by rerank (rerank mode) or hybrid (no
       rerank mode).

    Uses :func:`~app.rag.scope.tier_boost` semantics for step 1; scores are not
    fabricated anywhere.
    """
    if min_score is None:
        min_score = get_rag_settings().rag_min_rerank_score

    tiered = _apply_tier_order(list(evidence), query_scope)

    if enabled and reranker is not None:
        candidates = tiered[: get_rag_settings().rag_rerank_top_k]
        scores = reranker.rerank(query, [e.content for e in candidates])
        rebuilt: list[RetrievedEvidence] = []
        for ev, raw in zip(candidates, scores, strict=False):
            rebuilt.append(ev.model_copy(update={"rerank_score": float(raw)}))
        kept = [e for e in rebuilt if threshold_filter(float(e.rerank_score or 0.0), min_score)]
        selected = sorted(kept, key=lambda e: float(e.rerank_score or 0.0), reverse=True)
    else:
        kept_hybrid = [e for e in tiered if threshold_filter(e.hybrid_score or 0.0, 0.0)]
        selected = sorted(kept_hybrid, key=lambda e: e.hybrid_score or 0.0, reverse=True)

    return selected[:top_k]
