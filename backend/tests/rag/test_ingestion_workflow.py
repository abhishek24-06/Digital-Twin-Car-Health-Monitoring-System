"""Ingestion workflow instrumentation tests (hermetic: no database).

Every ingestion event must carry the document id once the document row
exists, and one ingestion operation must share a single correlation id so the
Admin RAG page can follow that upload end-to-end. The real ``ingest`` pipeline
is driven with a stub parser and an in-memory repository so the instrumentation
is exercised without requiring pgvector.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from app.rag.admin_documents import _to_upload_response
from app.rag.ingestion import IngestionReport, IngestionService
from app.schemas.rag import AdminRagDocumentUploadForm, AdminRagUploadResponse
from app.schemas.workflow import WorkflowStage, WorkflowType

SAMPLE = (
    "# Coolant Gauge\n"
    "If the temperature gauge enters the red zone the engine is overheating.\n"
    "# Coolant Level Check\n"
    "Check the coolant level in the reservoir between FULL and LOW.\n"
    "# Brake Fluid\n"
    "Check the brake fluid level in the master cylinder reservoir.\n"
)

POST_DOCUMENT_STAGES = {
    WorkflowStage.CHUNKING_STARTED,
    WorkflowStage.CHUNKS_CREATED,
    WorkflowStage.METADATA_ATTACHED,
    WorkflowStage.EMBEDDING_STARTED,
    WorkflowStage.EMBEDDINGS_GENERATED,
    WorkflowStage.VECTOR_STORAGE_STARTED,
    WorkflowStage.CHUNKS_STORED,
    WorkflowStage.INDEX_READY,
    WorkflowStage.INGESTION_COMPLETED,
}


class _ParseResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content_hash = ""
        self.page_count = 1
        self.pages = [text]


class _StubParser:
    name = "stub-parser"
    version = "1.0.0"

    def parse(self, path: Path) -> _ParseResult:
        return _ParseResult(SAMPLE)


class _FakeRepo:
    """In-memory stand-in for ``RagRepository`` (ingestion-relevant surface).

    State is shared across instances because ``ingest`` builds a fresh
    repository per call but the pipeline must observe prior versions (that is
    what makes the idempotent "unchanged" path reachable).
    """

    documents: dict = {}
    versions: dict = {}

    def __init__(self, conn) -> None:
        self.conn = conn

    async def get_document(self, canonical_source: str):
        return self.documents.get(canonical_source)

    async def upsert_document(self, doc_id: UUID, canonical_source: str, **cols):
        self.documents[canonical_source] = {"id": doc_id, **cols}
        return doc_id

    async def latest_version(self, doc_id: UUID):
        versions = [v for v in self.versions.values() if v["document_id"] == doc_id]
        if not versions:
            return None
        return max(versions, key=lambda v: v["version"])

    async def insert_version(
        self, version_id: UUID, doc_id: UUID, *, version: int, content_hash: str, **_kwargs
    ) -> None:
        self.versions[version_id] = {
            "id": version_id,
            "document_id": doc_id,
            "version": version,
            "content_hash": content_hash,
            "ingestion_status": "pending",
        }

    async def delete_chunks_for_version(self, version_id: UUID) -> None:
        return None

    async def insert_chunk(self, chunk_row, vector) -> None:
        return None

    async def complete_version(self, version_id: UUID) -> None:
        self.versions[version_id]["ingestion_status"] = "completed"

    async def fail_version(self, version_id: UUID, message: str) -> None:
        self.versions[version_id]["ingestion_status"] = "failed"


def _capture(monkeypatch) -> list[dict]:
    captured: list[dict] = []
    _FakeRepo.documents = {}
    _FakeRepo.versions = {}

    async def capture(**kwargs) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.rag.ingestion.publish_workflow_event", capture)
    monkeypatch.setattr("app.rag.ingestion.get_parser_for", lambda path: _StubParser())
    monkeypatch.setattr("app.rag.ingestion.RagRepository", _FakeRepo)
    return captured


async def test_ingestion_events_share_correlation_and_document_id(
    tmp_path: Path, monkeypatch
) -> None:
    captured = _capture(monkeypatch)
    doc = tmp_path / "manual.md"
    doc.write_text(SAMPLE, encoding="utf-8")

    report = await IngestionService(stub_embeddings=True, chunk_size=100, chunk_overlap=0).ingest(
        None, doc, canonical_source="rep://test/camry/2024/manual"
    )

    assert report.status == "ingested", report.error
    assert report.correlation_id
    assert report.correlation_id.startswith("ingest-")

    assert captured
    assert all(event["workflow"] == WorkflowType.RAG_INGESTION for event in captured)
    # One operation, one correlation id.
    assert {event["correlation_id"] for event in captured} == {report.correlation_id}

    # Every event emitted once the document row exists carries its id.
    resolved = [event for event in captured if event["stage"] in POST_DOCUMENT_STAGES]
    assert resolved
    assert {event.get("document_id") for event in resolved} == {report.document_id}


async def test_unchanged_ingestion_carries_document_id(tmp_path: Path, monkeypatch) -> None:
    captured = _capture(monkeypatch)
    doc = tmp_path / "manual.md"
    doc.write_text(SAMPLE, encoding="utf-8")

    service = IngestionService(stub_embeddings=True, chunk_size=100, chunk_overlap=0)
    first = await service.ingest(None, doc, canonical_source="rep://test/x/2024/m")
    assert first.status == "ingested", first.error

    second = await service.ingest(None, doc, canonical_source="rep://test/x/2024/m")
    assert second.status == "unchanged", second.error
    assert second.correlation_id

    completed = [
        event
        for event in captured
        if event["stage"] == WorkflowStage.INGESTION_COMPLETED and event.get("document_id")
    ]
    assert completed
    assert {event["document_id"] for event in completed} == {first.document_id}


async def test_failed_ingestion_emits_error_with_document_id(tmp_path: Path, monkeypatch) -> None:
    captured = _capture(monkeypatch)

    async def boom(self, chunk_row, vector) -> None:
        raise RuntimeError("vector store down")

    monkeypatch.setattr(_FakeRepo, "insert_chunk", boom)

    doc = tmp_path / "manual.md"
    doc.write_text(SAMPLE, encoding="utf-8")
    report = await IngestionService(stub_embeddings=True, chunk_size=100, chunk_overlap=0).ingest(
        None, doc, canonical_source="rep://test/x/2024/m"
    )

    assert report.status == "failed"
    error_events = [event for event in captured if event["stage"] == WorkflowStage.INGESTION_ERROR]
    assert error_events
    assert error_events[0]["status"].value == "error"
    assert error_events[0]["document_id"] == report.document_id


def test_upload_response_exposes_correlation_id() -> None:
    assert "correlation_id" in AdminRagUploadResponse.model_fields


def test_to_upload_response_maps_correlation_id() -> None:
    report = IngestionReport(
        source="x",
        canonical_source="rep://test/x",
        document_id=uuid4(),
        status="ingested",
        correlation_id="ingest-rep-test-1",
    )
    response = _to_upload_response(
        report, "manual.md", AdminRagDocumentUploadForm(canonical="rep://test/x")
    )
    assert response.correlation_id == "ingest-rep-test-1"
