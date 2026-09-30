"""Admin RAG document lifecycle integration tests (stub embeddings/rerank).

End-to-end: multipart upload through the real service into the pgvector test
database, list/detail/search visibility, idempotent re-upload, transactional
delete, failed-ingestion rollback and temp-file hygiene. Skipped when the test
server has no pgvector (same guard as the Phase 5 integration suite).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_admin_rag_service, get_db
from app.main import app
from app.rag.admin_documents import AdminRagDocumentService
from app.rag.ingestion import IngestionReport, IngestionService
from app.rag.rag_service import RAGService
from app.rag.repository import RagRepository
from app.rag.schemas import VehicleScope

pytestmark = pytest.mark.skipif(
    not __import__("tests").conftest.supports_pgvector(),
    reason="test database lacks the pgvector extension",
)

UPLOAD_URL = "/api/v1/admin/rag/documents"
CANONICAL = "rep://toyota/camry/2024/service-manual"

SAMPLE = (
    "# Coolant Gauge\n"
    "If the temperature gauge enters the red zone the engine is overheating.\n"
    "# Coolant Level Check\n"
    "Check the coolant level in the reservoir between FULL and LOW.\n"
    "Top up with Toyota Super Long Life Coolant when the engine is cool.\n"
    "## Hot Cap Warning\n"
    "Never open the radiator cap while the engine is hot.\n"
)


async def _upload(
    client: httpx.AsyncClient, *, content: bytes = SAMPLE.encode(), filename: str = "manual.md"
) -> httpx.Response:
    return await client.post(
        UPLOAD_URL,
        files={"file": (filename, content, "text/markdown")},
        data={
            "canonical": CANONICAL,
            "make": "Toyota",
            "model": "Camry",
            "year": "2024",
        },
    )


@pytest_asyncio.fixture
async def real_admin_rag(admin_client: httpx.AsyncClient, tmp_path: Path):
    """Route the admin endpoints through a real service on the request session."""

    def _factory(session: Annotated[AsyncSession, Depends(get_db)]) -> AdminRagDocumentService:
        return AdminRagDocumentService(
            session,
            ingestion_factory=lambda: IngestionService(stub_embeddings=True),
            temp_dir=tmp_path,
        )

    app.dependency_overrides[get_admin_rag_service] = _factory
    yield admin_client, tmp_path
    app.dependency_overrides.pop(get_admin_rag_service, None)


async def test_upload_list_detail_search_delete_lifecycle(real_admin_rag, session_factory) -> None:
    admin_client, tmp_path = real_admin_rag

    uploaded = await _upload(admin_client)
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["status"] == "ingested"
    assert body["canonical"] == CANONICAL
    assert body["make"] == "Toyota"
    doc_id = body["id"]

    listed = await admin_client.get(UPLOAD_URL, params={"make": "Toyota"})
    assert listed.status_code == 200
    listed_body = listed.json()
    assert listed_body["total"] >= 1
    assert any(item["id"] == doc_id for item in listed_body["items"])

    detail = await admin_client.get(f"{UPLOAD_URL}/{doc_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["model"] == "Camry"
    assert detail_body["latest_version"]["ingestion_status"] == "completed"
    assert detail_body["latest_version"]["chunk_count"] >= 3
    assert detail_body["latest_version"]["source_filename"] == "manual.md"

    async with session_factory() as session:
        conn = await session.connection()
        evidence = await RAGService(stub_embeddings=True, stub_rerank=True).search(
            conn,
            "What should be checked when coolant temperature is high?",
            VehicleScope(make="Toyota", model="Camry", year=2024),
            top_k=5,
        )
        assert any(e.document_id == doc_id for e in evidence.evidence)

    deleted = await admin_client.delete(f"{UPLOAD_URL}/{doc_id}")
    assert deleted.status_code == 204

    assert (await admin_client.get(f"{UPLOAD_URL}/{doc_id}")).status_code == 404

    async with session_factory() as session:
        conn = await session.connection()
        repo = RagRepository(conn)
        assert await repo.get_document(CANONICAL) is None
        gone = await RAGService(stub_embeddings=True, stub_rerank=True).search(
            conn,
            "coolant level",
            VehicleScope(make="Toyota", model="Camry", year=2024),
            top_k=10,
        )
        assert not any(e.document_id == doc_id for e in gone.evidence)

    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("dtwin-rag-")]
    assert leftovers == []


async def test_duplicate_upload_returns_unchanged_same_version(real_admin_rag) -> None:
    admin_client, _ = real_admin_rag

    first = await _upload(admin_client)
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["status"] == "ingested"

    second = await _upload(admin_client)
    assert second.status_code == 201, second.text
    second_body = second.json()
    assert second_body["status"] == "unchanged"
    assert second_body["id"] == first_body["id"]
    assert second_body["version"] == first_body["version"]

    listed = await admin_client.get(UPLOAD_URL, params={"canonical": CANONICAL})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


async def test_failed_ingestion_rolls_back(admin_client, session_factory, tmp_path) -> None:
    class _FailingIngestion:
        async def ingest(self, conn, path, **kwargs) -> IngestionReport:
            return IngestionReport(
                source=str(path),
                canonical_source=kwargs["canonical_source"],
                status="failed",
                error="synthetic ingestion failure",
            )

    def _factory(session: Annotated[AsyncSession, Depends(get_db)]) -> AdminRagDocumentService:
        return AdminRagDocumentService(
            session,
            ingestion_factory=_FailingIngestion,
            temp_dir=tmp_path,
        )

    app.dependency_overrides[get_admin_rag_service] = _factory
    try:
        response = await _upload(admin_client)
        assert response.status_code == 422
        assert "synthetic ingestion failure" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_admin_rag_service, None)

    async with session_factory() as session:
        conn = await session.connection()
        assert await RagRepository(conn).get_document(CANONICAL) is None

    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("dtwin-rag-")]
    assert leftovers == []
