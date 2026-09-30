"""Phase 5 repository integration tests against the pgvector test database.

Skipped entirely when the local test server cannot host the pgvector
extension (see ``tests.conftest.supports_pgvector``).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.rag.embeddings import StubEmbeddingAdapter
from app.rag.repository import ChunkRow, RagRepository
from app.rag.schemas import VehicleScope

pytestmark = pytest.mark.skipif(
    not __import__("tests").conftest.supports_pgvector(),
    reason="test database lacks the pgvector extension",
)


async def _seed(
    repo: RagRepository,
    *,
    make: str | None = "Toyota",
    model: str | None = "Camry",
    year: int | None = 2024,
) -> tuple[object, object]:
    doc_id = uuid4()
    version_id = uuid4()
    await repo.upsert_document(
        doc_id,
        "rep://toyota-camry-2024",
        title="Toyota Camry 2024 Service Manual",
        manufacturer="Toyota",
        make=make,
        model=model,
        year_start=year,
        year_end=year,
        document_type="service-manual",
    )
    await repo.insert_version(
        version_id,
        doc_id,
        version=1,
        content_hash="abc123",
        source_filename="toyota_camry_2024.md",
        parser_name="plain-text",
        parser_version="1.0.0",
        language="en",
        page_count=4,
        embedding_model="test-adapter",
        embedding_dimension=1024,
        chunking_version="structural-1.0.0",
    )
    adapter = StubEmbeddingAdapter(dimension=1024)
    vector = adapter.encode(["check coolant level when the engine is hot"], normalize=True)[0]
    await repo.insert_chunk(
        ChunkRow(
            chunk_id=uuid4(),
            document_version_id=version_id,
            chunk_index=0,
            chunk_type="section",
            title="Coolant Level Check",
            section_title="Coolant Level Check",
            heading_path=["Coolant Level Check"],
            page_start=2,
            page_end=2,
            start_char=0,
            end_char=80,
            content="check coolant level when the engine is hot; do not open the radiator cap",
            scope_make=make,
            scope_model=model,
            scope_year=year,
        ),
        vector,
    )
    await repo.complete_version(version_id)
    return doc_id, version_id


async def test_repository_roundtrip_hybrid(session_factory) -> None:
    async with session_factory() as session:
        conn = await session.connection()
        repo = RagRepository(conn)
        doc_id, version_id = await _seed(repo)
        adapter = StubEmbeddingAdapter(dimension=1024)
        qvec = adapter.encode(["coolant level check when hot"], normalize=True)[0]

        hits = await repo.hybrid_search(
            "coolant level",
            qvec,
            top_k=5,
            vehicle_scope=VehicleScope(make="Toyota", model="Camry", year=2024),
        )
        await session.commit()

        assert len(hits) == 1
        ev = hits[0]
        assert ev.document_id == doc_id
        assert ev.document_version_id == version_id
        assert ev.document_version == 1
        assert ev.title == "Toyota Camry 2024 Service Manual"
        assert ev.source_filename == "toyota_camry_2024.md"
        assert ev.section_title == "Coolant Level Check"
        assert ev.scope == "EXACT_VEHICLE"
        assert ev.dense_score is not None
        assert ev.lexical_score is not None and ev.lexical_score > 0
        assert ev.hybrid_score is not None


async def test_repository_scope_contradiction_filters(session_factory) -> None:
    async with session_factory() as session:
        conn = await session.connection()
        repo = RagRepository(conn)
        await _seed(repo)
        adapter = StubEmbeddingAdapter(dimension=1024)
        qvec = adapter.encode(["coolant level"], normalize=True)[0]

        hits = await repo.hybrid_search(
            "coolant level",
            qvec,
            top_k=5,
            vehicle_scope=VehicleScope(make="Ford", model="F-150", year=2023),
        )
        await session.commit()
        assert hits == []


async def test_repository_health(session_factory) -> None:
    async with session_factory() as session:
        conn = await session.connection()
        repo = RagRepository(conn)
        await _seed(repo)
        health = await repo.health()
        await session.commit()
        assert health["pgvector_available"] is True
        assert health["corpus"]["documents"] == 1
        assert health["corpus"]["completed_chunks"] == 1
