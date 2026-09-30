"""Vehicle-scope derivation + matching (pure, no I/O).

Phase 5 is *vehicle-aware retrieval*: every chunk carries a scope and every
query is matched against the caller's vehicle. The scope is **never invented** —
``None`` means "not constrained". The tier of a scope is the strongest
statement it can truthfully make, and matching is conservative: a chunk is only
withheld when the query *proves* it cannot apply.

Tiers (strongest → weakest)::

    EXACT_VEHICLE  make + model + a single year
    MODEL          make + model
    MAKE           make only
    GENERIC        anything else

A chunk whose tier is *stronger* than the query's tier is always admissible
(a MODEL manual is valid evidence for a small repair on that model); a chunk is
only dropped when it *contradicts* the query.
"""

from __future__ import annotations

from app.rag.schemas import VehicleScope

ScopeTier = str  # one of "GENERIC" | "MAKE" | "MODEL" | "EXACT_VEHICLE"

SCOPE_TIER_ORDER: dict[str, int] = {
    "GENERIC": 0,
    "MAKE": 1,
    "MODEL": 2,
    "EXACT_VEHICLE": 3,
}


def derive_tier(scope: VehicleScope) -> str:
    """Return the strongest tier *provably* supported by ``scope``.

    ``None`` on any axis means "no claim", so an exact tier requires make,
    model *and* a concrete year to be present together.
    """
    if scope and scope.make and scope.model and scope.year:
        return "EXACT_VEHICLE"
    if scope and scope.make and scope.model:
        return "MODEL"
    if scope and scope.make:
        return "MAKE"
    return "GENERIC"


def tier_rank(tier: str) -> int:
    """Map a tier name to a comparable integer (unknown tiers == GENERIC)."""
    return SCOPE_TIER_ORDER.get(tier, 0)


def matches(chunk_scope: VehicleScope | None, query_scope: VehicleScope | None) -> bool:
    """Hard filter: can ``chunk_scope`` serve ``query_scope``?

    A chunk is kept unless the query *positively contradicts* it:

    * if the chunk names a make/model and the query names a *different*
      make/model -> drop (unless the chunk is generic enough to still apply).
    * if the chunk pins an engine and the query pins a *different* engine -> drop.
    * if the chunk pins a year and the query pins a *different* year -> drop.
    * any ``None`` side never contradicts.
    """
    if not chunk_scope or not query_scope:
        return True  # either side is unconstrained

    # Generic chunk (no constraining claims) always serves.
    chunk_specific = chunk_scope.make or chunk_scope.model or chunk_scope.engine or chunk_scope.year
    if not chunk_specific:
        return True

    # A chunk that is MORE specific than the query is fine (MODEL manual for a
    # generic query); only contradictions drop it.
    if chunk_scope.make and query_scope.make and chunk_scope.make != query_scope.make:
        return False
    if chunk_scope.model and query_scope.model and chunk_scope.model != query_scope.model:
        return False
    if (
        chunk_scope.engine
        and query_scope.engine
        and chunk_scope.engine.lower() != query_scope.engine.lower()
    ):
        return False
    if chunk_scope.year and query_scope.year and chunk_scope.year != query_scope.year:
        return False
    return True


def tier_boost(chunk_scope: VehicleScope | None, query_scope: VehicleScope | None) -> float:
    """Small additive score bonus for scope agreement (hybrid fusion bias).

    Returns a value in ``[0.0, 0.30]``. Only makes *stronger* claims when both
    sides agree on a concrete axis; agreement between two EXACT_VEHICLE scopes
    on make+model-year scores highest.
    """
    if not chunk_scope or not query_scope:
        return 0.0
    if not (chunk_scope.make and query_scope.make):
        return 0.0

    points = 0.0
    if chunk_scope.make == query_scope.make:
        points += 0.10
        if chunk_scope.model and query_scope.model and chunk_scope.model == query_scope.model:
            points += 0.15
            if chunk_scope.year and query_scope.year and chunk_scope.year == query_scope.year:
                points += 0.05
    return min(points, 0.30)
