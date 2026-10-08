"""SSE live-telemetry stream endpoint tests.

Authentication/authorization/validation are exercised through the fast
in-process ASGITransport client. Actual streaming (heartbeats, live events,
cursor progress, disconnect behaviour) is verified over real HTTP against a
uvicorn server started on an ephemeral port: httpx's ``ASGITransport`` buffers
the whole response, so it can never see an endless stream.
"""

import asyncio
import json
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import uvicorn

from app.main import app
from tests.api.test_telemetry import telemetry_payload


def _future_iso(seconds: int) -> str:
    """A timestamp comfortably after any connection-time cursor."""
    dt = datetime.now(UTC) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


async def _next_data_line(lines: httpx.AsyncByteStream, timeout: float = 15.0) -> str:
    """Return the next ``data:`` line or fail instead of hanging forever."""

    async def _collect() -> str:
        async for line in lines:
            if line.startswith("data:"):
                return line
        raise AssertionError("stream ended before a data frame arrived")

    return await asyncio.wait_for(_collect(), timeout)


@pytest.fixture(scope="module")
def live_server(test_app_engine) -> str:
    """A real HTTP server running the app on an ephemeral port.

    ``lifespan="off"`` avoids double-initialising/disposing the shared engine:
    the pytest session already created the schema, and the engine is a
    process-wide NullPool resource the tests and server can share across their
    separate event loops.
    """
    config = uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not getattr(server, "started", False):
            if time.monotonic() > deadline:
                raise RuntimeError("live uvicorn server did not start in time")
            if not thread.is_alive():
                raise RuntimeError("live uvicorn server thread exited during startup")
            time.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def _make_vehicle(base_url: str, client: httpx.AsyncClient) -> tuple[str, dict[str, str]]:
    """Register a fresh owner and their vehicle over real HTTP."""
    email = f"stream.{uuid.uuid4().hex[:8]}@example.com"
    registered = await client.post(
        f"{base_url}/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert registered.status_code == 201, registered.text
    login = await client.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        f"{base_url}/api/v1/vehicles",
        json={
            "vin": f"SSEVIN{uuid.uuid4().hex[:10].upper()}",
            "make": "Toyota",
            "model": "Camry",
            "year": 2024,
            "engine_type": "2.5L Petrol",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"], headers


# ---------------------------------------------------------------------------
# In-process route checks (auth/ownership/validation happen before streaming).
# ---------------------------------------------------------------------------


async def test_stream_requires_auth(client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await client.get(f"/api/v1/vehicles/{sample_vehicle['id']}/telemetry/stream")

    assert response.status_code == 401


async def test_stream_unknown_vehicle(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get(f"/api/v1/vehicles/{uuid.uuid4()}/telemetry/stream")

    assert response.status_code == 404


async def test_stream_cross_user_denied(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    response = await other_user_client.get(
        f"/api/v1/vehicles/{sample_vehicle['id']}/telemetry/stream"
    )

    assert response.status_code == 404


async def test_stream_rejects_non_positive_interval(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.get(
        f"/api/v1/vehicles/{sample_vehicle['id']}/telemetry/stream",
        params={"interval_seconds": 0},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Live HTTP streaming behaviour.
# ---------------------------------------------------------------------------


async def test_live_stream_heartbeats_then_delivers_new_events(live_server: str, clean_db) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        vehicle_id, headers = await _make_vehicle(live_server, client)
        url = f"{live_server}/api/v1/vehicles/{vehicle_id}/telemetry/stream"

        async with client.stream(
            "GET", url, headers=headers, params={"interval_seconds": 0.05}
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = response.aiter_lines()

            # Live but idle -> heartbeat comment.
            first = await asyncio.wait_for(anext(lines), timeout=15)
            assert first == ": ping"

            # Publish a sample while the stream is open.
            posted = await client.post(
                f"{live_server}/api/v1/vehicles/{vehicle_id}/telemetry",
                json=telemetry_payload(_future_iso(5), rpm=3400.0),
                headers=headers,
            )
            assert posted.status_code == 201

            data_line = await _next_data_line(lines)
            payload = json.loads(data_line[5:].strip())
            assert "timestamp" in payload
            assert "server_time" in payload
            assert len(payload["events"]) == 1
            event = payload["events"][0]
            assert event["vehicle_id"] == vehicle_id
            assert event["rpm"] == 3400.0


async def test_live_stream_batches_samples_in_cursor_order(live_server: str, clean_db) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        vehicle_id, headers = await _make_vehicle(live_server, client)
        url = f"{live_server}/api/v1/vehicles/{vehicle_id}/telemetry/stream"

        # Seed both samples BEFORE connecting, so one poll observes both.
        for rpm, odometer, secs in ((1000.0, 0, 5), (2000.0, 1, 6)):
            posted = await client.post(
                f"{live_server}/api/v1/vehicles/{vehicle_id}/telemetry",
                json=telemetry_payload(_future_iso(secs), rpm=rpm, odometer=float(odometer)),
                headers=headers,
            )
            assert posted.status_code == 201

        async with client.stream(
            "GET", url, headers=headers, params={"interval_seconds": 0.05}
        ) as response:
            assert response.status_code == 200
            payload = json.loads((await _next_data_line(response.aiter_lines()))[5:].strip())
            rpms = [event["rpm"] for event in payload["events"]]
            assert rpms == [1000.0, 2000.0]
            assert payload["events"][0]["odometer"] == 0
            assert payload["events"][1]["odometer"] == 1


async def test_live_stream_disconnects_cleanly_and_does_not_replay(
    live_server: str, clean_db
) -> None:
    """A fresh connection starts its own cursor: no replay, server stays up."""
    async with httpx.AsyncClient(base_url=live_server) as client:
        vehicle_id, headers = await _make_vehicle(live_server, client)
        url = f"{live_server}/api/v1/vehicles/{vehicle_id}/telemetry/stream"
        params = {"interval_seconds": 0.05}

        # Seed one sample a little ahead of wall clock so the first connection
        # (cursor = connect time) sees it as new.
        seed = datetime.now(UTC) + timedelta(seconds=2.5)

        # First connection sees the fresh sample exactly once.
        async with client.stream("GET", url, headers=headers, params=params) as first:
            posted = await client.post(
                f"{live_server}/api/v1/vehicles/{vehicle_id}/telemetry",
                json=telemetry_payload(seed.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), rpm=1212.0),
                headers=headers,
            )
            assert posted.status_code == 201
            payload = json.loads((await _next_data_line(first.aiter_lines()))[5:].strip())
            assert [event["rpm"] for event in payload["events"]] == [1212.0]

        # Wait until wall clock passes the sample's timestamp, then reconnect:
        # the sample is behind the new cursor, so the stream must look idle.
        sample_ts = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
        wait = (sample_ts - datetime.now(UTC)).total_seconds() + 0.5
        if wait > 0:
            await asyncio.sleep(wait)

        async with client.stream("GET", url, headers=headers, params=params) as second:
            lines = second.aiter_lines()
            first_line = await asyncio.wait_for(anext(lines), timeout=15)
            assert first_line == ": ping"

            # The server is still healthy.
            posted = await client.post(
                f"{live_server}/api/v1/vehicles/{vehicle_id}/telemetry",
                json=telemetry_payload(_future_iso(5), rpm=7777.0),
                headers=headers,
            )
            assert posted.status_code == 201
            payload = json.loads((await _next_data_line(lines))[5:].strip())
            assert [event["rpm"] for event in payload["events"]] == [7777.0]
