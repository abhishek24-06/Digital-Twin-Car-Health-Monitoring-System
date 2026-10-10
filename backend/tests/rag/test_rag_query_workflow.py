"""RAG query-page pipeline instrumentation tests (hermetic: no database).

The RAG Query page calls ``GET /rag/search`` -> ``search_evidence()``. That
path previously emitted no workflow events; these tests pin the stage order,
the shared correlation id, and the error event.
"""

from __future__ import annotations

from uuid import uuid4

from app.rag.rag_service import RAGService
from app.rag.schemas import RetrievedEvidence
from app.schemas.workflow import WorkflowStage, WorkflowType


class _FakeRepo:
    """Stub for ``RagRepository`` exposing only ``hybrid_search``."""

    candidates: list = []
    error: Exception | None = None

    def __init__(self, conn) -> None:
        self.conn = conn

    async def hybrid_search(self, query_text, query_vector, *, top_k, vehicle_scope):
        if _FakeRepo.error is not None:
            raise _FakeRepo.error
        return list(_FakeRepo.candidates)


def _capture(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    async def capture(**kwargs) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.rag.rag_service.publish_workflow_event", capture)
    monkeypatch.setattr("app.rag.rag_service.RagRepository", _FakeRepo)
    _FakeRepo.candidates = []
    _FakeRepo.error = None
    return captured


def _stages(captured: list[dict]) -> list[WorkflowStage]:
    return [event["stage"] for event in captured]


def _candidate() -> RetrievedEvidence:
    return RetrievedEvidence(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        document_version=1,
        title="Coolant",
        content="Check coolant level when cold.",
        dense_score=0.9,
        lexical_score=0.5,
        hybrid_score=0.7,
        scope="GENERIC",
    )


async def test_search_evidence_emits_ordered_pipeline(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    service = RAGService(stub_embeddings=True, stub_rerank=True, enabled=True)

    result = await service.search_evidence(None, "what coolant", vehicle_scope=None, top_k=3)

    assert result.correlation_id
    assert result.correlation_id.startswith("rag-query-")
    assert all(event["workflow"] == WorkflowType.RAG_QUERY for event in captured)
    assert {event["correlation_id"] for event in captured} == {result.correlation_id}

    stages = _stages(captured)
    assert stages[0] == WorkflowStage.QUERY_RECEIVED
    assert WorkflowStage.QUERY_EMBEDDING_STARTED in stages
    assert WorkflowStage.QUERY_EMBEDDING_COMPLETED in stages
    assert WorkflowStage.VECTOR_SEARCH_STARTED in stages
    assert WorkflowStage.VECTOR_SEARCH_COMPLETED in stages
    assert WorkflowStage.CANDIDATES_RETRIEVED in stages
    assert WorkflowStage.CONTEXT_ASSEMBLED in stages
    assert stages[-1] == WorkflowStage.RAG_QUERY_COMPLETED
    assert stages.index(WorkflowStage.QUERY_RECEIVED) < stages.index(
        WorkflowStage.QUERY_EMBEDDING_STARTED
    )
    assert stages.index(WorkflowStage.CANDIDATES_RETRIEVED) < stages.index(
        WorkflowStage.CONTEXT_ASSEMBLED
    )


async def test_search_evidence_reranking_stages_when_used(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    _FakeRepo.candidates = [_candidate()]
    service = RAGService(stub_embeddings=True, stub_rerank=True, enabled=True)

    result = await service.search_evidence(None, "coolant", top_k=3, rerank=True)

    stages = _stages(captured)
    assert WorkflowStage.RERANKING_STARTED in stages
    assert WorkflowStage.RERANKING_COMPLETED in stages
    assert result.metrics["rerank_used"] is True


async def test_search_evidence_emits_error_and_raises(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    _FakeRepo.error = RuntimeError("vector store down")
    service = RAGService(stub_embeddings=True, stub_rerank=True, enabled=True)

    try:
        await service.search_evidence(None, "coolant")
    except RuntimeError as exc:
        assert "vector store down" in str(exc)
    else:  # pragma: no cover - the pipeline must propagate
        raise AssertionError("search_evidence should re-raise retrieval failure")

    error = [event for event in captured if event["stage"] == WorkflowStage.RAG_QUERY_ERROR]
    assert error
    assert error[0]["status"].value == "error"


async def test_search_evidence_does_not_change_search_path(monkeypatch) -> None:
    """``search()`` (agent tool path) keeps its own instrumentation untouched."""
    captured = _capture(monkeypatch)
    _FakeRepo.candidates = [_candidate()]
    service = RAGService(stub_embeddings=True, stub_rerank=True, enabled=True)

    guidance = await service.search(None, "coolant", None, top_k=3)

    assert guidance.available is True
    stages = _stages(captured)
    assert WorkflowStage.RAG_QUERY_COMPLETED in stages
    assert WorkflowStage.QUERY_RECEIVED in stages
