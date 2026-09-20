import httpx


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "digital-twin-api"}


async def test_database_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/db")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "digital-twin-api"
    assert body["database"] == "ok"
