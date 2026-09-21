# Digital Twin — Car Health Monitoring Platform (Backend)

Production-oriented FastAPI backend for the Digital Twin car health monitoring
platform. **Phase 2** adds an MQTT telemetry ingestion pipeline on top of the
Phase 1 foundation: a deterministic vehicle simulator publishes telemetry
envelopes through a Mosquitto broker, an MQTT subscriber validates and stores
them in PostgreSQL. **Phase 3** adds a deterministic, explainable **Vehicle
Health Context** engine that analyses a configurable historical telemetry
window (statistics → trends → baselines → rules → health score → confidence),
persists every analysis as an immutable snapshot in PostgreSQL, and exposes
it through a REST API.

## 1. Project overview

Vehicles emit OBD-II telemetry collected over MQTT and exposed through a REST
API. A later context engine and LLM reasoning layer will consume the stored
telemetry to produce diagnoses and recommendations; the layers implemented so
far provide the durable, ingestion-agnostic foundation for that.

Phase 2 delivers the long-lived ingestion path:

```
Vehicle Simulator  --publish-->  Mosquitto broker  --deliver-->  MQTT Subscriber
        (deterministic state machine,          (validates, deduplicates,
         QoS 1, retain=false)                    reuses service/repository)
                                                                   |
                                                                   v
                                                          PostgreSQL
```

REST API (`POST /api/v1/vehicles/{id}/telemetry`) remains a first-class
ingestion path and shares the exact same `TelemetryService` → `TelemetryRepository`
code the MQTT subscriber uses.

## 2. Implemented scope

**Phase 1 (foundation):**
- Layered architecture (API → Service → Repository → SQLAlchemy → PostgreSQL)
- Configuration management (pydantic-settings)
- SQLAlchemy 2.x async + asyncpg, Alembic migrations
- `vehicles` and `telemetry_records` tables
- Pydantic v2 schemas with validation
- REST API under `/api/v1`: health, vehicle CRUD, telemetry create/list
- Docker Compose development environment

**Phase 2 (MQTT ingestion):**
- `app/mqtt/` package: topics, envelope schemas, parser, publisher, subscriber
- MQTT envelopes with `schema_version`, `event_id`, `vehicle_id`, `timestamp` and
  validated `telemetry` payload; timezone-aware timestamps enforced
- Idempotent ingestion via `source_event_id` (DB unique constraint per
  vehicle, IntegrityError backstop for concurrent duplicates)
- Deterministic vehicle simulator (`simulator/`) with a driving-state machine
  and correlated, physically plausible sensor values; failure scenarios
  `normal | high_temperature | low_battery | high_engine_load`
- Subscriber with reconnect + exponential backoff, graceful shutdown, and
  bounded retries on transient database failures; malformed/unknown/duplicate
  messages are logged and skipped, never crash the process
- Mosquitto broker configuration (Docker: credentialed dev user; local:
  loopback-only anonymous for testing)
- Docker Compose services: `postgres`, `backend`, `mosquitto`, `mqtt-subscriber`,
  `simulator`
- Makefile targets, `.env.example`, pytest suite (unit + database + real-broker
  e2e), this documentation

**Phase 3 (vehicle health intelligence):**
- `app/intelligence/` deterministic, deterministic context engine — no LLM:
  statistics (`statistics.py`), trends (`trends.py`), vehicle baselines
  (`baselines.py`), rule engine (`rules.py`), scoring + confidence
  (`scoring.py`), context assembly (`context.py`), orchestration (`engine.py`)
- Transport-agnostic typed analysis: the engine consumes
  `TelemetryPoint(timestamp, values)` and never touches the DB/MQTT/API, so it
  works identically for MQTT, REST, replay, tests and historical data
- `vehicle_health_snapshots` table (Alembic migration) stores every generated
  context as JSONB; snapshots are immutable historical evidence — re-analysis
  creates a new snapshot and never mutates old ones
- `VehicleHealthService` loads a configurable analysis window plus a bounded
  historical baseline window and persists the resulting `HealthSnapshot`
- New REST endpoints: `POST /vehicles/{id}/health/analyze`,
  `GET /vehicles/{id}/health`, `GET /vehicles/{id}/health/history`
- Test coverage: pure-intelligence unit tests, repository, service and API
  tests, plus real-broker simulated scenarios validated against the analyzer
- `HEALTH_*` settings (analysis window, minimum samples, expected interval,
  baseline window, baseline minimum samples)

**Not implemented (later phases):** LangGraph/LangChain, LLM calls, RAG,
pgvector/embeddings, ML prediction, dashboard, authentication/JWT, and report
generation.

## 3. Architecture

```
Device / Simulator ──MQTT──> Mosquitto ──MQTT──> mqtt-subscriber
                                                    │
REST API routes ──────────────────────────────────>│
                                                    v
                                     Service layer (telemetry_service)
                                                    │
                                     Repository layer (telemetry_repository)
                                                    │
                                     SQLAlchemy 2.x async ORM
                                                    │
                                                  PostgreSQL
```

Phase 3 adds an analysis path on top of the same layers:

```
REST API (health_analyze) ─> VehicleHealthService
                                  │  window + baseline loading (telemetry_repository)
                                  v
                       HealthAnalysisEngine (app/intelligence)
                          statistics → trends → baselines → rules
                          → scoring → confidence → HealthContext
                                  │
                                  v
                       HealthSnapshotRepository → vehicle_health_snapshots (JSONB)
```

The intelligence engine contains no persistence or transport logic; the
service is the only layer that translates ORM records into typed
`TelemetryPoint` samples.

The subscriber contains no persistence logic: it decodes/validates MQTT
payloads and calls `TelemetryService.create_telemetry()` exactly like the REST
route does. Idempotency lives in the service; the unique
`(vehicle_id, source_event_id)` index is the DB-level backstop.

## 4. Technology stack

| Area             | Choice                            |
| ---------------- | --------------------------------- |
| Language         | Python 3.12+                      |
| Web              | FastAPI, Uvicorn                  |
| Validation       | Pydantic v2, pydantic-settings    |
| ORM              | SQLAlchemy 2.x (async), asyncpg   |
| Migrations       | Alembic                           |
| MQTT client      | aiomqtt 2.x (asyncio wrapper over paho-mqtt) |
| Broker           | Mosquitto (Docker / local)        |
| Database         | PostgreSQL 16+                    |
| Tests            | pytest, pytest-asyncio, httpx     |
| Lint/format      | Ruff                              |
| Container        | Docker, Docker Compose            |

## 5. Directory structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI app, lifespan, exception handlers, CORS
│   ├── api/
│   │   ├── router.py
│   │   └── routes/
│   │       ├── health.py        ├── vehicles.py        └── telemetry.py
│   ├── core/
│   │   ├── config.py            # Settings (env / .env) incl. MQTT_*
│   │   ├── database.py          # Async engine + session factory + health probe
│   │   ├── exceptions.py        ├── logging.py
│   ├── mqtt/                    # Phase 2 ingestion package
│   │   ├── topics.py            # Topic build/parse (single source of truth)
│   │   ├── schemas.py           # TelemetryMessage / StatusMessage envelopes
│   │   ├── parser.py            # Decode + validate payloads
│   │   ├── publisher.py         # Long-lived MQTTPublisher
│   │   ├── subscriber.py        # Reconnect/backoff loop + `python -m` entry
│   │   ├── client.py            # aiomqtt client factory + asyncio loop helpers
│   │   └── exceptions.py
│   ├── intelligence/             # Phase 3 health engine (no LLM, pure + typed)
│   │   ├── models.py             # HealthContext, MetricStatistics, Finding, ...
│   │   ├── statistics.py         # Robust summary statistics (never NaN/Inf)
│   │   ├── trends.py             # OLS slope + normalized slope (direction/strength)
│   │   ├── baselines.py          # Median + scaled MAD vs. window last value
│   │   ├── rules.py              # RuleThresholds + HealthRuleEngine
│   │   ├── scoring.py            # Health score + status + confidence model
│   │   ├── context.py            # HealthContext assembly
│   │   └── engine.py             # HealthAnalysisEngine pipeline
│   ├── models/  ├── schemas/  ├── repositories/  ├── services/
│   └── dependencies/
├── simulator/                   # Phase 2 vehicle simulator
│   ├── config.py                # SIMULATOR_* + shared MQTT_* settings
│   ├── vehicle.py               # DrivingState + VehicleState
│   ├── telemetry_generator.py   # State machine + physical sensor model
│   ├── publisher.py             # Reuses app.mqtt.publisher.MQTTPublisher
│   └── main.py                  # `python -m simulator.main` entry
├── scripts/
│   └── seed_demo_vehicle.py     # Idempotently seed the demo vehicle
├── infrastructure/mosquitto/
│   ├── mosquitto.conf           # Docker (credentialed) broker config
│   ├── mosquitto.acl            # Dev ACL (vehicles/#)
│   └── mosquitto.local.conf     # Loopback anonymous config for local dev
├── alembic/                     # Versions, async env, script.py.mako
├── tests/
│   ├── conftest.py              # Test DB, engine, client, clean-state fixtures
│   ├── api/  ├── services/  ├── mqtt/  └── simulator/
├── .env.example  alembic.ini  Dockerfile  docker-compose.yml  Makefile
├── pyproject.toml  README.md
```

## 6. Environment setup

Prerequisites: Python 3.12+, PostgreSQL 16+, an MQTT broker (either local
Mosquitto or Docker).

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -e ".[dev]"     # or: make install
```

Copy the environment template and adjust it for your setup:

```bash
cp .env.example .env
```

`.env` is git-ignored and must never contain production secrets. The API fails
clearly at startup if `DATABASE_URL` is missing; the simulator fails clearly if
`SIMULATOR_VEHICLE_ID` is missing. All values can be supplied as real
environment variables.

`HEALTH_ANALYSIS_WINDOW_MINUTES`/`HEALTH_MINIMUM_SAMPLES`/`HEALTH_EXPECTED_INTERVAL_SECONDS`/
`HEALTH_BASELINE_WINDOW_MINUTES`/`HEALTH_BASELINE_MINIMUM_SAMPLES` (see
`.env.example`).

## 7. MQTT message format

### Telemetry envelope (published by the simulator on `vehicles/{id}/telemetry`)

```json
{
  "schema_version": 1,
  "event_id": "a1b2c3d4e5f60718",
  "vehicle_id": "11111111-2222-4333-8444-555555555555",
  "timestamp": "2026-09-20T10:00:00.123456+00:00",
  "telemetry": {
    "rpm": 2145.3,
    "speed": 61.2,
    "engine_load": 34.0,
    "coolant_temperature": 91.2,
    "oil_temperature": 88.1,
    "battery_voltage": 13.94,
    "fuel_level": 74.96,
    "intake_air_temperature": 33.4,
    "throttle_position": 19.1,
    "engine_runtime": 1820.5,
    "odometer": 45232.1
  }
}
```

- Published with QoS 1, `retain=false`.
- `event_id` must be unique per vehicle; the subscriber stores it as
  `source_event_id` and skips duplicates.
- `timestamp` must be timezone-aware; naive timestamps are rejected.
- Unknown fields and out-of-range values (e.g. `battery_voltage > 40`,
  `fuel_level > 100`) cause the message to be discarded and logged.

### Status envelope (on `vehicles/{id}/status`)

```json
{
  "vehicle_id": "11111111-2222-4333-8444-555555555555",
  "status": "online",
  "timestamp": "2026-09-20T10:00:00+00:00"
}
```

The simulator announces `online` at start and `offline` on graceful shutdown.
Status messages are informational and are not persisted in this phase.

## 8. Local development (no Docker)

Prerequisites: mqtt client engine ready (aiomqtt installed), a local Mosquitto
binary, and PostgreSQL running.

```bash
alembic upgrade head                    # apply migrations (or: make migrate)

# 1) Start a local broker (loopback, anonymous, for development only):
mosquitto -c infrastructure/mosquitto/mosquitto.local.conf

# 2) Terminal A - API:
uvicorn app.main:app --reload           # or: make dev

# 3) Terminal B - subscriber:
python -m app.mqtt.subscriber           # or: make mqtt-subscriber

# 4) Seed the demo vehicle and run the simulator:
python -m scripts.seed_demo_vehicle     # or: make seed-demo-vehicle
python -m simulator.main                # or: make simulator
```

Watch the subscriber log lines appear as telemetry reaches the database:

```bash
# Telemetry arriving via MQTT:
curl "http://localhost:8000/api/v1/vehicles/11111111-2222-4333-8444-555555555555/telemetry?page_size=3"
```

The simulator's scenario/interval/seed can be changed with `SIMULATOR_*`
environment variables, e.g.:

```bash
$env:SIMULATOR_SCENARIO="high_temperature"
$env:SIMULATOR_INTERVAL_SECONDS="0.5"
python -m simulator.main
```

## 9. Docker development (full Phase 2 stack)

```bash
docker compose up --build -d    # or: make up
docker compose logs -f          # or: make logs
docker compose down             # or: make down
```

This starts:

| Service          | Purpose                                        | Host port   |
| ---------------- | ---------------------------------------------- | ----------- |
| `postgres`       | PostgreSQL 16 (healthchecked, named volume)    | `5432`      |
| `backend`        | FastAPI API; runs migrations then serves       | `8000`      |
| `mosquitto`      | MQTT broker (credentialed dev user, healthchecked) | `1883`  |
| `mqtt-subscriber`| Validates + persists MQTT telemetry           | —           |
| `simulator`      | Publishes telemetry for the demo vehicle       | —           |

The broker's password file is generated at container start from
`MQTT_USERNAME`/`MQTT_PASSWORD` (Compose defaults `mqtt`/`mqtt` — development
only). Credentials are not committed; the dev passwd hash is created inside the
container. Simulator defaults to the seeded demo vehicle id
`11111111-2222-4333-8444-555555555555`.

> **Note:** the `backend`, `mqtt-subscriber` and `simulator` services share one
> image built from the repo root `Dockerfile`. `subscriptions` will reconnect
> forever if the broker is down, and restart (unless-stopped) if the container
> itself dies.

## 11. Database schema & migrations

Migrations are autogenerated from the SQLAlchemy models.

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head            # or: make migrate
alembic downgrade -1
```

The schema is controlled exclusively by Alembic — the application never calls
`create_all()` at startup.

Phase 2 telemetry migration (`<revision>_add_source_event_id...`):

- adds nullable `telemetry_records.source_event_id` (existing rows unaffected)
- adds a **partial unique index** `(vehicle_id, source_event_id)` where
  `source_event_id IS NOT NULL` — one event id per vehicle, while historical
  rows without an event id remain valid
- `downgrade` drops the index and column

`TelemetryCreate` (REST) accepts an optional `source_event_id`, so REST and
MQTT ingestion share the same idempotency semantics.

Phase 3 health migration (`a1b2c3d4e5f6_create_vehicle_health_snapshots`):

- creates `vehicle_health_snapshots` with the full generated context in
  `context_json` (JSONB) plus queryable top-level columns
  (`health_score`, `health_status`, `confidence`, `window_*`, `sample_count`)
- foreign key `vehicle_id → vehicles.id` with `ON DELETE CASCADE`
- composite indexes `(vehicle_id, generated_at)` and
  `(vehicle_id, health_status, generated_at)`
- `downgrade` drops the table

## 12. Vehicle Health Context (Phase 3)

Analysis is only ever triggered explicitly — there is no scheduler, no
long-running job, and no background worker. Anyone can request a health
snapshot at any time for any vehicle.

### Analysis pipeline (deterministic, explainable)

```
window + baseline telemetry (PostgreSQL)
   -> HealthAnalysisEngine
        statistics  robust mean/median/min/max/IQR/std-dev/CV per metric
        trends      OLS slope + normalized slope -> increasing/decreasing/stable
        baselines   median + 1.4826*MAD of the vehicle's own history
                    -> within / elevated / depressed (|dev| > 2.0)
        rules       configured thresholds -> factual findings (never a diagnosis)
        scoring     100 - penalties (info=0, warning=10, critical=30), 40/category cap
        confidence  data-quality confidence in the ASSESSMENT (not health probability)
   -> HealthContext (typed, versioned, JSON-serialisable)
```

Each rule finding states what the telemetry shows (e.g. "coolant temperature
is significantly elevated") — never a mechanical diagnosis ("water pump
failed"). Rule thresholds are centralized in
`app/intelligence/rules.py::RuleThresholds` and are documented in the product
flow as configurable.

### Health score & status

- Score starts at 100; each finding deducts `info=0 / warning=10 / critical=30`,
  per-category penalties capped at 40 so no single discipline can dominate.
- Status: `score ≥ 80 → healthy`, `60 ≤ score < 80 → attention`,
  `< 60 → critical`; insufficient data (`< HEALTH_MINIMUM_SAMPLES`) → `unknown`.
- `confidence` (0–1) measures confidence *in the telemetry-based assessment*
  (coverage, duration, sample sufficiency, metric completeness) — explicitly
  NOT the probability that the vehicle is healthy.

### Health endpoints

| Method | Path                                        | Description                             |
| ------ | ------------------------------------------- | --------------------------------------- |
| POST   | `/api/v1/vehicles/{id}/health/analyze`      | Analyze a window, persist, return context (optional `window_minutes` 1–1440) |
| GET    | `/api/v1/vehicles/{id}/health`              | Latest persisted context (404 if none)  |
| GET    | `/api/v1/vehicles/{id}/health/history`      | Paginated history (newest first, time filter) |

```bash
# Analyze the last 15 minutes (default) of the demo vehicle:
curl -X POST http://localhost:8000/api/v1/vehicles/11111111-2222-4333-8444-555555555555/health/analyze

# ...or an explicit 5-minute window:
curl -X POST "http://localhost:8000/api/v1/vehicles/<vehicle_id>/health/analyze?window_minutes=5"

# Latest context + history:
curl http://localhost:8000/api/v1/vehicles/<vehicle_id>/health
curl "http://localhost:8000/api/v1/vehicles/<vehicle_id>/health/history?page=1&page_size=20"
```

The `window_minutes` default comes from `HEALTH_ANALYSIS_WINDOW_MINUTES`
(15 default). Baseline history is loaded from the `HEALTH_BASELINE_WINDOW_MINUTES`
(6 h default) immediately before the analysis window.

## 13. Running tests

```bash
set TEST_DATABASE_URL=postgresql+asyncpg://postgres:root@localhost:5432/digital_twin_test

pytest                    # or: make test        (skips broker e2e)
pytest -m mqtt_e2e        # or: make mqtt-test   (requires a running broker)
```

The suite:

- creates/uses `digital_twin_test`, builds the schema from models, truncates
  between tests, tears down afterwards
- **unit**: MQTT topic build/parse, envelope validation (ranges, timezone,
  unknown fields), parser, simulator state-machine/physical invariants, and
  simulator config/env handling; plus `tests/intelligence/` (statistics,
  trends, baselines, rule engine, scoring, engine/context)
- **service/repository**: idempotent ingestion (duplicate `source_event_id`),
  including the concurrent IntegrityError path; health snapshot persistence,
  pagination and `VehicleHealthService` analysis
- **API**: all Phase 1/2 endpoint tests still pass unchanged; Phase 3 health
  analysis/latest/history endpoint tests
- **subscriber (mocked MQTT)**: valid → persisted; duplicate → skipped;
  invalid JSON / envelope/topic mismatch / unknown vehicle → skipped without
  raising
- **e2e (`mqtt_e2e`)**: publishes a real envelope to a real broker and asserts
  the record lands in PostgreSQL; skips gracefully when no broker is reachable

## 14. Linting / formatting

```bash
ruff check .                 # or: make lint
ruff format .                # fix + format: make format
```

## 15. API documentation

Interactive docs are served by FastAPI:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

### Endpoints

| Method | Path                                  | Description                        |
| ------ | ------------------------------------- | ---------------------------------- |
| GET    | `/api/v1/health`                      | Liveness (no DB touch)             |
| GET    | `/api/v1/health/db`                   | Database reachability (`SELECT 1`) |
| GET    | `/api/v1/vehicles`                    | List vehicles (paginated)          |
| POST   | `/api/v1/vehicles`                    | Create vehicle (201)               |
| GET    | `/api/v1/vehicles/{id}`               | Get vehicle                        |
| PATCH  | `/api/v1/vehicles/{id}`               | Update mutable metadata            |
| DELETE | `/api/v1/vehicles/{id}`               | Delete vehicle (cascade telemetry) |
| GET    | `/api/v1/vehicles/{id}/telemetry`     | List telemetry (paginated, time filter) |
| POST   | `/api/v1/vehicles/{id}/telemetry`     | Store a telemetry sample (201)     |
| POST   | `/api/v1/vehicles/{id}/health/analyze`| Analyze + persist a health snapshot (window_minutes 1–1440) |
| GET    | `/api/v1/vehicles/{id}/health`        | Latest persisted health context     |
| GET    | `/api/v1/vehicles/{id}/health/history`| Paginated health snapshot history   |

All routes are versioned under `/api/v1`.

## 16. Example API requests

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

# Store telemetry for a vehicle (optional source_event_id enables idempotency)
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
    "source_event_id": "optional-unique-per-vehicle"
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

## 17. Simulator behavior

The simulator cycles the vehicle through a deterministic drive cycle at a fixed
interval:

```
OFF (2s) → STARTING (3s) → IDLE (10s) → ACCELERATING (15s) →
CRUISING (30s) → DECELERATING (10s) → IDLE → ... (repeat)
```

Durations, cruise speed, seed and scenario are configurable via `SIMULATOR_*`.
Sensor values are correlated with the driving state (rpm/speed/throttle/load
track each phase) and a seeded RNG makes every run with the same seed
reproducible.

Fault scenarios:

| Scenario          | Effect                                            | Health finding                        |
| ----------------- | ------------------------------------------------ | ------------------------------------- |
| `normal`          | Nominal operating ranges                         | `<healthy>` (no critical/warning rules)|
| `high_temperature`| Coolant/oil targets climb (~115 °C coolant)      | `COOLANT_TEMP_HIGH` critical, `OIL_TEMP_HIGH`, rapid-rise |
| `low_battery`     | Running/battery set-points collapse (~11.9 V)    | `BATTERY_VOLTAGE_LOW` warning          |
| `high_engine_load`| Engine load biased up to 100%                    | `ENGINE_LOAD_HIGH` warning             |

Physical invariants: fuel only decreases while running, odometer only
increases with speed, engine runtime only accumulates while not `OFF`.

## 18. Error semantics

| HTTP | Meaning                       |
| ---- | ----------------------------- |
| 404  | Resource does not exist       |
| 409  | Conflict (e.g. duplicate VIN) |
| 422  | Request validation failed     |
| 500  | Unexpected server failure     |

Internal database errors are logged and never exposed to clients. On the MQTT
path, malformed/unknown/duplicate messages are logged and skipped; transient
DB errors are retried a bounded number of times (see
`MQTT_MESSAGE_RETRY_ATTEMPTS`).

## 19. Intentionally not implemented (yet)

- LangGraph supervisor agent (Phase 4), manufacturer manual RAG (Phase 5),
  LLM diagnostics (Phase 6), PDF reports (Phase 7), Next.js dashboard
  (Phase 8).
- The Phase 3 health engine is fully deterministic: no LLM, no ML, and no
  prior/manual data are used anywhere in the analysis pipeline.
- Authentication/JWT, pgvector/embeddings, anomaly analytics, and any
  TimescaleDB-specific behaviour.