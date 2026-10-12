from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.routes import vehicle_health as vehicle_health_route

HEALTHY_PAYLOAD = {
    "rpm": 2000.0,
    "speed": 60.0,
    "engine_load": 30.0,
    "coolant_temperature": 90.0,
    "oil_temperature": 90.0,
    "battery_voltage": 13.5,
    "fuel_level": 60.0,
    "intake_air_temperature": 25.0,
    "throttle_position": 20.0,
    "engine_runtime": 1000.0,
    "odometer": 50000.0,
}


def _payload_at(seconds_ago: float) -> dict:
    ts = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    return {"timestamp": ts, **HEALTHY_PAYLOAD}


# The analysis window is 60 seconds wide and is anchored at *analysis* time,
# while these timestamps are taken during ingestion. Each POST therefore burns
# into the window budget, so the spread must stay well clear of 60s or the
# oldest samples silently fall out of the window and `sample_count` drops.
SPREAD_STEP_SECONDS = 0.1


async def _ingest(auth_client: httpx.AsyncClient, vehicle_id: str, count: int = 40) -> None:
    for index in range(count):
        response = await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry",
            json=_payload_at((count - index) * SPREAD_STEP_SECONDS),
        )
        assert response.status_code == 201, response.text


async def test_analyze_creates_healthy_context(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)

    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["vehicle_id"] == vehicle_id
    assert payload["context_schema_version"] == "1.2"
    assert payload["rule_engine_version"] == "1.0"
    assert payload["analysis_scope"] == "historical_window"
    assert payload["simulation_run_id"] is None
    assert payload["health_status"] == "healthy"
    assert payload["health_score"] == 100.0
    assert payload["data_quality"]["sample_count"] == 40
    assert "coolant_temperature" in payload["statistics"]
    assert isinstance(payload["confidence"], float)
    assert payload["data_sufficiency"] == "sufficient_data"
    assert payload["provisional"] is False
    assert payload["provisional_rating"] is None


async def test_get_latest_returns_most_recent_analysis(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health")
    assert response.status_code == 200
    assert response.json()["health_status"] == "healthy"
    # The latest report here is a historical window analysis, never current.
    assert response.json()["analysis_scope"] == "historical_window"


async def test_get_latest_404_when_no_snapshot(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.get(f"/api/v1/vehicles/{sample_vehicle['id']}/health")
    assert response.status_code == 404


async def test_get_latest_404_for_missing_vehicle(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get(f"/api/v1/vehicles/{uuid4()}/health")
    assert response.status_code == 404


async def test_history_pagination_and_growth(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    for _ in range(3):
        assert (
            await auth_client.post(
                f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
            )
        ).status_code == 200

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/history")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert len(page["items"]) == 3
    items = page["items"]
    assert all(item["health_status"] == "healthy" for item in items)
    assert items[0]["generated_at"] >= items[1]["generated_at"]

    page_two = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/health/history", params={"page": 1, "page_size": 2}
    )
    assert page_two.json()["total"] == 3
    assert len(page_two.json()["items"]) == 2


async def test_history_time_filtering(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    assert (
        await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
        )
    ).status_code == 200

    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    response = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/health/history",
        params={"start_time": future},
    )
    assert response.json()["total"] == 0

    response = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/health/history",
        params={"end_time": past},
    )
    assert response.json()["total"] == 0


async def test_analyze_missing_vehicle_is_404(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post(f"/api/v1/vehicles/{uuid4()}/health/analyze")
    assert response.status_code == 404


async def test_analyze_invalid_window_minutes_is_422(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/health/analyze",
        params={"window_minutes": 0},
    )
    assert response.status_code == 422

    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/health/analyze",
        params={"window_minutes": 1441},
    )
    assert response.status_code == 422


async def test_analyze_with_no_telemetry_is_no_data(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/health/analyze", params={"window_minutes": 1}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["health_status"] == "no_data"
    assert payload["health_score"] is None
    assert payload["data_sufficiency"] == "no_data"
    assert payload["provisional"] is False
    assert any(f["rule_id"] == "INSUFFICIENT_DATA" for f in payload["findings"])


async def test_high_temperature_context_reflected_in_findings(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    for index in range(40):
        payload = _payload_at((40 - index) * SPREAD_STEP_SECONDS)
        payload["coolant_temperature"] = 115.0
        response = await auth_client.post(f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload)
        assert response.status_code == 201, response.text

    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )
    assert response.status_code == 200
    payload = response.json()
    rule_ids = {f["rule_id"]: f["severity"] for f in payload["findings"]}
    assert rule_ids["COOLANT_TEMP_HIGH"] == "critical"
    assert payload["health_status"] == "attention"


async def test_cross_user_health_denied(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    assert (
        await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
        )
    ).status_code == 200

    assert (await other_user_client.get(f"/api/v1/vehicles/{vehicle_id}/health")).status_code == 404
    assert (
        await other_user_client.get(f"/api/v1/vehicles/{vehicle_id}/health/history")
    ).status_code == 404
    assert (
        await other_user_client.post(
            f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
        )
    ).status_code == 404


# --- Live current-session health (Phase 2) ---


class FakeSimulationManager:
    """Stands in for the real process-supervising manager (no subprocesses)."""

    def __init__(self, *, run_id: UUID | None = None, state: str = "stopped", error: str | None = None) -> None:
        self._run_id = run_id
        self._state = state
        self._error = error

    async def get_status(self, vehicle_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(status=self._state, error=self._error)

    async def active_run_id(self, vehicle_id: UUID) -> UUID | None:
        return self._run_id


def _patch_manager(monkeypatch: pytest.MonkeyPatch, manager: FakeSimulationManager) -> None:
    monkeypatch.setattr(vehicle_health_route, "get_simulation_manager", lambda: manager)


def _run_payload_at(seconds_ago: float, run_id: UUID) -> dict:
    ts = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    return {
        "timestamp": ts,
        "simulation_run_id": str(run_id),
        **HEALTHY_PAYLOAD,
    }


async def _ingest_run(
    auth_client: httpx.AsyncClient,
    vehicle_id: str,
    run_id: UUID,
    *,
    count: int = 40,
    seconds_ago_at_end: float = 1.0,
    step: float = 1.0,
) -> None:
    for index in range(count):
        response = await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry",
            json=_run_payload_at(
                seconds_ago_at_end + (count - index - 1) * step, run_id
            ),
        )
        assert response.status_code == 201, response.text


async def test_live_no_session_never_presents_old_snapshot(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stopped vehicle: the live view reports no session and keeps the old
    historical snapshot out of the current-session assessment."""
    vehicle_id = sample_vehicle["id"]
    _patch_manager(monkeypatch, FakeSimulationManager(run_id=None, state="stopped"))

    await _ingest(auth_client, vehicle_id)
    analyze_resp = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )
    assert analyze_resp.status_code == 200
    historical_generated_at = analyze_resp.json()["generated_at"]

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["simulator_state"] == "stopped"
    assert body["live_state"] == "no_session"
    assert body["run_id"] is None
    assert body["assessment"] is None
    # The old snapshot's timestamp surfaces only as *when* an evaluation last
    # ran, never as the current assessment.
    assert body["last_evaluated_at"] == historical_generated_at
    assert body["sample_count"] == 0


async def test_live_collecting_state_with_fresh_run(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    vehicle_id = sample_vehicle["id"]
    run_id = uuid4()
    _patch_manager(
        monkeypatch, FakeSimulationManager(run_id=run_id, state="running")
    )
    await _ingest_run(auth_client, vehicle_id, run_id, count=5, step=1.0)

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(run_id)
    assert body["simulator_state"] == "running"
    assert body["live_state"] == "collecting"
    assert body["sample_count"] == 5
    assert body["required_sample_count"] == 30
    assert body["assessment"] is None
    assert body["insufficiency_reasons"]
    assert body["latest_source_timestamp"] is not None
    assert body["latest_persisted_at"] is not None


async def test_live_fresh_run_yields_definitive_assessment(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    vehicle_id = sample_vehicle["id"]
    run_id = uuid4()
    _patch_manager(monkeypatch, FakeSimulationManager(run_id=run_id, state="running"))
    await _ingest_run(auth_client, vehicle_id, run_id, count=40, step=1.0)

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(run_id)
    assert body["live_state"] == "fresh"
    assert body["sample_count"] == 40
    assert body["assessment"] is not None
    assessment = body["assessment"]
    assert assessment["health_status"] == "healthy"
    assert assessment["data_sufficiency"] == "sufficient_data"
    assert assessment["provisional"] is False
    assert assessment["simulation_run_id"] == str(run_id)
    assert body["last_evaluated_at"] is not None
    assert body["message"] is not None


async def test_live_read_is_side_effect_free(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2-1: GET /health/live must not persist a snapshot as a read side-effect.

    Repeated live polls used to write a current-session snapshot each time,
    filling the snapshot history from a read endpoint. A live evaluation must
    leave the persisted snapshot count unchanged while still returning a
    definitive assessment.
    """
    vehicle_id = sample_vehicle["id"]
    run_id = uuid4()
    _patch_manager(monkeypatch, FakeSimulationManager(run_id=run_id, state="running"))
    await _ingest_run(auth_client, vehicle_id, run_id, count=40, step=1.0)

    before = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/health/history", params={"page_size": 100}
    )
    assert before.status_code == 200
    before_total = before.json()["total"]

    for _ in range(3):
        response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
        assert response.status_code == 200
        body = response.json()
        assert body["live_state"] == "fresh"
        assert body["assessment"] is not None

    after = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/health/history", params={"page_size": 100}
    )
    assert after.status_code == 200
    assert after.json()["total"] == before_total


async def test_live_uses_only_active_run_over_api(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance 1+4: the live endpoint assesses only the active run and
    labels the report scope; legacy and previous-run outliers in the same
    window are excluded."""
    vehicle_id = sample_vehicle["id"]
    active_run = uuid4()
    old_run = uuid4()
    _patch_manager(monkeypatch, FakeSimulationManager(run_id=active_run, state="running"))

    # Legacy (NULL-run) critical outlier ~10 minutes ago: inside the window.
    for index in range(30):
        payload = _payload_at(600 + index * 0.1)
        payload["coolant_temperature"] = 130.0
        assert (
            await auth_client.post(f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload)
        ).status_code == 201
    # Previous-run critical outlier ~8 minutes ago: inside the window.
    for index in range(30):
        payload = _payload_at(480 + index * 0.1)
        payload["coolant_temperature"] = 130.0
        payload["simulation_run_id"] = str(old_run)
        assert (
            await auth_client.post(f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload)
        ).status_code == 201
    # Active run: fresh, sufficient and healthy.
    await _ingest_run(auth_client, vehicle_id, active_run, count=40, step=1.0)

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["live_state"] == "fresh"
    assert body["sample_count"] == 40
    assessment = body["assessment"]
    assert assessment is not None
    assert assessment["analysis_scope"] == "current_session"
    assert assessment["simulation_run_id"] == str(active_run)
    assert assessment["statistics"]["coolant_temperature"]["maximum"] == 90.0
    assert all(f["rule_id"] != "COOLANT_TEMP_HIGH" for f in assessment["findings"])


async def test_live_stale_feed_state(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    vehicle_id = sample_vehicle["id"]
    run_id = uuid4()
    _patch_manager(monkeypatch, FakeSimulationManager(run_id=run_id, state="running"))
    # 40 samples spanning 40s, but the newest is 60s old: plenty of data, no
    # freshness.
    await _ingest_run(
        auth_client,
        vehicle_id,
        run_id,
        count=40,
        seconds_ago_at_end=60.0,
        step=1.0,
    )

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["live_state"] == "stale"
    assert body["assessment"] is None
    assert body["latest_sample_age_seconds"] >= body["max_sample_age_seconds"]
    assert any("old" in r for r in body["insufficiency_reasons"])


async def test_live_denied_for_other_user(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vehicle_id = sample_vehicle["id"]
    _patch_manager(monkeypatch, FakeSimulationManager(run_id=uuid4(), state="running"))
    await _ingest_run(auth_client, vehicle_id, uuid4(), count=5)

    response = await other_user_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
    assert response.status_code == 404
