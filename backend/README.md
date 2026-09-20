# Digital Twin — Car Health Monitoring Platform (Backend)

Production-oriented FastAPI backend for the Digital Twin car health monitoring
platform. **Phase 1** delivers the backend foundation only: vehicle registry,
raw telemetry storage, and a health-checked, containerised development
environment.

## 1. Project overview

Vehicles emit OBD-II telemetry that is eventually consumed by a context engine
and an LLM reasoning layer to produce diagnoses and recommendations. Phase 1
stands up the durable foundation those later phases build on: a layered FastAPI
service backed by PostgreSQL.

## 2. Phase 1 scope

- Project structure (layered: API → Service → Repository → SQLAlchemy → PostgreSQL)
- Configuration management (pydantic-settings)
- PostgreSQL integration (SQLAlchemy 2.x async, asyncpg)
- Alembic migrations
- `vehicles` and `telemetry_records` tables
- Pydantic v2 request/response schemas with validation
- Repository and service layers
- REST API under `/api/v1` with health checks
- Docker Compose development environment
- pytest test suite (PostgreSQL-based, self-contained via `TEST_DATABASE_URL`)
- This documentation

**Not implemented (later phases):** MQTT, OBD-II integration, vehicle
simulator, LangGraph/LangChain, LLM calls, RAG, pgvector, embeddings, ML
prediction, dashboard, authentication/JWT, and report generation. The API and
service layers are designed so these can be added without restructuring.

## 3. Architecture

```
Vehicle API / Telemetry API (FastAPI routes)
        ↓
  Service layer (business logic, transaction boundary)
        ↓
  Repository layer (data access)
        ↓
  SQLAlchemy 2.x async ORM
        ↓
      PostgreSQL
```

Future telemetry ingestion (e.g. an MQTT subscriber) can call
`TelemetryService.create_telemetry()` directly, reusing the same service and
repository layers without touching the API layer.

## 4. Technology stack

| Area        | Choice                       |
| ----------- | ---------------------------- |
| Language    | Python 3.12+                 |
| Web         | FastAPI, Uvicorn             |
| Validation  | Pydantic v2, pydantic-settings |
| ORM         | SQLAlchemy 2.x (async), asyncpg |
| Migrations  | Alembic                      |
| Database    | PostgreSQL 16+               |
| Tests       | pytest, pytest-asyncio, httpx |
| Lint/format | Ruff                         |
| Container   | Docker, Docker Compose       |

## 5. Directory structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI app, lifespan, exception handlers, CORS
│   ├── api/
│   │   ├── router.py           # Central router (prefix /api/v1)
│   │   └── routes/
│   │       ├── health.py
│   │       ├── vehicles.py
│   │       └── telemetry.py
│   ├── core/
│   │   ├── config.py           # Settings (env / .env)
│   │   ├── database.py         # Async engine + session factory + health probe
│   │   ├── exceptions.py       # NotFoundError, ConflictError, DatabaseError, AppError
│   │   └── logging.py
│   ├── models/
│   │   ├── base.py             # DeclarativeBase, UUID + timestamp mixins
│   │   ├── vehicle.py
│   │   └── telemetry.py
│   ├── schemas/
│   │   ├── common.py           # PaginatedResponse
│   │   ├── vehicle.py
│   │   ├── telemetry.py
│   │   └── health.py
│   ├── repositories/
│   │   ├── vehicle_repository.py
│   │   └── telemetry_repository.py
│   ├── services/
│   │   ├── vehicle_service.py
│   │   └── telemetry_service.py
│   └── dependencies/
│       └── database.py         # get_db + service/repository providers
├── alembic/
│   ├── versions/               # Migrations
│   ├── env.py                  # Async-aware Alembic environment
│   └── script.py.mako
├── tests/
│   ├── conftest.py             # Test DB, engine, client, clean-state fixtures
│   ├── api/                    # Health, vehicles, telemetry endpoint tests
│   └── services/               # Service + repository layer tests
├── .env.example
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── README.md
```

## 6. Environment setup

Prerequisites: Python 3.12+, PostgreSQL 16+ (local or via Docker).

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -e ".[dev]"     # or: make install
```

Copy the environment template and adjust `DATABASE_URL` for your setup:

```bash
cp .env.example .env
```

`.env` is git-ignored and must never contain production secrets. All settings
can also be provided as real environment variables; the application fails
clearly at startup if `DATABASE_URL` is missing.

## 7. Local development

```bash
alembic upgrade head        # or: make migrate
uvicorn app.main:app --reload   # or: make dev
```

The API is served at `http://localhost:8000`.

## 8. Docker development

```bash
docker compose up --build   # or: make docker-up
```

This starts:

- `postgres` (PostgreSQL 16) on `:5432` with a named volume and a `pg_isready`
  healthcheck.
- `backend` on `:8000`, which waits for PostgreSQL to be healthy, applies
  Alembic migrations, then serves the API.

```bash
docker compose down         # or: make docker-down
```

The compose file uses development-only credentials (`postgres`/`postgres`);
override via environment/compose values in production.

## 9. Database migrations

Migrations are autogenerated from the SQLAlchemy models.

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
alembic downgrade -1
```

The schema is controlled exclusively by Alembic — the application never calls
`create_all()` at startup. The initial migration creates:

- `vehicles`: UUID PK, unique indexed `vin`, `make`, `model`, `year`,
  nullable `engine_type`, timezone-aware `created_at`/`updated_at`.
- `telemetry_records`: UUID PK, `vehicle_id` FK → `vehicles.id` (ON DELETE
  CASCADE), indexed `timestamp`, nullable OBD-II sensor columns, JSONB
  `raw_payload`, plus composite index `(vehicle_id, timestamp)`.

## 10. Running tests

Tests run against a dedicated PostgreSQL database and are self-contained
(no already-running developer database is required, but PostgreSQL must exist).

```bash
set TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/digital_twin_test
pytest                       # or: make test
```

The test suite creates `digital_twin_test` if it does not exist, builds the
schema, truncates tables between tests, and tears everything down afterwards.

## 11. Linting / formatting

```bash
ruff check .                 # or: make lint
ruff format .                # fix + format: make format
```

## 12. API documentation

Interactive docs are served by FastAPI:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

### Endpoints

| Method | Path                                  | Description                        |
| ------ | ------------------------------------- | ---------------------------------- |
| GET    | `/api/v1/health`                      | Liveness (no DB touch)            |
| GET    | `/api/v1/health/db`                   | Database reachability (`SELECT 1`) |
| GET    | `/api/v1/vehicles`                    | List vehicles (paginated)         |
| POST   | `/api/v1/vehicles`                    | Create vehicle (201)              |
| GET    | `/api/v1/vehicles/{id}`               | Get vehicle                       |
| PATCH  | `/api/v1/vehicles/{id}`               | Update mutable metadata           |
| DELETE | `/api/v1/vehicles/{id}`               | Delete vehicle (cascade telemetry) |
| GET    | `/api/v1/vehicles/{id}/telemetry`     | List telemetry (paginated, time filter) |
| POST   | `/api/v1/vehicles/{id}/telemetry`     | Store a telemetry sample (201)    |

All routes are versioned under `/api/v1`.

## 13. Example API requests

```bash
# Health
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/db

# Create a vehicle
curl -X POST http://localhost:8000/api/v1/vehicles \
  -H "Content-Type: application/json" \
  -d '{
    "vin": "TESTVIN123456789",
    "make": "Toyota",
    "model": "Camry",
    "year": 2024,
    "engine_type": "2.5L Petrol"
  }'

# Store telemetry for a vehicle
curl -X POST http://localhost:8000/api/v1/vehicles/<vehicle_id>/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "2026-09-20T08:30:12Z",
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
    "raw_payload": {}
  }'

# Time-bounded, paginated telemetry
curl "http://localhost:8000/api/v1/vehicles/<vehicle_id>/telemetry?page=1&page_size=50&start_time=2026-09-19T00:00:00Z&end_time=2026-09-20T23:59:59Z"
```

### Paginated response shape

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 100
}
```

## 14. Intentionally not implemented (yet)

- MQTT subscriber and OBD-II simulator (Phase 2) — `TelemetryService` is
  ingestion-agnostic and ready to be called from a subscriber.
- Vehicle Context Engine (Phase 3) — will consume historical telemetry via the
  repository layer.
- LangGraph supervisor agent (Phase 4), manufacturer manual RAG (Phase 5),
  LLM diagnostics (Phase 6), PDF reports (Phase 7), Next.js dashboard
  (Phase 8).
- Authentication/JWT, pgvector/embeddings, and any TimescaleDB-specific
  behaviour.

## 15. Error semantics

| HTTP | Meaning                         |
| ---- | ------------------------------- |
| 404  | Resource does not exist         |
| 409  | Conflict (e.g. duplicate VIN)   |
| 422  | Request validation failed       |
| 500  | Unexpected server failure       |

Internal database errors are logged and never exposed to clients.