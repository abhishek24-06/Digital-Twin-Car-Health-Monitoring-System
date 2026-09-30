# Digital Twin — Car Health Monitoring Platform (Backend)

Production-oriented FastAPI backend for the Digital Twin car health monitoring
platform. **Phase 2** adds an MQTT telemetry ingestion pipeline on top of the
Phase 1 foundation: a deterministic vehicle simulator publishes telemetry
envelopes through a Mosquitto broker, an MQTT subscriber validates and stores
them in PostgreSQL. **Phase 3** adds a deterministic, explainable **Vehicle
Health Context** engine that analyses a configurable historical telemetry
window (statistics → trends → baselines → rules → health score → confidence),
persists every analysis as an immutable snapshot in PostgreSQL, and exposes
it through a REST API. **Phase 4** adds an **agentic vehicle reasoning** layer:
a LangGraph supervisor workflow grounds natural-language queries and critical
telemetry events through a controlled Vehicle Context tool and the deterministic
health context, and persists structured diagnoses the LLM can never overwrite.
**Phase 6** adds **identity, roles & vehicle ownership**: JWT access tokens
(PyJWT, HMAC-signed) + rotating, hashed, revocable refresh tokens (bcrypt
password hashing), `user`/`admin` roles, and per-user vehicle ownership with
end-to-end IDOR protection across the vehicle, telemetry, health, agent and RAG
endpoints.

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

**Phase 4 (agentic vehicle reasoning):**
- `app/agent/` LangGraph supervisor workflow
  (`supervisor → reason → validate → persist`): the supervisor gathers the
  vehicle context, the reason node calls the LLM, the validate node grounds
  evidence and clamps severity/confidence, and persist writes the result
- Controlled **Vehicle Context tool** (`app/agent/tools/vehicle_context.py`) —
  the LLM's only view of data: serialized, size-bounded Health Context JSON;
  the model never touches the DB, SQL, or repositories
- Deterministic engine is the source of truth: severity/confidence/score always
  reflect the health context; the LLM's assessed severity is clamped to the
  deterministic severity, confidence to within ±0.2, and fabricated
  rule ids/metrics are dropped with `validation_warnings` (evidence grounding)
- Raw provider errors classified into a taxonomy (`timeout | rate_limit |
  connection | server | auth | bad_request | unknown`); retryable failures use
  exponential backoff; the fallback provider (OpenRouter primary, Groq
  fallback) is built lazily and skipped when unconfigured
- Providers (LangChain `langchain-openai` chat models over the OpenAI-compatible
  Chat Completions API): `openrouter.py`, `groq.py`, plus a deterministic
  `mock.py` used by the entire test suite
- `agent_diagnoses` table (Alembic migration `c7f2e8a1b3d4`) persists every
  grounded diagnosis (JSONB body + queryable severity/confidence/status/provider/
  latency/token columns, no chain-of-thought persisted)
- Triggers: `USER_QUERY`, `CRITICAL_TELEMETRY_EVENT` (with cooldown
  deduplication — repeated rules within `AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS`
  return the existing diagnosis without a new LLM call), and a **no-LLM**
  `DASHBOARD_LOAD` hook
- REST endpoints under `/api/v1/vehicles/{id}/agent`; agent errors map to
  `500/502/503/504` and are never leaked to clients
- Full unit + API test suite (`tests/agent/`) runs on `MockLLMProvider` — no
  real API keys required; live LLM smoke gated behind `RUN_LLM_SMOKE_TEST=true`
  (`scripts/smoke_agent_llm.py` / `make agent-llm-smoke`)

**Phase 5 (manufacturer documentation RAG):**
- `app/rag/` hybrid retrieval stack: structure-aware chunking, plain-text /
  markdown parsing, pgvector dense embeddings (`BAAI/bge-m3`, 1024-dim),
  Postgres FTS lexical (`content_tsv` + GIN), fusion, scope filtering
  (EXACT_VEHICLE > MODEL > MAKE > GENERIC) and reranking
  (`BAAI/bge-reranker-v2-m3`)
- Scaled, versioned corpus: `rag_documents` (unique `canonical_source`),
  immutable `rag_document_versions` (content_hash, embedding_model/dimension,
  chunking_version) and `rag_chunks` (heading_path, page/char offsets,
  frame, `embedding_store vector(1024)` + HNSW cosine index) — Alembic
  migration `4f9d3c2b1a8e`
- Idempotent + atomic ingestion: re-ingesting the same source is a no-op
  (`unchanged v<n>`), never a duplicate version row
- LangGraph integration: the agent's `ManufacturerGuidanceTool` retrieves
  scoped evidence and feeds a citation-backed guidance section into the prompt;
  diagnostics persist `rag_used`, `rag_evidence_count`, `rag_embedding_model`,
  `rag_reranker_model`, `rag_scope` (migration `b8c3e1d4a9f7`)
- Retrieved documents are **data, never instructions**: prompt-injection
  resistance, negative grounding (no results → no claims) and a clean
  RAG-disabled fallback to Phase 4 behaviour are all live-verified
- Read-only admin API (`/api/v1/rag/health`, `/api/v1/rag/search`) + CLI
  (`scripts/ingest_documents.py`, `scripts/query_rag.py`)
- Live verification harness `scripts/phase5_agent_rag_verify.py` (real
  models against Supabase) plus `tests/rag/` (43 test nodes); tests run
  offline on stub adapters unless RAG is explicitly enabled

**Not implemented (later phases):** PDF reports (Phase 7), Next.js dashboard
(Phase 8), ML prediction, TimescaleDB features, vehicle sharing, soft delete.

**Phase 6 (identity, roles & vehicle ownership):**
- `users` table (`role` = `user` | `admin`, bcrypt `password_hash`, active
  flag, timestamps) + `refresh_tokens` table (`SHA-256 token_hash`, expiry,
  revoked_at) — Alembic migration `d6a9b1c2e3f4`
- **Register / login / logout / refresh / me** under `/api/v1/auth`:
  `POST /auth/register` (422 on unknown fields, including `role`/`is_active`
  escalation attempts), `POST /auth/login` (identical 401 for unknown email vs
  wrong password — no account probing), `POST /auth/refresh` (one-time rotating
  refresh tokens stored only as hashes; reuse-after-revocation revokes every
  token for that user), `POST /auth/logout` (idempotent revoke), `GET /auth/me`
- Access JWT (`JWT_SECRET`-signed, `type=access`, short-lived
  `AUTH_ACCESS_TOKEN_MINUTES`) verified by `get_current_user`; the user is
  **re-read from the database on every request** so `is_active`/`role` can't
  be smuggled through a stale token
- **Vehicle ownership**: `vehicles.owner_user_id` (nullable FK, ON DELETE
  SET NULL). All vehicle-family endpoints are scoped via `ensure_vehicle_access`
  (admins bypass; non-owners get 404 so vehicle existence is never leaked):
  vehicles CRUD, telemetry create/list, health analyze/get/history, agent
  query/events/dashboard/diagnoses, and per diagnostic the agent run persists
  the requesting `user_id`
- `GET/PATCH /api/v1/users/me` — self-service profile (only `full_name`
  editable; 422 otherwise)
- RAG admin surface minimum protection: `GET /api/v1/rag/health` is
  admin-only (403 for non-admins), `GET /api/v1/rag/search` requires any
  authenticated user
- Security settings hardened in `app/core/security.py` + config:
  `JWT_SECRET` minimum length, `JWT_ALGORITHM` whitelist, access-token expiry
  bounds; `SecuritySettings` tests in `tests/core/test_security_settings.py`
- New tests: `tests/api/test_auth.py` (flow + rotation + tampering),
  `tests/api/test_authorization.py` (IDOR matrix), plus auth-aware rewrites of
  the vehicle/telemetry/health/agent/RAG suites

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
| Agent            | LangGraph state graph + supervisor pattern (Phase 4) |
| LLM SDK          | LangChain (langchain-openai) over OpenAI-compatible endpoints |
| Migrations       | Alembic                           |
| Auth             | PyJWT (access tokens), bcrypt (password hashes), SHA-256 refresh-token hashes (Phase 6) |
| MQTT client      | aiomqtt 2.x (asyncio wrapper over paho-mqtt) |
| Broker           | Mosquitto (Docker / local)        |
| Database         | PostgreSQL 16+ (local dev) / Supabase managed PostgreSQL (deployment) |
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
│   │       ├── health.py  ├── vehicles.py  ├── telemetry.py
│   │       ├── vehicle_health.py       └── agent.py       # Phase 4 agent API
│   │       ├── auth.py  ├── users.py                      # Phase 6 identity
│   ├── core/
│   │   ├── config.py            # Settings (env / .env) incl. MQTT_* / AUTH_*
│   │   ├── database.py          # Async engine + session factory + health probe
│   │   ├── security.py          # bcrypt + PyJWT helpers (Phase 6)
│   │   ├── exceptions.py        ├── logging.py
│   ├── dependencies/
│   │   ├── auth.py              # get_current_user / require_admin (Phase 6)
│   │   ├── database.py          # service providers incl. auth/user services
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
│   ├── agent/                    # Phase 4 reasoning agent
│   │   ├── config.py  errors.py  triggers.py            # settings + error taxonomy
│   │   ├── schemas.py            # DiagnosisContent, DiagnosisResponse, ...
│   │   ├── determinism.py  grounding.py                 # severity/confidence + evidence
│   │   ├── prompts.py            # system prompt + message builders
│   │   ├── providers/            # base, openrouter, groq, mock, factory
│   │   ├── llm_service.py        # retry + fallback + JSON extraction
│   │   ├── tools/vehicle_context.py                     # LLM's only data view
│   │   ├── state.py  nodes.py  graph.py  service.py     # LangGraph + AgentService
│   ├── models/  ├── schemas/  ├── repositories/  ├── services/
│   │   ├── agent_diagnosis.py  └── agent_diagnosis_repository.py  # Phase 4
│   │   ├── user.py  ├── refresh_token.py               # Phase 6 models
│   │   ├── schemas/auth.py  schemas/user.py            # Phase 6 schemas
│   │   ├── services/auth_service.py  services/vehicle_access.py  # Phase 6
│   └── dependencies/
├── simulator/                   # Phase 2 vehicle simulator
│   ├── config.py                # SIMULATOR_* + shared MQTT_* settings
│   ├── vehicle.py               # DrivingState + VehicleState
│   ├── telemetry_generator.py   # State machine + physical sensor model
│   ├── publisher.py             # Reuses app.mqtt.publisher.MQTTPublisher
│   └── main.py                  # `python -m simulator.main` entry
├── scripts/
│   ├── seed_demo_vehicle.py     # Idempotently seed the demo vehicle
│   └── smoke_agent_llm.py       # Gate-controlled live LLM smoke (Phase 4)
├── infrastructure/mosquitto/
│   ├── mosquitto.conf           # Docker (credentialed) broker config
│   ├── mosquitto.acl            # Dev ACL (vehicles/#)
│   └── mosquitto.local.conf     # Loopback anonymous config for local dev
├── alembic/                     # Versions, async env, script.py.mako
├── tests/
│   ├── conftest.py              # Test DB, engine, client, clean-state fixtures
│   ├── api/  ├── services/  ├── mqtt/  ├── simulator/  └── agent/  # Phase 4 tests
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

Phase 6 auth settings: `JWT_SECRET` (required; at least 32 characters —
startup fails with a clear message if it is missing/short),
`JWT_ALGORITHM` (HS256 default), `AUTH_ACCESS_TOKEN_MINUTES` (default 20),
`AUTH_REFRESH_TOKEN_DAYS` (default 30). See `.env.example`.

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

## 10. Supabase database (Phase 3.5)

Phase 3.5 keeps the existing architecture — FastAPI → Services →
Repositories → SQLAlchemy (async) → asyncpg → Alembic — exactly as is, and
replaces the local PostgreSQL deployment with a **managed Supabase PostgreSQL**
project **purely via configuration**. No `supabase-py`, no Data/REST/Storage/
Auth, no `supabase/migrations/`, no new schema tooling. The application cannot
tell (and does not need to know) whether it talks to local PostgreSQL or
Supabase.

### 10.1 Choosing the connection string

Supabase exposes one PostgreSQL database per project (schema lives in a
dedicated `postgres` login). The **only** supported source is the project's
Connect dialogue:

> Supabase Dashboard → Project Settings → Database → **Connection string** (`URI`)

- **Prefer the Direct connection** — `db.<project-ref>.supabase.co:5432`.
  Choose this if the machine can reach it; it is the closest match to the
  local experience.
- **Fall back to the Session pooler** (`Pooler` + **Session** mode, port
  `5432`) only when the network is IPv4-only and direct connections time out.
- **Do not use Transaction mode.** If it is ever enabled, connections must set
  `asyncpg` `statement_cache_size=0` (not currently configured — avoid the
  mode entirely).
- Supabase requires TLS; asyncpg negotiates it automatically. For explicit,
  verifiable encryption append `?ssl=require` to the URL. (Use `ssl`, not
  `sslmode`: SQLAlchemy's asyncpg dialect forwards URL query parameters as
  connect() keyword arguments, where asyncpg accepts `ssl` but rejects
  `sslmode`.) Never use `ssl=false` or `sslmode=disable` workarounds.

### 10.2 Configuring the app

Put the full connection string in `backend/.env` (already git-ignored) as
`DATABASE_URL`. Nothing else changes:

```bash
# backend/.env  (with the exact string from the Connect dialogue)
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@db.<project-ref>.supabase.co:5432/postgres?ssl=require
```

Or export it as a real environment variable / Compose variable. `.env` and
`.env.*` are git-ignored; real credentials must never be committed. Reports and
logs always redact them.

### 10.3 Verifying connectivity and migrating the schema

The schema is owned exclusively by Alembic, so migration targets Supabase with
the exact same commands used locally:

```bash
make db-check      # independent asyncpg probe; prints server version + TLS
make db-current    # confirm state (empty/new project shows "<base>")
make migrate       # alembic upgrade head  (applies all migrations)
make db-current    # confirm head == d6a9b1c2e3f4
```

`alembic upgrade head` creates `vehicles`, `telemetry_records` (partial unique
index on `(vehicle_id, source_event_id)`), and `vehicle_health_snapshots`
(JSONB + indexes) inside the project's `public` schema.

### 10.4 Data migration decision

The local database currently holds **disposable development/demo data**
(`11` vehicles, `4430` telemetry rows, `16` health snapshots — all produced by
the seed script, the simulator, and manual scenarios). Per Phase 3.5 guidance
this is **CASE A: data is disposable — do not copy it**. Instead:

1. Migrate only the **schema** via `alembic upgrade head` (above).
2. Recreate the demo vehicle and data on Supabase:
   `make seed-demo-vehicle`, then run the simulator (`make simulator`) or the
   REST/health scenario commands to generate fresh telemetry and snapshots.

The local database is left intact; **rollback** is simply pointing
`DATABASE_URL` back at the local server (see 10.7).

### 10.5 Runtime verification on Supabase

```bash
make dev                      # or: .venv\Scripts\uvicorn app.main:app
curl http://localhost:8000/api/v1/health/db    # must report reachable
make mqtt-subscriber          # persists MQTT telemetry into Supabase
make db-check                 # rows appear / TLS stays on
curl -X POST http://localhost:8000/api/v1/vehicles/11111111-2222-4333-8444-555555555555/health/analyze
```

Confirm written rows in Supabase Dashboard → **Table Editor** (`public` schema)
and that the health snapshot round-trips correctly.

### 10.6 Test safety

The automated suite **always runs against the dedicated local test database**
(`digital_twin_test`, driven by `TEST_DATABASE_URL`) and never against
Supabase. `tests/conftest.py` refuses to start if the test URL host looks
hosted (`supabase`/`pooler`), because the fixtures drop and truncate tables.

### 10.7 Rollback plan

| Step | Action |
| ---- | ------ |
| 1 | Stop the API / subscriber / simulator |
| 2 | In `backend/.env`, set `DATABASE_URL` back to `postgresql+asyncpg://postgres:postgres@localhost:5432/digital_twin` |
| 3 | `make db-current` — local upgraded (stays at `d6a9b1c2e3f4`) |
| 4 | `make dev` — everything works against local PostgreSQL again |

No application code was changed during the migration, so nothing else to
revert.

### 10.8 Docker notes

`backend/docker-compose.yml` now reads `DATABASE_URL` as
`${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@postgres:5432/digital_twin}`,
so `DATABASE_URL=... docker compose up` runs the Compose stack against any
managed database. Because the Compose `postgres` service is still wired as a
dependency (and intentionally kept for the fully local stack), it starts and
sits unused in that scenario; start only the services you need
(`docker compose up backend mqtt-subscriber mosquitto simulator`) to avoid it.
The `Dockerfile` needs no changes — it already receives the URL via the
environment.

> Docker runtime verification was not performed because Docker is unavailable
> on the development machine.

### 10.9 Row-level security (RLS) posture

RLS is **not enabled** on the schema in this phase. The backend connects with a
privileged PostgreSQL login and executes authenticated application logic over
SQLAlchemy; enabling RLS adds no protection for this access path. RLS should be
revisited when a public-facing Data API / frontend is introduced, with separate
`authenticated`/`anon` roles and per-row policies. Documented here — not
applied now.

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

Phase 4 agent migration (`c7f2e8a1b3d4_create_agent_diagnoses`):

- creates `agent_diagnoses` with the grounded diagnosis body (`diagnosis` JSONB)
  plus queryable top-level columns (`severity`, `confidence`, `status`,
  `error_code`, `provider`, `model`, `fallback_used`, `latency_ms`,
  `input_tokens`, `output_tokens`, `context_timestamp`)
- foreign key `vehicle_id → vehicles.id` with `ON DELETE CASCADE`
- composite indexes `(vehicle_id, created_at)` and
  `(vehicle_id, trigger_type, created_at)`
- `downgrade` drops the table

Phase 6 identity migration (`d6a9b1c2e3f4_phase6_identity_roles_vehicle_ownership`):

- creates `users` (`role` CHECK `user|admin`, `password_hash`, `is_active`,
  timestamps) and `refresh_tokens` (`token_hash` SHA-256, `expires_at`,
  `revoked_at`, `user_id` FK CASCADE, index on `token_hash`)
- adds nullable `vehicles.owner_user_id` (FK→users ON DELETE SET NULL + index)
  plus non-null `source_type` CHECK `simulator|real` and `status` CHECK
  `active|disabled`, `simulation_enabled BOOLEAN DEFAULT false`
- adds nullable `agent_diagnoses.user_id` (FK→users ON DELETE SET NULL,
  attribution of who triggered each agent run)
- symmetric `downgrade` restores the Phase 5 shape

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

# Live LLM smoke (Phase 4) — requires a real provider key in .env:
RUN_LLM_SMOKE_TEST=true python -m scripts.smoke_agent_llm    # or: make agent-llm-smoke
```

The suite:

- creates/uses `digital_twin_test`, builds the schema from models, truncates
  between tests, tears down afterwards
- **refuses to start** when `TEST_DATABASE_URL` points at a hosted database
  (Supabase/pooler hostnames), protecting production data from the destructive
  fixtures
- **unit**: MQTT topic build/parse, envelope validation (ranges, timezone,
  unknown fields), parser, simulator state-machine/physical invariants, and
  simulator config/env handling; plus `tests/intelligence/` (statistics,
  trends, baselines, rule engine, scoring, engine/context)
- **service/repository**: idempotent ingestion (duplicate `source_event_id`),
  including the concurrent IntegrityError path; health snapshot persistence,
  pagination and `VehicleHealthService` analysis
- **API**: all Phase 1/2 endpoint tests still pass unchanged; Phase 3 health
  analysis/latest/history endpoint tests
- **agent (`tests/agent/`)**: settings, provider factory, error classification
  and retry/fallback routing, deterministic severity/confidence, evidence
  grounding, and the full agent API (query, critical-event dedup, no-LLM
  dashboard, history, latest) — all on `MockLLMProvider`, no real API keys
- **rag (`tests/rag/`)**: chunking/scope/parser unit tests, embedding/reranker
  stub adapters, retrieval select+rerank, service / repository integration
  round-trips, agent guidance-tool units (21) and admin-API contracts — run
  offline on stubs; the pgvector-gated integration tests skip unless a local
  pgvector DB is present and are covered live by
  `scripts/phase5_agent_rag_verify.py`
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
| POST   | `/api/v1/auth/register`               | Create a `user` account (201)      |
| POST   | `/api/v1/auth/login`                  | Exchange email/password for tokens |
| POST   | `/api/v1/auth/refresh`                | Rotate a refresh token (one-time)  |
| POST   | `/api/v1/auth/logout`                 | Revoke the refresh token (204)     |
| GET    | `/api/v1/auth/me`                     | Current user profile (401 guard)   |
| GET    | `/api/v1/users/me`                    | Get my profile (Auth required)     |
| PATCH  | `/api/v1/users/me`                    | Update `full_name` (Auth required) |
| GET    | `/api/v1/vehicles`                    | List my vehicles (paginated)       |
| POST   | `/api/v1/vehicles`                    | Create vehicle owned by me (201)   |
| GET    | `/api/v1/vehicles/{id}`               | Get vehicle (owner/admin only)     |
| PATCH  | `/api/v1/vehicles/{id}`               | Update mutable metadata (owner/admin only; `vin`/security fields 422) |
| DELETE | `/api/v1/vehicles/{id}`               | Delete vehicle — cascade telemetry (owner/admin only, 204) |
| GET    | `/api/v1/vehicles/{id}/telemetry`     | List telemetry (owner/admin, paginated, time filter) |
| POST   | `/api/v1/vehicles/{id}/telemetry`     | Store a telemetry sample (owner/admin, 201) |
| POST   | `/api/v1/vehicles/{id}/health/analyze`| Analyze + persist a health snapshot (owner/admin; window_minutes 1–1440) |
| GET    | `/api/v1/vehicles/{id}/health`        | Latest persisted health context (owner/admin) |
| GET    | `/api/v1/vehicles/{id}/health/history`| Paginated health snapshot history (owner/admin) |
| POST   | `/api/v1/vehicles/{id}/agent/query`   | Natural-language question → grounded diagnosis (owner/admin, LLM) |
| POST   | `/api/v1/vehicles/{id}/agent/events/critical` | Diagnose a critical telemetry event (owner/admin, LLM; dedup within cooldown) |
| GET    | `/api/v1/vehicles/{id}/agent/dashboard`   | Dashboard hook — health context + latest diagnosis (owner/admin, no LLM) |
| GET    | `/api/v1/vehicles/{id}/agent/diagnoses`   | Paginated agent diagnosis history (owner/admin) |
| GET    | `/api/v1/vehicles/{id}/agent/diagnoses/latest` | Latest persisted diagnosis (owner/admin, 404 if none) |
| GET    | `/api/v1/rag/health`  | RAG status — adapters, pgvector, corpus counts (**admin only**, 403 otherwise) |
| GET    | `/api/v1/rag/search`  | Scoped hybrid search (`q` required; any authenticated user) |
| POST   | `/api/v1/admin/rag/documents` | Ingest a manufacturer document (multipart, 201; **admin only**) |
| GET    | `/api/v1/admin/rag/documents` | Paginated corpus documents + filters (**admin only**) |
| GET    | `/api/v1/admin/rag/documents/{id}` | Document detail + version history (**admin only**) |
| DELETE | `/api/v1/admin/rag/documents/{id}` | Delete document, versions and vectors (204; **admin only**) |

All routes are versioned under `/api/v1`. Vehicle-family endpoints require
`Authorization: Bearer <access_token>` and, for non-admin accounts, ownership
of the target vehicle (non-owners receive 404 — vehicle existence is never
revealed). Health endpoints stay public.

## 16. Example API requests

```bash
# Health (public)
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/db

# --- Phase 6: register / login (all vehicle routes need a bearer token) ---
JWT_SECRET="..."  # or keep in .env (must be >= 32 chars)

curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "Sup3rSecret!", "full_name": "Ada"}'
# => {"access_token": ..., "refresh_token": ..., "expires_in": 1200, "user": {...}}

curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "Sup3rSecret!"}'

# Create a vehicle (owned by the calling user)
curl -X POST http://localhost:8000/api/v1/vehicles \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "vin": "TESTVIN123456789",
    "make": "Toyota",
    "model": "Camry",
    "year": 2024,
    "engine_type": "2.5L Petrol"
  }'

# Rotate the refresh token (old value becomes unusable)
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "$REFRESH_TOKEN"}'

# Logout revokes the refresh token (204)
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "$REFRESH_TOKEN"}'

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
| 401  | Not authenticated / invalid or expired bearer token (Phase 6) |
| 403  | Authenticated but forbidden (requires `admin`; also RAG `/health`) |
| 404  | Resource does not exist (or, for non-owners, a vehicle that does exist — no existence leak) |
| 409  | Conflict (e.g. duplicate VIN, duplicate email) |
| 422  | Request validation failed (incl. forbidden registration/profile fields) |
| 500  | Agent misconfiguration / graph execution failure |
| 502  | LLM provider error (bad request, auth, provider failure, invalid structured output) |
| 503  | LLM provider rate limiting    |
| 504  | LLM provider timeout          |

Internal database errors are logged and never exposed to clients. On the MQTT
path, malformed/unknown/duplicate messages are logged and skipped; transient
DB errors are retried a bounded number of times (see
`MQTT_MESSAGE_RETRY_ATTEMPTS`). LLM API keys never appear in logs or responses:
provider exceptions are sanitized into the agent taxonomy above.

## 19. Intentionally not implemented (yet)

- PDF reports (Phase 7), Next.js dashboard (Phase 8).
- The Phase 3 health engine is fully deterministic: no LLM, no ML, and no
  prior/manual data are used anywhere in the analysis pipeline.
- The Phase 4 agent has no long-term memory/history beyond the persisted
  diagnoses and no tool access beyond the controlled Vehicle Context tool and
  (Phase 5) the Manufacturer Guidance tool — the LLM cannot touch the
  database, SQL, or repositories directly.
- Vehicle sharing (multiple owners per vehicle), soft delete, and account
  management beyond self-service profile updates are not implemented. Refresh
  tokens are single-use and rotation-based; no surrounding device/session
  management is exposed.
- Anomaly analytics and any TimescaleDB-specific behaviour.

## 20. Manufacturer Documentation RAG (Phase 5)

`RAG_ENABLED` (default `true` outside tests) gates the whole feature; every
other setting has a default and sensible bounds. Real models are only loaded
when RAG is enabled and used — the offline test suite (`RAG_ENABLED=false` in
`tests/conftest.py`) never touches Hugging Face.

### Schema (Alembic `4f9d3c2b1a8e` → `d6a9b1c2e3f4`, applied to Supabase)

```txt
rag_documents            canonical_source UNIQUE, make/model/year range, title
rag_document_versions    immutable: content_hash, embedding_model (bge-m3),
                         embedding_dimension, chunking_version, UNIQUE(document_id, version)
rag_chunks               content_plain, content_tsv (GIN), scope + make/model/year,
                         embedding_store vector(1024) + HNSW vector_cosine_ops
agent_diagnoses          + rag_used, rag_evidence_count, rag_embedding_model,
                         rag_reranker_model, rag_scope (JSONB)
```

### Agent grounding

- `ManufacturerGuidanceTool` runs during agent execution when RAG is enabled:
  derives the vehicle scope, runs hybrid retrieval + rerank, applies a
  threshold, and injects a citation-backed guidance section (with provenance)
  into the prompt only when evidence exists.
- Citations map to actually-retrieved chunks; `rag_evidence_count` records how
  many were used; the diagnosis row stores `rag_used`,
  `rag_embedding_model`, `rag_reranker_model`, `rag_scope`.
- Guardrails (all live-verified): retrieved documents are treated as **data,
  not instructions** (prompt-injection tested), a nonsense/no-result query
  yields **zero** manufacturer claims (negative grounding), and `RAG_ENABLED=
  false` reproduces Phase 4 behaviour exactly (no guidance, `rag_used=False`).

### Ingest docs

```bash
python scripts/ingest_documents.py manual.md --canonical rep://acme/manual --make Acme --model Camry --year 2024
python scripts/query_rag.py "coolant level" --make Acme --model Camry --year 2024 --top-k 3
python scripts/phase5_agent_rag_verify.py   # real BGE-M3 + reranker, live Supabase E2E
```

BGE-M3/reranker weights are cached locally; the verifier pins
`HF_HUB_OFFLINE=1` etc. The corpus on Supabase is currently empty (cleaned up
after verification) until documents are (re-)ingested.

## 21. Admin document management (Phase 6.x)

The manufacturer corpus can also be managed over HTTP by an **admin** user. The
API adds only an upload/safety layer on top of the Phase 5 pipeline — the same
`IngestionService` (`parse → chunk → embed → persist`) backs both
`scripts/ingest_documents.py` and these endpoints, so versioning, content-hash
deduplication and failure semantics are identical on both paths. **No schema
change was required** (Phase 5 tables already hold every field).

All four endpoints require `role=admin` (401 unauthenticated, 403 non-admin):

| Method | Path | Success | Purpose |
| ------ | ---- | ------- | ------- |
| `POST` | `/api/v1/admin/rag/documents` | `201` | Ingest one document (multipart) |
| `GET` | `/api/v1/admin/rag/documents` | `200` | Paginated list + filters |
| `GET` | `/api/v1/admin/rag/documents/{id}` | `200` | Detail + immutable version history |
| `DELETE` | `/api/v1/admin/rag/documents/{id}` | `204` | Transactional delete of document + versions + chunks/vectors |

### Upload

```bash
curl -X POST http://localhost:8000/api/v1/admin/rag/documents \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@service_manual.pdf" \
  -F "canonical=rep://toyota/camry/2024/service-manual" \
  -F "make=Toyota" -F "model=Camry" -F "year=2024" \
  -F "document_type=service-manual"
```

- `file` and `canonical` are required; `make`, `model`, `year` and the optional
  `manufacturer`, `title`, `source_uri`, `source_type`, `document_type`,
  `year_end`, `language` mirror the existing `IngestionService.ingest` kwargs —
  no invented metadata. Any other form field is rejected (`422`).
- Accepted extensions come from the parser registry, never a second hardcoded
  list: `.pdf .docx .doc .rtf .pptx .ppt .html .mhtml .xlsx .xls .odt .ods
  .odp .epub .txt .md .text`.
- Size ceiling `RAG_MAX_UPLOAD_SIZE_MB` (default `50`); the upload is streamed
  in 1 MiB chunks and aborted with `413` the moment it exceeds the limit.
- Response: `201` with `status` `ingested` (new document/version) or `unchanged`
  (identical content already present — Phase 5 idempotency), plus `version`,
  `chunks_created`, `content_hash`, `parser_name`, `embedding_model` and
  `embedding_dimension`.

```json
{
  "id": "3f2c...", "status": "ingested", "filename": "service_manual.pdf",
  "canonical": "rep://toyota/camry/2024/service-manual", "make": "Toyota",
  "model": "Camry", "year": 2024, "version": 1, "chunks_created": 42,
  "content_hash": "9ab1...", "parser_name": "docling-2",
  "embedding_model": "BAAI/bge-m3", "embedding_dimension": 1024
}
```

### List / detail / delete

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/admin/rag/documents?page=1&page_size=20&make=Toyota&status=completed"
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/admin/rag/documents/$DOC_ID
curl -X DELETE -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/admin/rag/documents/$DOC_ID
```

List uses the shared `PaginatedResponse` envelope (`items`, `page`, `page_size`,
`total`) with `page >= 1`, `page_size` 1..100 and exact filters `make`, `model`,
`canonical`, model-year range `year`, and `status` (a version ingestion state).
Detail adds the version history (content hash, parser, chunk counts, status per
version) plus `latest_version`. Delete removes chunks → versions → document in
one transaction (the Phase 5 foreign keys are *not* `ON DELETE CASCADE`), so no
orphaned vectors remain and RAG search stops returning the content immediately.

### Safety and error semantics

| Status | Cause |
| ------ | ----- |
| `400` | Unsupported extension, empty file, non-UTF-8 text, unsafe/path-traversal filename |
| `413` | Upload exceeds `RAG_MAX_UPLOAD_SIZE_MB` |
| `422` | Invalid metadata / unknown form field, or ingestion failure (transaction rolled back) |
| `404` | Unknown `document_id` |
| `503` | RAG backend unavailable (pgvector missing) |

Uploads are streamed to a throwaway temp directory (`tempfile.mkdtemp`,
`uuid4().hex` file name) and removed on every exit path — success, validation
error or ingestion failure. The client-supplied filename is never used as a
path, and it is rejected outright if it contains directory separators, `..` or a
NUL byte.

### Testing

`tests/rag/test_admin_documents_api.py` (39 hermetic tests: authorization matrix,
validation, pagination envelope, 404/503 mapping, temp-file hygiene) and
`tests/rag/test_admin_documents_integration.py` (full upload → search → delete
lifecycle, idempotent re-upload, failed-ingest rollback). The integration file
is pgvector-gated and skips when the test database lacks the extension.