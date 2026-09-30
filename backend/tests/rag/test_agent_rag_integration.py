"""Phase 5 agent <-> RAG integration: Manufacturer Guidance Tool wired into the
LangGraph diagnosis flow against the pgvector test database.

Skipped when the test server has no pgvector extension (the Phase 3.5 safety
guard also holds: this suite only ever targets the local TEST_DATABASE_URL).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.config import AgentSettings
from app.agent.llm_service import LLMService
from app.agent.providers.mock import MockLLMProvider
from app.agent.service import AgentService
from app.models.vehicle import Vehicle
from app.rag.ingestion import IngestionService
from app.rag.rag_service import RAGService
from app.repositories.vehicle_repository import VehicleRepository

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
    p = tmp_path / "toyota_camry_2024_cooling.md"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


async def _ingest_and_vehicle(session_factory, sample_doc: Path) -> tuple[Vehicle, str]:
    async with session_factory() as session:
        conn = await session.connection()
        report = await IngestionService(stub_embeddings=True).ingest(
            conn,
            sample_doc,
            canonical_source="rep://toyota-camry-2024-cooling",
            title="Toyota Camry 2024 Cooling",
            make="Toyota",
            model="Camry",
            year_start=2024,
            year_end=2024,
            manufacturer="Toyota",
        )
        await session.commit()
        assert report.status == "ingested", report.error

        vehicle = Vehicle(
            vin=f"RAGVIN{uuid4().hex[:10].upper()}",
            make="Toyota",
            model="Camry",
            year=2024,
            engine_type="2.5L Petrol",
        )
        session.add(vehicle)
        await session.commit()
        return vehicle, report.embedding_model


async def test_agent_diagnosis_persists_rag_metadata(session_factory, sample_doc, clean_db) -> None:
    vehicle, embedding_model = await _ingest_and_vehicle(session_factory, sample_doc)

    async with session_factory() as session:
        rag = RAGService(stub_embeddings=True, stub_rerank=True, enabled=True)
        settings = AgentSettings(llm_primary_provider="mock")
        llm = LLMService(settings, primary_provider=MockLLMProvider(settings))

        svc = AgentService(session, llm_service=llm, rag_service=rag)
        response = await svc.run_user_query(
            vehicle.id, "What should be checked when coolant temperature is high?"
        )

        assert response.execution.rag_used is True
        assert response.execution.rag_evidence_count >= 1
        assert response.execution.rag_embedding_model == embedding_model
        assert response.execution.rag_scope.get("make") == "Toyota"
        # The mock provider cites source [1]; citation integrity rebuilds the
        # user-facing Citation app-side from the actual retrieved evidence.
        assert response.diagnosis.citations, "expected at least one grounded citation"
        citation = response.diagnosis.citations[0]
        assert citation.source_filename == "toyota_camry_2024_cooling.md"
        assert response.diagnosis.manufacturer_evidence, "expected bounded evidence metadata"
        assert response.diagnosis.manufacturer_evidence[0].index == 1
        assert response.diagnosis.manufacturer_guidance, (
            "expected the validated manufacturer guidance"
        )

        # Persisted record carries the same safe RAG metadata.
        record = await svc._diagnosis_repository.get_latest_by_vehicle(vehicle.id)
        assert record is not None
        assert record.rag_used is True
        assert record.rag_evidence_count >= 1
        assert record.rag_embedding_model == embedding_model
        assert record.rag_reranker_model == "stub-reranker"
        assert (record.rag_scope or {}).get("model") == "Camry"


async def test_agent_without_rag_evidence_has_no_manufacturer_claims(
    session_factory, clean_db
) -> None:
    """Negative grounding: a query with no matching corpus evidence produces a
    diagnosis with zero manufacturer guidance and zero citations."""
    async with session_factory() as session:
        vehicle = Vehicle(
            vin=f"RAGVIN{uuid4().hex[:10].upper()}",
            make="Toyota",
            model="Camry",
            year=2024,
            engine_type="2.5L Petrol",
        )
        session.add(vehicle)
        await session.commit()

        rag = RAGService(stub_embeddings=True, stub_rerank=True, enabled=True)
        settings = AgentSettings(llm_primary_provider="mock")
        llm = LLMService(settings, primary_provider=MockLLMProvider(settings))

        svc = AgentService(session, llm_service=llm, rag_service=rag)
        response = await svc.run_user_query(vehicle.id, "unrelated telemetry topic")

        assert response.execution.rag_used is False
        assert response.diagnosis.manufacturer_guidance == ""
        assert response.diagnosis.citations == []
        assert response.diagnosis.manufacturer_evidence == []

    # Vehicle lookup sanity: the repository used by the tool resolves rows.
    async with session_factory() as session:
        repo = VehicleRepository(session)
        assert await repo.get(vehicle.id) is not None
