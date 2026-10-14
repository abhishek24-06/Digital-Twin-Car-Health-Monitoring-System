"""Phase A: abuse control and concurrency handling for POST /health/analyze.

These tests exercise the real ASGI app against the real test database:

* the per-user analysis budget returns 429 with a Retry-After header and does
  not write a snapshot for the rejected request;
* identical concurrent analyses are coalesced into a single run and a single
  snapshot, while distinct requests are never merged;
* the coalescing key is caller-scoped so one user can never receive another
  user's report.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.api.routes import vehicle_health as vehicle_health_route
from app.core.config import get_settings
from app.services.analysis_coordinator import AnalysisCoordinator
from app.services.vehicle_health_service import VehicleHealthService

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


async def _ingest(client: httpx.AsyncClient, vehicle_id: str, count: int = 40) -> None:
    for index in range(count):
        ts = (datetime.now(UTC) - timedelta(seconds=(count - index) * 0.1)).isoformat()
        response = await client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry",
            json={"timestamp": ts, **HEALTHY_PAYLOAD},
        )
        assert response.status_code == 201, response.text


@pytest.fixture
def small_analysis_budget(monkeypatch: pytest.MonkeyPatch):
    """Rebuild the analysis limiter with a 2-request budget for one test."""
    from app.core import rate_limit as rl

    settings = get_settings().model_copy(
        update={
            "analysis_rate_limit_enabled": True,
            "analysis_rate_limit_max_requests": 2,
            "analysis_rate_limit_window_seconds": 60.0,
        }
    )
    monkeypatch.setattr(rl, "get_settings", lambda: settings)
    vehicle_health_route._analysis_rate_limit.reset()
    yield
    vehicle_health_route._analysis_rate_limit.reset()


async def test_analyze_rate_limit_returns_429_without_snapshot(
    auth_client: httpx.AsyncClient,
    sample_vehicle: dict,
    small_analysis_budget: None,
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    url = f"/api/v1/vehicles/{vehicle_id}/health/analyze"

    first = await auth_client.post(url, params={"window_minutes": 1})
    second = await auth_client.post(url, params={"window_minutes": 1})
    blocked = await auth_client.post(url, params={"window_minutes": 1})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert blocked.status_code == 429, blocked.text
    assert int(blocked.headers["Retry-After"]) >= 1

    # The rejected request must not have produced a third snapshot.
    history = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/history")
    assert history.json()["total"] == 2


async def test_analyze_rate_limit_can_be_disabled(
    auth_client: httpx.AsyncClient,
    sample_vehicle: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import rate_limit as rl

    settings = get_settings().model_copy(update={"analysis_rate_limit_enabled": False})
    monkeypatch.setattr(rl, "get_settings", lambda: settings)
    vehicle_health_route._analysis_rate_limit.reset()

    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    url = f"/api/v1/vehicles/{vehicle_id}/health/analyze"

    try:
        for _ in range(5):
            response = await auth_client.post(url, params={"window_minutes": 1})
            assert response.status_code == 200, response.text
    finally:
        vehicle_health_route._analysis_rate_limit.reset()


async def test_concurrent_identical_analyses_write_one_snapshot(
    auth_client: httpx.AsyncClient,
    sample_vehicle: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)

    calls = {"n": 0}
    started = asyncio.Event()
    release = asyncio.Event()
    original = VehicleHealthService.analyze_vehicle_for_user

    async def slow(self, vid, user, window_minutes=None):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        started.set()
        await release.wait()
        return await original(self, vid, user, window_minutes=window_minutes)

    monkeypatch.setattr(VehicleHealthService, "analyze_vehicle_for_user", slow)
    coordinator = AnalysisCoordinator()
    monkeypatch.setattr(vehicle_health_route, "get_analysis_coordinator", lambda: coordinator)

    url = f"/api/v1/vehicles/{vehicle_id}/health/analyze"
    leader = asyncio.create_task(auth_client.post(url, params={"window_minutes": 1}))
    await asyncio.wait_for(started.wait(), timeout=5)
    follower = asyncio.create_task(auth_client.post(url, params={"window_minutes": 1}))
    # Wait until the follower has actually reached the coordinator and joined
    # the in-flight analysis, instead of guessing with a fixed sleep.
    for _ in range(250):
        if coordinator.waiter_count >= 1:
            break
        await asyncio.sleep(0.02)
    assert coordinator.waiter_count >= 1, "follower never joined the in-flight analysis"
    release.set()

    first, second = await asyncio.gather(leader, follower)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert calls["n"] == 1
    assert first.json()["generated_at"] == second.json()["generated_at"]

    history = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/history")
    assert history.json()["total"] == 1


async def test_concurrent_distinct_windows_are_not_merged(
    auth_client: httpx.AsyncClient,
    sample_vehicle: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)

    calls = {"n": 0}
    original = VehicleHealthService.analyze_vehicle_for_user

    async def counting(self, vid, user, window_minutes=None):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return await original(self, vid, user, window_minutes=window_minutes)

    monkeypatch.setattr(VehicleHealthService, "analyze_vehicle_for_user", counting)
    coordinator = AnalysisCoordinator()
    monkeypatch.setattr(vehicle_health_route, "get_analysis_coordinator", lambda: coordinator)

    url = f"/api/v1/vehicles/{vehicle_id}/health/analyze"
    first, second = await asyncio.gather(
        auth_client.post(url, params={"window_minutes": 1}),
        auth_client.post(url, params={"window_minutes": 2}),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert calls["n"] == 2

    history = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/history")
    assert history.json()["total"] == 2


def test_analysis_key_is_caller_scoped() -> None:
    from uuid import uuid4

    from app.models.user import User

    vehicle_id = uuid4()
    user_a = User(id=uuid4(), email="a@example.com", password_hash="x")
    user_b = User(id=uuid4(), email="b@example.com", password_hash="x")

    key_a = vehicle_health_route._analysis_key(vehicle_id, user_a, 15)
    key_b = vehicle_health_route._analysis_key(vehicle_id, user_b, 15)
    assert key_a != key_b
    assert key_a == vehicle_health_route._analysis_key(vehicle_id, user_a, 15)
    assert key_a != vehicle_health_route._analysis_key(vehicle_id, user_a, 30)
