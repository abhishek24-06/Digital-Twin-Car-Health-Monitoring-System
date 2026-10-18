"""Unit tests for the shared simulator-state reconciliation.

These pin the exact rule every consumer (Simulation Control and the fleet
overview) relies on: a process that cannot be delivering telemetry is reported
as ``degraded`` rather than a hollow ``running``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.services.simulation_manager import SimulationStatus
from app.services.simulation_state import derive_simulation_state, telemetry_is_stale
from app.services.telemetry_freshness import STALE_AFTER_SECONDS, STARTUP_BUFFER_SECONDS


def _status(**overrides: object) -> SimulationStatus:
    base: dict[str, object] = {
        "vehicle_id": uuid4(),
        "status": "running",
        "started_at": datetime.now(UTC) - timedelta(minutes=10),
    }
    base.update(overrides)
    return SimulationStatus(**base)  # type: ignore[arg-type]


def test_stopped_passthrough() -> None:
    state, error = derive_simulation_state(_status(status="stopped"), None, True)
    assert state == "stopped"
    assert error is None


def test_error_passthrough_keeps_reason() -> None:
    state, error = derive_simulation_state(_status(status="error", error="boom"), None, True)
    assert state == "error"
    assert error == "boom"


def test_running_with_fresh_telemetry_is_running() -> None:
    state, error = derive_simulation_state(
        _status(), datetime.now(UTC), True, now=datetime.now(UTC)
    )
    assert state == "running"
    assert error is None


def test_running_without_telemetry_after_warmup_is_degraded() -> None:
    now = datetime.now(UTC)
    simulation = _status(started_at=now - timedelta(seconds=STARTUP_BUFFER_SECONDS + 5))
    state, error = derive_simulation_state(simulation, None, True, now=now)
    assert state == "degraded"
    assert error is not None


def test_running_with_stale_telemetry_is_degraded() -> None:
    now = datetime.now(UTC)
    last = now - timedelta(seconds=STALE_AFTER_SECONDS * 3)
    state, error = derive_simulation_state(_status(), last, True, now=now)
    assert state == "degraded"
    assert error is not None


def test_running_within_warmup_is_not_degraded() -> None:
    now = datetime.now(UTC)
    simulation = _status(started_at=now - timedelta(seconds=1))
    state, _ = derive_simulation_state(simulation, None, True, now=now)
    assert state == "running"


def test_running_with_subscriber_offline_is_degraded() -> None:
    now = datetime.now(UTC)
    state, error = derive_simulation_state(_status(), now, False, now=now)
    assert state == "degraded"
    assert error is not None


def test_telemetry_is_stale_matches_threshold() -> None:
    now = datetime.now(UTC)
    simulation = _status(started_at=now - timedelta(minutes=5))
    assert telemetry_is_stale(
        simulation, now - timedelta(seconds=STALE_AFTER_SECONDS - 1), now=now
    ) is False
    assert telemetry_is_stale(
        simulation, now - timedelta(seconds=STALE_AFTER_SECONDS + 1), now=now
    ) is True
