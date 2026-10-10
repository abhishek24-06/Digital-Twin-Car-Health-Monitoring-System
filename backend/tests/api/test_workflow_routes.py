"""Tests for the workflow observability routes.

Auth is exercised through the fast in-process ASGI client. Stream frames are
driven by calling the route coroutine directly and consuming its
``body_iterator`` in the same event loop -- an endless SSE body cannot be
observed through httpx's buffering ASGITransport.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx

from app.api.routes.workflow import (
    _is_event_visible,
    stream_events,
)
from app.schemas.workflow import (
    WorkflowEvent,
    WorkflowStage,
    WorkflowStatus,
    WorkflowType,
)
from app.services.workflow_event_bus import (
    get_workflow_event_bus,
    publish_workflow_event,
)
from tests.conftest import unique_vin


class _FakeRequest:
    """Minimal Request stand-in: the route only asks if the client left."""

    async def is_disconnected(self) -> bool:
        return False


class _FakeUser:
    """Duck-typed user for direct route invocation (admin by default)."""

    def __init__(self, *, is_admin: bool = True, user_id=None) -> None:
        self.is_admin = is_admin
        self.id = user_id


async def _open_stream(**params):
    response = await stream_events(request=_FakeRequest(), user=_FakeUser(is_admin=True), **params)
    return response.body_iterator


async def _close(iterator) -> None:
    aclose = getattr(iterator, "aclose", None)
    if aclose is not None:
        await aclose()


def _parse(frame: str) -> dict:
    assert frame.startswith("data:"), frame
    return json.loads(frame[5:].strip())


async def test_recent_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/workflow/events/recent")
    assert response.status_code == 401


async def test_recent_hides_other_users_vehicles_and_ingestion(
    auth_client: httpx.AsyncClient,
    admin_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    bus = get_workflow_event_bus()
    await bus.clear()

    other_vehicle = await other_user_client.post(
        "/api/v1/vehicles",
        json={
            "vin": unique_vin(),
            "make": "Honda",
            "model": "Civic",
            "year": 2022,
            "engine_type": "1.8L Petrol",
        },
    )
    assert other_vehicle.status_code == 201, other_vehicle.text
    other_vehicle_id = other_vehicle.json()["id"]

    await publish_workflow_event(
        workflow=WorkflowType.SIMULATION,
        stage=WorkflowStage.SIMULATION_STARTED,
        status=WorkflowStatus.SUCCESS,
        message="owned-vehicle",
        vehicle_id=sample_vehicle["id"],
    )
    await publish_workflow_event(
        workflow=WorkflowType.SIMULATION,
        stage=WorkflowStage.SIMULATION_STARTED,
        status=WorkflowStatus.SUCCESS,
        message="other-vehicle",
        vehicle_id=other_vehicle_id,
    )
    await publish_workflow_event(
        workflow=WorkflowType.RAG_INGESTION,
        stage=WorkflowStage.DOCUMENT_UPLOAD_STARTED,
        status=WorkflowStatus.STARTED,
        message="private-ingestion",
    )
    await publish_workflow_event(
        workflow=WorkflowType.SYSTEM,
        stage=WorkflowStage.SUBSCRIBER_STARTED,
        status=WorkflowStatus.SUCCESS,
        message="global-system",
    )

    user_response = await auth_client.get("/api/v1/workflow/events/recent")
    assert user_response.status_code == 200, user_response.text
    user_messages = {item["message"] for item in user_response.json()["items"]}
    assert "owned-vehicle" in user_messages
    assert "global-system" in user_messages
    assert "other-vehicle" not in user_messages
    assert "private-ingestion" not in user_messages

    admin_response = await admin_client.get("/api/v1/workflow/events/recent")
    assert admin_response.status_code == 200, admin_response.text
    admin_messages = {item["message"] for item in admin_response.json()["items"]}
    assert {
        "owned-vehicle",
        "other-vehicle",
        "private-ingestion",
        "global-system",
    } <= admin_messages


async def test_stream_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/workflow/events/stream")
    assert response.status_code == 401


async def test_stream_first_frame_is_connection_event() -> None:
    """The known enum-attribute bug must be fixed: no AttributeError."""
    iterator = await _open_stream()
    try:
        frame = await asyncio.wait_for(iterator.__anext__(), timeout=5)
        payload = _parse(frame)
        assert payload["workflow"] == "system"
        assert payload["stage"] == "stream_connected"
        assert payload["status"] == "success"
    finally:
        await _close(iterator)


async def test_stream_filters_by_correlation_id() -> None:
    bus = get_workflow_event_bus()
    await bus.clear()

    iterator = await _open_stream(correlation_id="corr-A")
    try:
        await asyncio.wait_for(iterator.__anext__(), timeout=5)  # connection frame

        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_STARTED,
            status=WorkflowStatus.SUCCESS,
            message="other operation",
            correlation_id="corr-B",
        )
        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_STARTED,
            status=WorkflowStatus.SUCCESS,
            message="target operation",
            correlation_id="corr-A",
        )

        frame = await asyncio.wait_for(iterator.__anext__(), timeout=5)
        payload = _parse(frame)
        assert payload["correlation_id"] == "corr-A"
        assert payload["message"] == "target operation"
    finally:
        await _close(iterator)


def _event(**kwargs) -> WorkflowEvent:
    base = dict(
        workflow=WorkflowType.SIMULATION,
        stage=WorkflowStage.SIMULATION_STARTED,
        status=WorkflowStatus.SUCCESS,
        message="m",
    )
    base.update(kwargs)
    return WorkflowEvent(**base)


def test_is_event_visible_admin_sees_everything() -> None:
    assert _is_event_visible(_event(workflow=WorkflowType.RAG_INGESTION), None)


def test_is_event_visible_non_admin_never_sees_ingestion() -> None:
    assert not _is_event_visible(_event(workflow=WorkflowType.RAG_INGESTION), set())


def test_is_event_visible_non_admin_global_event_allowed() -> None:
    assert _is_event_visible(_event(vehicle_id=None), set())


def test_is_event_visible_non_admin_owned_vehicle_only() -> None:
    owned = uuid4()
    other = uuid4()
    assert _is_event_visible(_event(vehicle_id=owned), {owned})
    assert not _is_event_visible(_event(vehicle_id=other), {owned})


async def test_stream_does_not_leak_other_vehicle_events(monkeypatch) -> None:
    bus = get_workflow_event_bus()
    await bus.clear()

    owned_id = uuid4()
    other_id = uuid4()

    async def fake_resolve(_user):
        return {owned_id}

    monkeypatch.setattr("app.api.routes.workflow._resolve_visible_vehicle_ids", fake_resolve)

    response = await stream_events(
        request=_FakeRequest(), user=_FakeUser(is_admin=False, user_id=uuid4())
    )
    iterator = response.body_iterator
    try:
        await asyncio.wait_for(iterator.__anext__(), timeout=5)  # connection frame

        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_STARTED,
            status=WorkflowStatus.SUCCESS,
            message="other-vehicle",
            vehicle_id=str(other_id),
        )
        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_STARTED,
            status=WorkflowStatus.SUCCESS,
            message="owned-vehicle",
            vehicle_id=str(owned_id),
        )

        frame = await asyncio.wait_for(iterator.__anext__(), timeout=5)
        payload = _parse(frame)
        assert payload["message"] == "owned-vehicle"
    finally:
        await _close(iterator)


async def test_state_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/workflow/state")
    assert response.status_code == 401


async def test_status_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/workflow/status")
    assert response.status_code == 401


async def test_status_reports_high_level_state(auth_client: httpx.AsyncClient) -> None:
    """GET /api/v1/workflow/status returns the high-level snapshot.

    The endpoint derives the recency signal by counting persisted telemetry
    through the real repository, so this exercises the full code path rather
    than a stub.
    """
    response = await auth_client.get("/api/v1/workflow/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["events_in_buffer"], int)
    assert "oldest_event_ts" in body
    assert "newest_event_ts" in body
    assert "telemetry_pipeline_active" in body
    assert "rag_pipeline_active" in body
    assert "agent_pipeline_active" in body
    assert "subscriber_running" in body
    assert "active_simulations" in body


async def test_state_owned_vehicle_has_derived_stages(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.get(
        "/api/v1/workflow/state", params={"vehicle_id": sample_vehicle["id"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["vehicle_id"] == sample_vehicle["id"]
    assert item["stages"], "expected at least the always-known subscriber stage"
    assert all(stage["observation"] == "derived" for stage in item["stages"])
    assert all(stage["status"] != "waiting" for stage in item["stages"])


async def test_state_hides_other_users_vehicle(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    response = await other_user_client.get(
        "/api/v1/workflow/state", params={"vehicle_id": sample_vehicle["id"]}
    )
    # Not a leaky 404: the caller gets a well-formed, empty result.
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


async def test_state_admin_sees_all_vehicles(
    admin_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await admin_client.get("/api/v1/workflow/state")
    assert response.status_code == 200, response.text
    ids = {item["vehicle_id"] for item in response.json()["items"]}
    assert sample_vehicle["id"] in ids


async def test_state_surfaces_last_health_failure(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, monkeypatch
) -> None:
    """A newer failed health evaluation is reported as a degraded engine.

    Regression: the monitor can fail (e.g. a statement timeout) while the
    process still looks "running"; derived state must consult the failure so the
    UI does not show a healthy engine that is actually erroring.
    """
    from types import SimpleNamespace  # noqa: PLC0415

    from app.services import telemetry_pipeline_state as tps  # noqa: PLC0415

    # The hermetic suite disables the monitor (HEALTH_MONITOR_ENABLED=false), so
    # opt it in here to exercise the failure-surfacing path.
    monkeypatch.setattr(
        tps,
        "get_settings",
        lambda: SimpleNamespace(
            health_monitor_enabled=True,
            health_monitor_min_seconds=60.0,
            health_monitor_interval_seconds=10.0,
        ),
    )

    bus = get_workflow_event_bus()
    await bus.clear()
    await publish_workflow_event(
        workflow=WorkflowType.HEALTH,
        stage=WorkflowStage.HEALTH_ANALYSIS_STARTED,
        status=WorkflowStatus.ERROR,
        message="statement timeout",
        vehicle_id=sample_vehicle["id"],
    )

    response = await auth_client.get(
        "/api/v1/workflow/state", params={"vehicle_id": sample_vehicle["id"]}
    )
    assert response.status_code == 200, response.text
    stages = {stage["stage"]: stage for stage in response.json()["items"][0]["stages"]}
    assert stages["health_engine"]["status"] == "degraded"
    assert "statement timeout" in stages["health_engine"]["detail"]


def _dependency_calls(route) -> set[str]:
    calls: set[str] = set()

    def walk(dependant) -> None:
        for sub in dependant.dependencies:
            if sub.call is not None:
                calls.add(getattr(sub.call, "__name__", str(sub.call)))
            walk(sub)

    walk(route.dependant)
    return calls


def test_stream_route_does_not_pin_request_scoped_db_session() -> None:
    """The SSE routes must resolve auth without the request-scoped DB session.

    Pinning ``get_db`` for the lifetime of an SSE response kept a pooled
    connection (and an open transaction) busy for minutes, starving the pool and
    making ``/workflow/state`` time out -- which surfaced as stale UI state.
    """
    from app.api.routes.telemetry import (  # noqa: PLC0415
        router as telemetry_router,
    )
    from app.api.routes.workflow import router  # noqa: PLC0415

    for route in router.routes:
        if getattr(route, "path", None) == "/workflow/events/stream":
            calls = _dependency_calls(route)
            assert "get_current_user_stream" in calls
            assert "get_current_user" not in calls
            assert "get_db" not in calls
            break
    else:  # pragma: no cover - fail loudly if the route is renamed
        raise AssertionError("workflow stream route not found")

    for route in telemetry_router.routes:
        if getattr(route, "path", None) == "/stream":
            calls = _dependency_calls(route)
            assert "get_current_user_stream" in calls
            assert "get_current_user" not in calls
            assert "get_db" not in calls
            break
    else:  # pragma: no cover - fail loudly if the route is renamed
        raise AssertionError("telemetry stream route not found")
