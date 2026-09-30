import uuid
from datetime import UTC, datetime, timedelta

import httpx


def telemetry_payload(timestamp: str, **overrides: object) -> dict:
    payload = {
        "timestamp": timestamp,
        "rpm": 3200,
        "speed": 74.0,
        "engine_load": 82.4,
        "coolant_temperature": 104.2,
        "oil_temperature": 97.0,
        "battery_voltage": 12.1,
        "fuel_level": 64.0,
        "intake_air_temperature": 32.0,
        "throttle_position": 41.0,
        "engine_runtime": 1820,
        "odometer": 42150.2,
        "raw_payload": {},
    }
    payload.update(overrides)
    return payload


def iso(hours_ago: int) -> str:
    dt = datetime.now(UTC) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


async def test_create_telemetry(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    vehicle_id = sample_vehicle["id"]

    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", json=telemetry_payload(iso(0))
    )

    assert response.status_code == 201
    body = response.json()
    assert body["vehicle_id"] == vehicle_id
    assert body["rpm"] == 3200
    assert body["speed"] == 74.0
    assert body["raw_payload"] == {}
    assert "id" in body
    assert "created_at" in body


async def test_create_telemetry_nonexistent_vehicle(auth_client: httpx.AsyncClient) -> None:

    response = await auth_client.post(
        f"/api/v1/vehicles/{uuid.uuid4()}/telemetry", json=telemetry_payload(iso(0))
    )

    assert response.status_code == 404


async def test_create_telemetry_validation_error(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/telemetry",
        json=telemetry_payload(iso(0), rpm=-10),
    )

    assert response.status_code == 422


async def test_list_telemetry_newest_first(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    for hours_ago in (3, 2, 1):
        assert (
            await auth_client.post(
                f"/api/v1/vehicles/{vehicle_id}/telemetry",
                json=telemetry_payload(iso(hours_ago), rpm=float(hours_ago * 1000)),
            )
        ).status_code == 201

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/telemetry")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    rpms = [item["rpm"] for item in body["items"]]
    assert rpms == sorted(rpms)


async def test_list_telemetry_pagination(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    for hours_ago in (5, 4, 3):
        assert (
            await auth_client.post(
                f"/api/v1/vehicles/{vehicle_id}/telemetry",
                json=telemetry_payload(iso(hours_ago), rpm=float(hours_ago * 100)),
            )
        ).status_code == 201

    page1 = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", params={"page": 1, "page_size": 2}
    )
    page2 = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", params={"page": 2, "page_size": 2}
    )

    assert page1.status_code == 200
    assert page1.json()["total"] == 3
    assert len(page1.json()["items"]) == 2
    assert page2.json()["total"] == 3
    assert len(page2.json()["items"]) == 1


async def test_list_telemetry_time_filtering(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    t1, t2, t3 = iso(3), iso(2), iso(1)
    for ts in (t1, t2, t3):
        assert (
            await auth_client.post(
                f"/api/v1/vehicles/{vehicle_id}/telemetry",
                json=telemetry_payload(ts),
            )
        ).status_code == 201

    only_window = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry",
        params={"start_time": t2, "end_time": t3},
    )
    assert only_window.status_code == 200
    assert only_window.json()["total"] == 2

    upper_only = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", params={"end_time": t1}
    )
    assert upper_only.status_code == 200
    assert upper_only.json()["total"] == 1

    lower_only = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", params={"start_time": t2}
    )
    assert lower_only.status_code == 200
    assert lower_only.json()["total"] == 2


async def test_list_telemetry_nonexistent_vehicle(auth_client: httpx.AsyncClient) -> None:

    response = await auth_client.get(f"/api/v1/vehicles/{uuid.uuid4()}/telemetry")

    assert response.status_code == 404


async def test_create_telemetry_requires_auth(
    client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/telemetry", json=telemetry_payload(iso(0))
    )

    assert response.status_code == 401


async def test_cross_user_telemetry_denied(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    """A non-owner cannot read or write another user's telemetry (404)."""
    vehicle_id = sample_vehicle["id"]

    read = await other_user_client.get(f"/api/v1/vehicles/{vehicle_id}/telemetry")
    assert read.status_code == 404

    write = await other_user_client.post(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", json=telemetry_payload(iso(0))
    )
    assert write.status_code == 404
