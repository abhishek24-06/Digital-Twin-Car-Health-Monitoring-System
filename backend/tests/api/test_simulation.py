"""API tests for the Simulation Control routes: auth, ownership, validation,
conflict handling, response shape, and the cross-vehicle summary list. The
simulator manager dependency is overridden with a real SimulationManager driven
by a fake process runner, so no OS subprocess is ever spawned."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest_asyncio

from app.api.routes import simulation as simulation_route
from app.core.config import get_settings
from app.main import app
from app.services.simulation_manager import (
    SimulationManager,
    SimulationStatus,
    get_simulation_manager,
)
from app.services.subscriber_manager import SubscriberHealth, get_subscriber_supervisor
from tests.services.test_simulation_manager import FakeProcessRunner

EXPECTED_STATUS_KEYS = {
    "vehicle_id",
    "status",
    "scenario",
    "interval_seconds",
    "seed",
    "started_at",
    "error",
    "last_telemetry_at",
}


class FakeSubscriber:
    def __init__(self, running: bool = True) -> None:
        self._running = running

    async def health(self) -> SubscriberHealth:
        return SubscriberHealth(running=self._running)


@pytest_asyncio.fixture(autouse=True)
async def simulation_manager(tmp_path):
    """Route the start/stop/restart/status dependencies to a real
    SimulationManager driven by a fake process runner, so no OS subprocess is
    ever spawned during API tests. The subscriber supervisor is faked as
    "running" so a healthy pipeline does not degrade the statuses."""
    manager = SimulationManager(
        get_settings(),
        FakeProcessRunner(),
        runtime_dir=tmp_path / "api-sims",
        grace_seconds=0.02,
        stop_timeout_seconds=0.05,
    )
    app.dependency_overrides[get_simulation_manager] = lambda: manager
    app.dependency_overrides[get_subscriber_supervisor] = lambda: FakeSubscriber(running=True)
    yield manager
    app.dependency_overrides.pop(get_subscriber_supervisor, None)
    await manager.shutdown()
    app.dependency_overrides.pop(get_simulation_manager, None)


def _assert_status_body(body: dict) -> None:
    assert set(body.keys()) == EXPECTED_STATUS_KEYS
    for secret_key in ("pid", "env", "command", "cmd"):
        assert secret_key not in body


async def test_start_requires_auth(client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/simulation",
        json={"scenario": "normal"},
    )
    assert response.status_code == 401


async def test_start_unknown_vehicle_404(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post(
        f"/api/v1/vehicles/{uuid4()}/simulation",
        json={"scenario": "normal"},
    )
    assert response.status_code == 404


async def test_start_cross_user_denied(
    other_user_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    start = await other_user_client.post(
        f"/api/v1/vehicles/{vehicle_id}/simulation", json={"scenario": "normal"}
    )
    assert start.status_code == 404, start.text
    status = await other_user_client.get(f"/api/v1/vehicles/{vehicle_id}/simulation")
    assert status.status_code == 404
    stopped = await other_user_client.delete(f"/api/v1/vehicles/{vehicle_id}/simulation")
    assert stopped.status_code == 404
    restarted = await other_user_client.post(
        f"/api/v1/vehicles/{vehicle_id}/simulation/restart",
        json={"scenario": "normal"},
    )
    assert restarted.status_code == 404


async def test_start_success(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/simulation",
        json={"scenario": "high_temperature", "interval_seconds": 2.0, "seed": 11},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    _assert_status_body(body)
    assert body["vehicle_id"] == sample_vehicle["id"]
    assert body["status"] == "running"
    assert body["scenario"] == "high_temperature"
    assert body["interval_seconds"] == 2.0
    assert body["seed"] == 11
    assert body["started_at"] is not None
    assert body["error"] is None
    assert body["last_telemetry_at"] is None


async def test_start_default_seed(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/simulation", json={"scenario": "normal"}
    )
    assert response.status_code == 201
    assert response.json()["seed"] == 42


async def test_start_validation_422(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    url = f"/api/v1/vehicles/{sample_vehicle['id']}/simulation"
    bad_scenario = await auth_client.post(url, json={"scenario": "wormhole"})
    assert bad_scenario.status_code == 422
    zero_interval = await auth_client.post(url, json={"scenario": "normal", "interval_seconds": 0})
    assert zero_interval.status_code == 422
    big_interval = await auth_client.post(url, json={"scenario": "normal", "interval_seconds": 61})
    assert big_interval.status_code == 422
    negative_seed = await auth_client.post(url, json={"scenario": "normal", "seed": -1})
    assert negative_seed.status_code == 422
    extra_field = await auth_client.post(
        url, json={"scenario": "normal", "vehicle_id": uuid4().hex}
    )
    assert extra_field.status_code == 422
    not_a_uuid = await auth_client.post("/api/v1/vehicles/not-a-uuid/simulation", json={})
    assert not_a_uuid.status_code == 422


async def test_duplicate_start_conflict(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    url = f"/api/v1/vehicles/{sample_vehicle['id']}/simulation"
    assert (await auth_client.post(url, json={"scenario": "normal"})).status_code == 201
    second = await auth_client.post(url, json={"scenario": "normal"})
    assert second.status_code == 409


async def test_get_status_stopped_default(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.get(f"/api/v1/vehicles/{sample_vehicle['id']}/simulation")
    assert response.status_code == 200
    body = response.json()
    _assert_status_body(body)
    assert body["status"] == "stopped"
    assert body["scenario"] is None
    assert body["started_at"] is None
    assert body["error"] is None


async def test_stop_idempotent(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    url = f"/api/v1/vehicles/{sample_vehicle['id']}/simulation"
    stopped_empty = await auth_client.delete(url)
    assert stopped_empty.status_code == 200
    assert stopped_empty.json()["status"] == "stopped"

    assert (await auth_client.post(url, json={"scenario": "normal"})).status_code == 201
    stopped = await auth_client.delete(url)
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"


async def test_restart_switches_scenario(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    url = f"/api/v1/vehicles/{sample_vehicle['id']}/simulation"
    assert (await auth_client.post(url, json={"scenario": "normal"})).status_code == 201
    restarted = await auth_client.post(
        url + "/restart", json={"scenario": "low_battery", "interval_seconds": 3.5}
    )
    assert restarted.status_code == 200, restarted.text
    body = restarted.json()
    assert body["status"] == "running"
    assert body["scenario"] == "low_battery"
    assert body["interval_seconds"] == 3.5


async def test_admin_can_operate_other_users_vehicle(
    admin_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    started = await admin_client.post(
        f"/api/v1/vehicles/{vehicle_id}/simulation", json={"scenario": "normal"}
    )
    assert started.status_code == 201
    status = await admin_client.get(f"/api/v1/vehicles/{vehicle_id}/simulation")
    assert status.status_code == 200
    assert status.json()["status"] == "running"
    stopped = await admin_client.delete(f"/api/v1/vehicles/{vehicle_id}/simulation")
    assert stopped.status_code == 200


async def test_status_includes_last_telemetry_at(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    now = datetime.now(UTC).isoformat()
    telemetry = {
        "timestamp": now,
        "rpm": 1000,
        "speed": 10.0,
        "engine_load": 50.0,
        "coolant_temperature": 90.0,
        "oil_temperature": 80.0,
        "battery_voltage": 12.6,
        "fuel_level": 75.0,
        "intake_air_temperature": 25.0,
        "throttle_position": 10.0,
        "engine_runtime": 100,
        "odometer": 1000.0,
    }
    created = await auth_client.post(f"/api/v1/vehicles/{vehicle_id}/telemetry", json=telemetry)
    assert created.status_code == 201
    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/simulation")
    assert response.status_code == 200
    assert response.json()["last_telemetry_at"] is not None


async def test_list_simulations_shows_own_vehicles(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.get("/api/v1/simulations")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["vehicle_id"] == sample_vehicle["id"]
    assert body["items"][0]["status"] == "stopped"

    started = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/simulation",
        json={"scenario": "normal"},
    )
    assert started.status_code == 201
    refreshed = await auth_client.get("/api/v1/simulations")
    assert refreshed.json()["items"][0]["status"] == "running"


async def test_list_simulations_empty_for_new_user(other_user_client: httpx.AsyncClient) -> None:
    response = await other_user_client.get("/api/v1/simulations")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["page"] == 1
    assert body["page_size"] == 100


async def test_list_simulations_admin_sees_all(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    admin_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    second_response = await other_user_client.post(
        "/api/v1/vehicles",
        json={
            "vin": "TESTVINADMIN0002",
            "make": "Tesla",
            "model": "Model 3",
            "year": 2025,
            "engine_type": "Electric",
        },
    )
    assert second_response.status_code == 201

    owner_list = await auth_client.get("/api/v1/simulations")
    assert owner_list.json()["total"] == 1

    admin_list = await admin_client.get("/api/v1/simulations")
    assert admin_list.status_code == 200
    ids = {item["vehicle_id"] for item in admin_list.json()["items"]}
    assert ids == {sample_vehicle["id"], second_response.json()["id"]}


async def test_list_simulations_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/simulations")
    assert response.status_code == 401


async def test_start_reports_degraded_when_subscriber_offline(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    app.dependency_overrides[get_subscriber_supervisor] = lambda: FakeSubscriber(running=False)
    try:
        response = await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/simulation", json={"scenario": "normal"}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "degraded"
        assert body["error"] is not None and "subscriber" in body["error"]

        listed = await auth_client.get("/api/v1/simulations")
        assert listed.json()["items"][0]["status"] == "degraded"

        stopped = await auth_client.delete(f"/api/v1/vehicles/{vehicle_id}/simulation")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
    finally:
        app.dependency_overrides[get_subscriber_supervisor] = lambda: FakeSubscriber(running=True)


# ---------------------------------------------------------------------- #
# Truthful status derivation (unit-level)                                #
# ---------------------------------------------------------------------- #


def _status(
    state: str,
    *,
    started_ago_seconds: float | None = None,
    error: str | None = None,
) -> SimulationStatus:
    started_at = datetime.now(UTC) - timedelta(seconds=started_ago_seconds or 0.0)
    return SimulationStatus(
        vehicle_id=uuid4(),
        status=state,
        scenario="normal",
        interval_seconds=1.0,
        seed=42,
        started_at=started_at,
        error=error,
    )


def _derive(state, last_at, subscriber=True, *, error=None) -> tuple[str, str | None]:
    return simulation_route._derive_state(
        _status(state, started_ago_seconds=120.0, error=error),
        last_at,
        subscriber,
    )


def test_derive_healthy_running_with_fresh_telemetry() -> None:
    state, error = _derive("running", datetime.now(UTC))
    assert state == "running"
    assert error is None


def test_derive_running_warmup_ignores_missing_telemetry() -> None:
    simulation = _status("running", started_ago_seconds=1.0)
    state, error = simulation_route._derive_state(simulation, None, True)
    assert state == "running"
    assert error is None


def test_derive_degraded_when_no_telemetry_after_warmup() -> None:
    state, error = _derive("running", None)
    assert state == "degraded"
    assert error is not None and "no telemetry" in error


def test_derive_degraded_when_telemetry_stale() -> None:
    state, error = _derive("running", datetime.now(UTC) - timedelta(seconds=90))
    assert state == "degraded"
    assert error is not None and "stale" in error


def test_derive_degraded_when_subscriber_offline() -> None:
    state, error = _derive("running", datetime.now(UTC), subscriber=False)
    assert state == "degraded"
    assert error is not None and "subscriber" in error


def test_derive_degraded_while_starting_with_subscriber_offline() -> None:
    state, error = _derive("starting", None, subscriber=False)
    assert state == "degraded"


def test_derive_leaves_finished_states_untouched() -> None:
    for finished in ("stopped", "error"):
        state, error = _derive(finished, None, subscriber=False)
        assert state == finished
    assert _derive("error", None)[1] is None
    assert _derive("error", None, subscriber=False)[1] is None


def test_derive_passes_through_original_error() -> None:
    state, error = _derive("error", None, error="boom")
    assert state == "error"
    assert error == "boom"
