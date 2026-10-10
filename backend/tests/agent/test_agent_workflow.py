"""Agent workflow correlation + error-boundary tests (hermetic: fake graph).

``AgentService._run`` owns the per-run ``agent_run_id``. The response must
carry that same id, and any graph/LLM/persist failure must publish a single
``AGENT_ERROR`` before propagating -- not only the "missing reasoning" case.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.agent.schemas import DiagnosisContent, DiagnosisResponse
from app.agent.service import AgentService
from app.agent.triggers import TriggerType
from app.schemas.workflow import WorkflowStage, WorkflowType

VEHICLE_ID = UUID("00000000-0000-0000-0000-000000000001")


def _response_payload() -> dict[str, Any]:
    return DiagnosisResponse(
        vehicle_id=VEHICLE_ID,
        trigger_type="USER_QUERY",
        user_query="why is it overheating",
        diagnosis=DiagnosisContent(summary="cooling system fault"),
        severity="warning",
        confidence=0.6,
        generated_at=datetime.now(UTC),
    ).model_dump(mode="json")


class _FakeGraph:
    """Stands in for the compiled LangGraph graph."""

    def __init__(self, *, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.saw_state: dict | None = None

    async def ainvoke(self, state, *, context):  # noqa: ANN001
        self.saw_state = state
        if self.error is not None:
            raise self.error
        return {"final_response": self.payload}


def _capture(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    async def capture(**kwargs) -> None:
        captured.append(kwargs)

    # The boundary lives in the service; nodes keep their own instrumentation.
    monkeypatch.setattr("app.agent.service.publish_workflow_event", capture)
    monkeypatch.setattr("app.agent.nodes.publish_workflow_event", capture)
    return captured


def _service(monkeypatch, graph: _FakeGraph) -> AgentService:
    monkeypatch.setattr("app.agent.service.get_cached_agent_graph", lambda *args, **kwargs: graph)
    return AgentService(None)


async def test_run_response_carries_run_correlation_id(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    graph = _FakeGraph(payload=_response_payload())
    service = _service(monkeypatch, graph)

    response = await service._run(
        vehicle_id=VEHICLE_ID,
        trigger_type=TriggerType.USER_QUERY,
        user_query="why is it overheating",
    )

    assert graph.saw_state is not None
    assert response.correlation_id == graph.saw_state["agent_run_id"]
    assert response.vehicle_id == VEHICLE_ID
    # The success path is not an error.
    assert WorkflowStage.AGENT_ERROR not in [e["stage"] for e in captured]


async def test_run_emits_agent_error_and_propagates(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    graph = _FakeGraph(error=RuntimeError("llm exploded"))
    service = _service(monkeypatch, graph)

    with pytest.raises(RuntimeError, match="llm exploded"):
        await service._run(
            vehicle_id=VEHICLE_ID,
            trigger_type=TriggerType.USER_QUERY,
            user_query="why is it overheating",
        )

    errors = [e for e in captured if e["stage"] == WorkflowStage.AGENT_ERROR]
    assert len(errors) == 1
    assert errors[0]["workflow"] == WorkflowType.AGENT
    assert errors[0]["status"].value == "error"
    assert errors[0]["vehicle_id"] == str(VEHICLE_ID)
    assert errors[0]["correlation_id"] == graph.saw_state["agent_run_id"]


async def test_diagnosis_response_exposes_correlation_id() -> None:
    assert "correlation_id" in DiagnosisResponse.model_fields
