"""Phase 5 RAG unit tests — pure logic, no database, no model weights.

These run on any machine (no pgvector needed) because they exercise the
deterministic layers: chunking, query planning, scope matching, embedding/rerank
stubs, parser registry, and fusion/rerank selection.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from app.rag.chunking import approx_pages, chunk_by_structure
from app.rag.embeddings import StubEmbeddingAdapter
from app.rag.parser.base import RAGParseError
from app.rag.parser.docling import DOCLING_EXTENSIONS, get_parser_for
from app.rag.parser.plain_text import parse_plain_text
from app.rag.query_builder import build_plan
from app.rag.reranker.base import StubRerankerAdapter, threshold_filter
from app.rag.retrieval import fusion_alpha, lexical_score, rerank_and_select
from app.rag.schemas import RetrievedEvidence, VehicleScope
from app.rag.scope import derive_tier, matches, tier_boost

SAMPLE = (
    "# Coolant Gauge\n"
    "The gauge needle must stay below the red zone.\n"
    "# Coolant Level Check\n"
    "Check the reservoir level between FULL and LOW when the engine is cool.\n"
    "Top up with Toyota Super Long Life Coolant.\n"
    "## Hot Refill Warning\n"
    "Never open the radiator cap while the engine is hot.\n"
)


# ---------------------------------------------------------------- chunking


def test_approx_pages_zero() -> None:
    assert approx_pages(0, 0) == (0, 0)
    assert approx_pages(0, 99, chars_per_page=100) == (1, 1)
    assert approx_pages(0, 100, chars_per_page=100) == (1, 1)
    assert approx_pages(100, 199, chars_per_page=100) == (2, 2)


def test_chunking_headings_structure_paths() -> None:
    chunks = chunk_by_structure(SAMPLE, size=800, overlap=120)
    assert chunks
    assert chunks[0].chunk_type in {"section", "preamble"}
    by_title = {c.section_title: c for c in chunks}
    assert "Coolant Gauge" in by_title
    assert "Coolant Level Check" in by_title
    nested = [c for c in chunks if c.section_title == "Hot Refill Warning"]
    assert nested and nested[0].heading_path == ["Coolant Level Check", "Hot Refill Warning"]
    assert all(c.end_char > c.start_char for c in chunks)


def test_chunking_windows_respect_size() -> None:
    long_body = "# Big Section\n" + ("A warm line of service instructions. " * 400)
    chunks = chunk_by_structure(long_body, size=800, overlap=120)
    assert len(chunks) > 1
    for c in chunks:
        assert c.start_char >= 0 and c.chunk_index == chunks.index(c)
    # Windows never exceed size + overlap; last may be shorter.
    for c in chunks:
        assert len(c.content) <= 800 + 120


def test_chunking_empty() -> None:
    assert chunk_by_structure("", size=800, overlap=120) == []


# ------------------------------------------------------------ query builder


def test_query_plan_strips_vin() -> None:
    plan = build_plan("The VIN 1FTEW1EP6LFA12345 has brake noise?")
    assert plan.detected_vin is True
    assert "1FTEW1EP6LFA12345" not in plan.text
    assert "brake noise" in plan.text
    assert any("vin" in n.casefold() for n in plan.notes)


def test_query_plan_question_mark_and_type() -> None:
    plan = build_plan("What checks when coolant high?")
    assert plan.detected_vin is False
    assert plan.lexical_variants
    assert all(v for v in plan.lexical_variants)


# ------------------------------------------------------------------- scope


def test_scope_tiers_and_matches() -> None:
    exact = VehicleScope(make="Toyota", model="Camry", year=2024)
    model = VehicleScope(make="Toyota", model="Camry")
    generic = VehicleScope()
    assert derive_tier(exact) == "EXACT_VEHICLE"
    assert derive_tier(model) == "MODEL"
    assert derive_tier(generic) == "GENERIC"
    assert matches(generic, exact)
    assert matches(model, exact)
    assert not matches(VehicleScope(make="Ford"), VehicleScope(make="Toyota"))
    assert matches(VehicleScope(year=2023), VehicleScope(year=2024)) is False
    assert tier_boost(model, exact) >= 0.15


# --------------------------------------------------------------- embeddings


def test_stub_embedding_shape_and_norm() -> None:
    adapter = StubEmbeddingAdapter(dimension=1024)
    vecs = adapter.encode(["coolant temperature", "brake pads"], normalize=True)
    assert vecs.shape == (2, 1024)
    assert vecs.dtype == np.float32
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)


# ----------------------------------------------------------------- reranker


def test_reranker_threshold_logic() -> None:
    assert threshold_filter(0.5, min_score=0.2)
    assert not threshold_filter(0.1, min_score=0.2)
    reranker = StubRerankerAdapter(min_score=0.2)
    scores = reranker.rerank("coolant", ["high coolant", "brake pads"])
    assert len(scores) == 2
    assert all(0.2 <= s <= 1.0 for s in scores)


def test_retrieval_rerank_and_select() -> None:
    base = RetrievedEvidence(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        document_version=1,
        content="high coolant temperature check the coolant level",
    )
    unrelated = base.model_copy(deep=True)
    unrelated.content = "brake pad wear inspection procedure"
    candidates = [unrelated, base]
    out = rerank_and_select(
        candidates,
        "coolant temperature",
        StubRerankerAdapter(min_score=0.2),
        top_k=2,
        min_score=0.0,
        enabled=True,
        query_scope=None,
    )
    assert out
    assert out[0].rerank_score is not None
    assert lexical_score({"coolant"}, "coolant level") == 1.0
    assert 0.0 <= fusion_alpha() <= 1.0


# ------------------------------------------------------------------ parser


def test_plain_text_sections_and_pages(tmp_path: Path) -> None:
    src = tmp_path / "manual.txt"
    src.write_text(
        "# Coolant Gauge\nRed zone = high.\n----- Page 4 -----\n# Level Check\nCheck reservoir.\n",
        encoding="utf-8",
    )
    result = parse_plain_text(src)
    assert result.content_hash
    assert result.page_count == 4
    titles = [s.heading for s in result.sections]
    assert "Coolant Gauge" in titles
    assert "Level Check" in titles
    level = next(s for s in result.sections if s.heading == "Level Check")
    assert level.page_start == 4


def test_parser_registry_routing(tmp_path: Path) -> None:
    from app.rag.parser.docling import DoclingParser
    from app.rag.parser.plain_text import PlainTextParser

    assert isinstance(get_parser_for(tmp_path / "a.pdf"), DoclingParser)
    assert isinstance(get_parser_for(tmp_path / "a.DOCX"), DoclingParser)
    assert isinstance(get_parser_for(tmp_path / "a.md"), PlainTextParser)
    assert isinstance(get_parser_for(tmp_path / "a.txt"), PlainTextParser)
    with pytest.raises(RAGParseError):
        get_parser_for(tmp_path / "a.xyz").parse(tmp_path / "a.xyz")
    assert ".pdf" in DOCLING_EXTENSIONS
