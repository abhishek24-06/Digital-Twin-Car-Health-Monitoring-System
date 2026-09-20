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


async def test_create_vehicle(client: httpx.AsyncClient) -> None:
    payload = vehicle_payload()

    response = await client.post("/api/v1/vehicles", json=payload)

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


async def test_create_vehicle_allows_missing_engine_type(client: httpx.AsyncClient) -> None:
    payload = vehicle_payload(engine_type=None)

    response = await client.post("/api/v1/vehicles", json=payload)

    assert response.status_code == 201
    assert response.json()["engine_type"] is None


async def test_create_vehicle_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/vehicles", json=vehicle_payload(year=1600))

    assert response.status_code == 422


async def test_create_vehicle_duplicate_vin_conflict(client: httpx.AsyncClient) -> None:
    vin = unique_vin()
    first = await client.post("/api/v1/vehicles", json=vehicle_payload(vin=vin))
    assert first.status_code == 201

    second = await client.post("/api/v1/vehicles", json=vehicle_payload(vin=vin))

    assert second.status_code == 409


async def test_get_vehicle(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/vehicles", json=vehicle_payload())
    vehicle = created.json()

    response = await client.get(f"/api/v1/vehicles/{vehicle['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == vehicle["id"]


async def test_get_vehicle_not_found(client: httpx.AsyncClient) -> None:
    import uuid

    response = await client.get(f"/api/v1/vehicles/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_list_vehicles_defaults(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        assert (await client.post("/api/v1/vehicles", json=vehicle_payload())).status_code == 201

    response = await client.get("/api/v1/vehicles")

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 3
    assert len(body["items"]) == 3


async def test_list_vehicles_pagination(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        assert (await client.post("/api/v1/vehicles", json=vehicle_payload())).status_code == 201

    response = await client.get("/api/v1/vehicles", params={"page": 2, "page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["total"] == 5
    assert len(body["items"]) == 2


async def test_list_vehicles_rejects_invalid_pagination(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/vehicles", params={"page": 0})).status_code == 422
    assert (await client.get("/api/v1/vehicles", params={"page_size": 0})).status_code == 422
    assert (await client.get("/api/v1/vehicles", params={"page_size": 101})).status_code == 422


async def test_update_vehicle(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/vehicles", json=vehicle_payload())
    vehicle = created.json()

    response = await client.patch(
        f"/api/v1/vehicles/{vehicle['id']}",
        json={"make": "Honda", "year": 2025},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["make"] == "Honda"
    assert body["year"] == 2025
    assert body["model"] == vehicle["model"]
    assert body["vin"] == vehicle["vin"]


async def test_update_vehicle_cannot_change_vin(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/vehicles", json=vehicle_payload())
    vehicle = created.json()

    response = await client.patch(
        f"/api/v1/vehicles/{vehicle['id']}", json={"vin": "CHANGED00000000000"}
    )

    assert response.status_code == 200
    assert response.json()["vin"] == vehicle["vin"]


async def test_update_vehicle_not_found(client: httpx.AsyncClient) -> None:
    import uuid

    response = await client.patch(f"/api/v1/vehicles/{uuid.uuid4()}", json={"make": "Honda"})

    assert response.status_code == 404


async def test_delete_vehicle(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/vehicles", json=vehicle_payload())
    vehicle_id = created.json()["id"]

    response = await client.delete(f"/api/v1/vehicles/{vehicle_id}")

    assert response.status_code == 204
    assert (await client.get(f"/api/v1/vehicles/{vehicle_id}")).status_code == 404


async def test_delete_vehicle_not_found(client: httpx.AsyncClient) -> None:
    import uuid

    response = await client.delete(f"/api/v1/vehicles/{uuid.uuid4()}")

    assert response.status_code == 404
