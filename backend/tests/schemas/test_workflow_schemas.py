"""Tests for the canonical workflow event schema vocabulary."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.workflow import (
    StageState,
    TelemetryStage,
    VehicleTelemetryState,
    WorkflowEvent,
    WorkflowStage,
    WorkflowStateResponse,
    WorkflowStatus,
    WorkflowType,
)


def test_status_vocabulary_is_exact():
    """The persisted backend status vocabulary is exactly the approved set."""
    assert {s.value for s in WorkflowStatus} == {
        "started",
        "running",
        "success",
        "warning",
        "degraded",
        "error",
        "skipped",
    }


def test_waiting_is_not_a_backend_status():
    """WAITING is a frontend-only concept and must never be persisted."""
    assert "waiting" not in {s.value for s in WorkflowStatus}
    assert "waiting" not in {s.name for s in WorkflowStatus}


def test_stream_stages_exist():
    """The SSE stream lifecycle has first-class stages."""
    assert WorkflowStage.STREAM_CONNECTED.value == "stream_connected"
    assert WorkflowStage.STREAM_DISCONNECTED.value == "stream_disconnected"


def test_workflow_event_accepts_degraded():
    """An event can carry the new DEGRADED status."""
    event = WorkflowEvent(
        workflow=WorkflowType.SYSTEM,
        stage=WorkflowStage.STREAM_CONNECTED,
        status=WorkflowStatus.DEGRADED,
        message="flow degraded",
    )
    assert event.status is WorkflowStatus.DEGRADED


def test_workflow_event_rejects_waiting_status():
    """A backend event must never accept WAITING."""
    with pytest.raises(ValidationError):
        WorkflowEvent(
            workflow=WorkflowType.SYSTEM,
            stage=WorkflowStage.STREAM_CONNECTED,
            status="waiting",
            message="should fail",
        )


def test_existing_status_values_unchanged():
    """Adding statuses must not renumber or rename existing members."""
    assert WorkflowStatus.STARTED.value == "started"
    assert WorkflowStatus.RUNNING.value == "running"
    assert WorkflowStatus.SUCCESS.value == "success"
    assert WorkflowStatus.WARNING.value == "warning"
    assert WorkflowStatus.ERROR.value == "error"


# --------------------------------------------------------------------------
# Derived telemetry state (presentation-only, never an event type)
# --------------------------------------------------------------------------


def test_telemetry_stage_vocabulary_is_exact():
    assert {s.value for s in TelemetryStage} == {
        "simulator",
        "mqtt_publish",
        "mqtt_broker",
        "mqtt_subscriber",
        "parser",
        "postgres",
        "health_engine",
        "health_snapshot",
    }


def test_stage_state_round_trips():
    state = StageState(
        stage=TelemetryStage.PARSER,
        status=WorkflowStatus.SUCCESS,
        observation="derived",
        at=None,
        detail="Receiving valid telemetry",
    )
    assert state.stage is TelemetryStage.PARSER
    assert state.status is WorkflowStatus.SUCCESS
    assert state.observation == "derived"
    assert state.detail == "Receiving valid telemetry"


def test_stage_state_observation_is_bounded():
    with pytest.raises(ValidationError):
        StageState(
            stage=TelemetryStage.PARSER,
            status=WorkflowStatus.SUCCESS,
            observation="guessed",
        )


def test_stage_state_rejects_waiting():
    with pytest.raises(ValidationError):
        StageState(
            stage=TelemetryStage.PARSER,
            status="waiting",
            observation="derived",
        )


def test_workflow_state_response_shape():
    vehicle_id = uuid4()
    item = VehicleTelemetryState(
        vehicle_id=vehicle_id,
        simulation_status="running",
        stages=[
            StageState(
                stage=TelemetryStage.SIMULATOR,
                status=WorkflowStatus.SUCCESS,
                observation="derived",
            )
        ],
        messages_received=12,
    )
    response = WorkflowStateResponse(items=[item])
    assert response.items[0].vehicle_id == vehicle_id
    assert response.items[0].messages_received == 12
    assert response.items[0].updated_at is not None
    assert response.items[0].simulation_status == "running"
