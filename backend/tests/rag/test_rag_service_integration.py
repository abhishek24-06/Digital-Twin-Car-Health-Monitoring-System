"""Phase 5 ingestion + service integration tests (stub adapters) against the
pgvector test database. Skipped when the test server has no pgvector."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.ingestion import IngestionService
from app.rag.rag_service import RAGService
from app.rag.schemas import VehicleScope

pytestmark = pytest.mark.skipif(
    not __import__("tests").conftest.supports_pgvector(),
    reason="test database lacks the pgvector extension",
)

SAMPLE = (
    "# Coolant Gauge\n"
    "If the temperature gauge enters the red zone the engine is overheating.\n"
    "# Coolant Level Check\n"
    "Check the coolant level in the reservoir between FULL and LOW.\n"
    "Top up with Toyota Super Long Life Coolant when the engine is cool.\n"
    "## Hot Cap Warning\n"
    "Never open the radiator cap while the engine is hot.\n"
)


@pytest.fixture
def sample_doc(tmp_path: Path) -> Path:
    p = tmp_path / "toyota_camry_2024.md"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


async def test_ingestion_idempotent_and_reported(session_factory, sample_doc) -> None:
    async with session_factory() as session:
        conn = await session.connection()
        service = IngestionService(stub_embeddings=True)
        first = await service.ingest(
            conn,
            sample_doc,
            canonical_source="rep://toyota-camry-2024",
            title="Toyota Camry 2024",
            make="Toyota",
            model="Camry",
            year_start=2024,
            year_end=2024,
        )
        await session.commit()
        assert first.status == "ingested"
        assert first.chunk_count >= 3
        assert first.embedding_model == "phase-5-stub"
        assert first.embedding_dimension == 1024

        second = await service.ingest(
            conn,
            sample_doc,
            canonical_source="rep://toyota-camry-2024",
            title="Toyota Camry 2024",
            make="Toyota",
            model="Camry",
            year_start=2024,
            year_end=2024,
        )
        await session.commit()
        assert second.status == "unchanged"
        assert second.version == first.version


async def test_service_grounded_guidance_roundtrip(session_factory, sample_doc) -> None:
    async with session_factory() as session:
        conn = await session.connection()
        await IngestionService(stub_embeddings=True).ingest(
            conn,
            sample_doc,
            canonical_source="rep://toyota-camry-2024",
            title="Toyota Camry 2024",
            make="Toyota",
            model="Camry",
            year_start=2024,
            year_end=2024,
        )
        service = RAGService(stub_embeddings=True, stub_rerank=True)
        result = await service.search(
            conn,
            "What should be checked when coolant temperature is high?",
            VehicleScope(make="Toyota", model="Camry", year=2024),
            top_k=3,
        )
        await session.commit()

        assert result.available is True
        assert result.guidance
        assert "[1]" in result.guidance
        assert result.citations
        assert all(c.index >= 1 for c in result.citations)
        assert result.evidence
        top = result.evidence[0]
        assert top.dense_score is not None
        assert top.rerank_score is not None
        assert result.metrics["rerank_used"] is True
        assert result.metrics["embedding_model"] == "phase-5-stub"
