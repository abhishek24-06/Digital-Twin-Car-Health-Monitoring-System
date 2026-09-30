import uuid

import httpx

from tests.conftest import unique_vin


def vehicle_payload(**overrides: object) -> dict:
    payload = {
        "vin": unique_vin(),
        "make": "Toyota",
        "model": "Camry",
        "year": 2024,
        "engine_type": "2.5L Petrol",
    }
    payload.update(overrides)
    return payload


async def test_create_vehicle(auth_client: httpx.AsyncClient, auth_user: dict) -> None:
    payload = vehicle_payload()

    response = await auth_client.post("/api/v1/vehicles", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["vin"] == payload["vin"].upper()
    assert body["make"] == "Toyota"
    assert body["model"] == "Camry"
    assert body["year"] == 2024
    assert body["engine_type"] == "2.5L Petrol"
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body
    assert body["owner_user_id"] == auth_user["id"]
    assert body["source_type"] == "simulator"
    assert body["status"] == "active"
    assert body["simulation_enabled"] is False


async def test_create_vehicle_allows_missing_engine_type(auth_client: httpx.AsyncClient) -> None:
    payload = vehicle_payload(engine_type=None)

    response = await auth_client.post("/api/v1/vehicles", json=payload)

    assert response.status_code == 201
    assert response.json()["engine_type"] is None


async def test_create_vehicle_validation_error(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post("/api/v1/vehicles", json=vehicle_payload(year=1600))

    assert response.status_code == 422


async def test_create_vehicle_rejects_privilege_escalation_fields(
    auth_client: httpx.AsyncClient,
) -> None:
    """Clients may not set owner/lifecycle fields on create (extra=forbid)."""
    response = await auth_client.post(
        "/api/v1/vehicles",
        json=vehicle_payload(owner_user_id=str(uuid.uuid4()), source_type="real"),
    )

    assert response.status_code == 422


async def test_create_vehicle_duplicate_vin_conflict(auth_client: httpx.AsyncClient) -> None:
    vin = unique_vin()
    first = await auth_client.post("/api/v1/vehicles", json=vehicle_payload(vin=vin))
    assert first.status_code == 201

    second = await auth_client.post("/api/v1/vehicles", json=vehicle_payload(vin=vin))

    assert second.status_code == 409


async def test_get_vehicle(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await auth_client.get(f"/api/v1/vehicles/{sample_vehicle['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == sample_vehicle["id"]


async def test_get_vehicle_not_found(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get(f"/api/v1/vehicles/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_list_vehicles_only_own(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    """The ordinary user only sees their own vehicles."""
    for _ in range(3):
        assert (
            await auth_client.post("/api/v1/vehicles", json=vehicle_payload())
        ).status_code == 201
    assert (
        await other_user_client.post("/api/v1/vehicles", json=vehicle_payload())
    ).status_code == 201

    response = await auth_client.get("/api/v1/vehicles")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


async def test_list_vehicles_defaults(auth_client: httpx.AsyncClient) -> None:
    for _ in range(3):
        assert (
            await auth_client.post("/api/v1/vehicles", json=vehicle_payload())
        ).status_code == 201

    response = await auth_client.get("/api/v1/vehicles")

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 3
    assert len(body["items"]) == 3


async def test_list_vehicles_pagination(auth_client: httpx.AsyncClient) -> None:
    for _ in range(5):
        assert (
            await auth_client.post("/api/v1/vehicles", json=vehicle_payload())
        ).status_code == 201

    response = await auth_client.get("/api/v1/vehicles", params={"page": 2, "page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["total"] == 5
    assert len(body["items"]) == 2


async def test_list_vehicles_rejects_invalid_pagination(auth_client: httpx.AsyncClient) -> None:
    assert (await auth_client.get("/api/v1/vehicles", params={"page": 0})).status_code == 422
    assert (await auth_client.get("/api/v1/vehicles", params={"page_size": 0})).status_code == 422
    assert (await auth_client.get("/api/v1/vehicles", params={"page_size": 101})).status_code == 422


async def test_update_vehicle(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await auth_client.patch(
        f"/api/v1/vehicles/{sample_vehicle['id']}",
        json={"make": "Honda", "year": 2025},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["make"] == "Honda"
    assert body["year"] == 2025
    assert body["model"] == sample_vehicle["model"]
    assert body["vin"] == sample_vehicle["vin"]


async def test_update_vehicle_cannot_change_vin(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    """VIN (and any other unlisted field) is rejected outright, not ignored."""
    response = await auth_client.patch(
        f"/api/v1/vehicles/{sample_vehicle['id']}", json={"vin": "CHANGED00000000000"}
    )

    assert response.status_code == 422


async def test_update_vehicle_cannot_change_ownership(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.patch(
        f"/api/v1/vehicles/{sample_vehicle['id']}",
        json={"owner_user_id": str(uuid.uuid4()), "status": "disabled"},
    )

    assert response.status_code == 422


async def test_update_vehicle_not_found(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.patch(f"/api/v1/vehicles/{uuid.uuid4()}", json={"make": "Honda"})

    assert response.status_code == 404


async def test_delete_vehicle(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await auth_client.delete(f"/api/v1/vehicles/{sample_vehicle['id']}")

    assert response.status_code == 204
    assert (await auth_client.get(f"/api/v1/vehicles/{sample_vehicle['id']}")).status_code == 404


async def test_delete_vehicle_not_found(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.delete(f"/api/v1/vehicles/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_auth_required(client: httpx.AsyncClient) -> None:
    """Without a bearer token every vehicle endpoint is 401."""
    assert (await client.get("/api/v1/vehicles")).status_code == 401
    assert (await client.post("/api/v1/vehicles", json=vehicle_payload())).status_code == 401
    assert (await client.get(f"/api/v1/vehicles/{uuid.uuid4()}")).status_code == 401
