"""Manufacturer citation validation for agent output (Phase 5).

The LLM never invents titles, page ranges, or document ids. It may only emit
``cited_sources`` — 1-based indexes into the source list that the supervisor
supplied. This module rebuilds the user-facing :class:`~app.rag.schemas.Citation`
objects app-side from the *actual* retrieved evidence, dropping out-of-range or
duplicate references and recording every drop as a validation warning so
operations can see how far the model stayed on-rails.

This is also the negative-grounding gate: when no manufacturer evidence was
retrieved, *no* citation can be valid and any synthesized guidance must be
removed.
"""

from __future__ import annotations

from app.rag.schemas import Citation


def build_citations_from_sources(
    cited_sources: list[int],
    evidence: list[dict],
    *,
    start_index: int = 1,
) -> tuple[list[Citation], list[str]]:
    """Map the model's ``cited_sources`` refs onto real evidence items.

    Evidence items are the JSON shapes produced by the Manufacturer Guidance
    Tool (each carrying ``index``, provenance and section/page). Only refs that
    resolve to a real, present item become citations; every dropped ref is
    reported as a validation warning.
    """
    if not cited_sources or not evidence:
        return [], []

    by_index = {item.get("index"): item for item in evidence}
    citations: list[Citation] = []
    warnings: list[str] = []
    seen: set[int] = set()

    for ref in cited_sources:
        item = by_index.get(ref)
        if item is None:
            warnings.append(f"Citation source [{ref}] dropped: no matching retrieved source")
            continue
        if ref in seen:
            warnings.append(f"Citation source [{ref}] dropped: duplicate reference")
            continue
        seen.add(ref)
        citations.append(
            Citation(
                index=start_index + len(citations),
                document_id=item.get("document_id"),
                document_version_id=item.get("document_version_id"),
                document_version=item.get("document_version"),
                chunk_id=item.get("chunk_id"),
                source_filename=item.get("source_filename"),
                title=item.get("title") or "",
                section_title=item.get("section_title") or "",
                page_start=item.get("page_start"),
                page_end=item.get("page_end"),
            )
        )
    return citations, warnings
