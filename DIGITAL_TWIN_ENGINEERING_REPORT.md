# Digital Twin Engineering Report

**Project:** Digital Twin — Car Health Monitoring Platform
**Scope:** Complete engineering audit of the backend implementation (Phases 1, 2, 3, 3.5)
**Report date:** 2026-09-22
**Author:** Engineering audit (assistant-assisted documentation task; no application code modified)

---

## 1. Executive Summary

The Digital Twin backend is a production-shaped, dependency-injected FastAPI
application that ingests simulated vehicle telemetry over MQTT, persists it to
PostgreSQL with end-to-end idempotency, and delivers a deterministic,
explainable vehicle-health intelligence layer over a versioned REST API.

The repository documents **four completed implementation phases**:

| Phase | What | Status |
|---|---|---|
| 1 | Vehicle CRUD + raw telemetry ingestion REST API (PostgreSQL via SQLAlchemy 2 / Alembic) | **IMPLEMENTED + VERIFIED** |
| 2 | MQTT ingestion pipeline (Mosquitto broker, subscriber, publisher, simulator), idempotent persistence | **IMPLEMENTED + VERIFIED** |
| 3 | Deterministic Vehicle Health Context: statistics, trends, baselines, rule engine, scoring, snapshots | **IMPLEMENTED + VERIFIED** |
| 3.5 | Supabase (managed PostgreSQL) target database, connection hardening, migration + runtime verification | **IMPLEMENTED + VERIFIED** |

Best-evidence state today:

- **204 tests collected**, of which **202 passed** and **2 MQTT end-to-end tests
  deselected** by default (needs a live broker); MQTT E2E also verified against a
  real broker earlier.
- `ruff check .` and `ruff format --check .` both **clean** (89 Python files).
- Alembic head `a1b2c3d4e5f6` applied on **both** the local dev database and
  the Supabase project (`upgrade` verified; `downgrade` not exercised).
- Live end-to-end smoke test on Supabase: 1 demo vehicle, 21 telemetry rows,
  21 distinct `source_event_id`s, **0 duplicate groups**, 1 health snapshot,
  `/api/v1/health/db` = ok, no errors in API or subscriber logs.
- TLS: direct Supabase connection encrypted (PostgreSQL 17.6, `TLS: True`).

**Open gaps (documented, not blocking):** Docker runtime verification was not
performed in this environment (Docker unavailable); Alembic *downgrade* is not
tested; RLS intentionally deferred; no frontend; no LLM/agent layer.

Local dev data was treated as disposable (CASE A) and **not** migrated to
Supabase; the local database remains intact.

---

## 2. Scope of This Report

This report documents **exactly what exists** in the repository, how it works,
how it was verified, and what remains intentionally not implemented. It is a
snapshot of the current source of truth.

- **Included:** all backend application code, tests, migrations, configuration,
  Docker/compose artifacts, scripts, Make targets, README.
- **Excluded:** any code NOT present in the repo (e.g. LLM/RAG layer implied by
  the original project vision). Such items appear in §"Not implemented".
- **Security stance:** this report contains **no secrets**. Connection strings
  are shown redacted (`DATABASE_URL=<REDACTED>`). The real credentials live
  only in the git-ignored `backend/.env`.

Related historical deliverables (earlier phase reports) exist at the repo root:
`PHASE3_REPORT.md` and `FINAL_INTEGRATION.md`. They are **superseded** by this
document; the repository itself is the source of truth.

---

## 3. Methodology

The audit used three independent evidence passes and a repeatability check.

### 3.1 Pass 1 — Structural phase discovery
Repository walk (top to bottom) reconstructing the phase timeline from
migrations, README, Makefile, dependencies, and file layout.

### 3.2 Pass 2 — Subsystem deep reads (4 parallel agents)
- API layer: routers, schemas, services, repositories, exceptions.
- Intelligence engine: statistics, trends, baselines, rules, scoring, context.
- MQTT subsystem + simulator: topics, schemas, parser, client, scenarios.
- Tests, migrations, infra, docs, dependency scan.

### 3.3 Pass 3 — Runtime verification (Phase 3.5)
Connectivity probe, `alembic upgrade head` on Supabase, schema/constraint/index
inspection, seed, live subscriber + API + simulator run, idempotency query.

### 3.4 Repeatability
Every verification command is documented in §"Verification evidence" and
re-runnable via the Makefile targets listed in the Onboarding section.

---

## 4. Known Issues & Environment Limitations

| # | Limitation | Impact | Status |
|---|---|---|---|
| 1 | **Docker unavailable** on the audit machine | Compose stack never executed here; compose/Dockerfile only verified by static inspection | Documented; feature verified locally without Docker |
| 2 | **Alembic downgrade untested** | Only `upgrade head` exercised on both DBs | Open (risk: low) |
| 3 | Windows `SelectorEventLoop` requirement | aiomqtt needs `add_reader`; handled by explicit event-loop selection in `client.py` / `subscriber.py` | Mitigated |
| 4 | MQTT session takeover | Fixed client ids caused reconnect flaps; unique per-process client id default | Mitigated (documented in config docstrings) |
| 5 | asyncpg `sslmode` incompatibility | SQLAlchemy asyncpg dialect passes URL query params as `connect()` kwargs; asyncpg accepts `ssl` but rejects `sslmode` kwarg; asyncpg DSN accepts `sslmode` but rejects `ssl` in DSN itself | Resolved: use `?ssl=require` in DATABASE_URL; `scripts/check_db.py` normalizes |
| 6 | Supabase test safety | Running tests against Supabase could clobber data | Guarded: `tests/conftest.py` raises if `TEST_DATABASE_URL` host contains `supabase`/`pooler` |
| 7 | Mosquitto Windows service `$SYS` metric query timeout | Purely diagnostic; runtime verified via tests + logs instead | Not material |

---

## 5. Repository Inventory

```
.                                        ← workspace root (git repo, branch main)
├── PHASE3_REPORT.md                     ← historical phase-3 deliverable (superseded)
├── FINAL_INTEGRATION.md                 ← historical phase-1+2 deliverable (superseded)
└── backend/
    ├── .env                             ← real settings incl. DATABASE_URL (git-ignored, SECRET)
    ├── .env.example                     ← documented template
    ├── .gitignore
    ├── Makefile                         ← 20+ targets incl. db-check/current/heads/history
    ├── pyproject.toml                   ← deps + ruff config
    ├── Dockerfile
    ├── docker-compose.yml               ← postgres, backend, mosquitto, mqtt-subscriber, simulator
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py
    │   └── versions/
    │       ├── e01c2724f67b_initial_schema_vehicles_and_telemetry_.py   (Phase 1)
    │       ├── 7e38f4f3d70b_add_source_event_id_to_telemetry_records.py (Phase 2)
    │       └── a1b2c3d4e5f6_create_vehicle_health_snapshots.py          (Phase 3, head)
    ├── app/
    │   ├── main.py                      ← FastAPI app, lifespan, exception handlers, CORS, router mount
    │   ├── api/
    │   │   ├── router.py                ← mounts /health /vehicles /vehicles/{id}/telemetry /vehicles/{id}/health
    │   │   └── routes/
    │   │       ├── health.py
    │   │       ├── vehicles.py
    │   │       ├── telemetry.py
    │   │       └── vehicle_health.py
    │   ├── core/
    │   │   ├── config.py                ← Settings (pydantic-settings), MQTT + health knobs
    │   │   ├── database.py              ← engine/pool factory, session factory, checks, dispose
    │   │   ├── exceptions.py            ← AppError, NotFoundError, ConflictError, DatabaseError...
    │   │   └── logging.py
    │   ├── dependencies/database.py     ← service DI providers
    │   ├── models/                      ← base (UUID PK + timestamp mixins), vehicle, telemetry, health_snapshot
    │   ├── schemas/                     ← common, vehicle, telemetry, health, vehicle_health
    │   ├── repositories/                ← vehicle, telemetry, health_snapshot
    │   ├── services/                    ← vehicle, telemetry, vehicle_health
    │   ├── mqtt/                        ← topics, schemas, parser, client, publisher, subscriber, exceptions
    │   └── intelligence/                ← models, statistics, trends, baselines, rules, scoring, context, engine
    ├── simulator/
    │   ├── config.py                    ← SimulatorSettings (SIMULATOR_* + shared MQTT_*)
    │   ├── vehicle.py                   ← DrivingState state machine definitions
    │   ├── telemetry_generator.py       ← deterministic sensor model + scenarios
    │   ├── publisher.py
    │   └── main.py
    ├── scripts/
    │   ├── check_db.py                  ← independent TLS/connectivity probe (normalizes ?ssl=)
    │   └── seed_demo_vehicle.py         ← idempotent demo vehicle insert
    ├── infrastructure/mosquitto/
    │   ├── mosquitto.conf               ← docker image config
    │   ├── mosquitto.acl
    │   └── mosquitto.local.conf         ← loopback anonymous dev broker
    └── tests/                           ← 26 test modules, 204 collected
        ├── conftest.py                  ← local TEST_DATABASE_URL + Supabase/pooler guard
        ├── api/    (33)  health 2, vehicles 14, telemetry 7, vehicle_health 10
        ├── core/   (2)   config 2
        ├── intelligence/ (67) statistics 11, trends 7, baselines 10, rules 19, scoring 12, engine 8
        ├── mqtt/   (53)  schemas 21, topics 8, parser 9, publisher 2, subscriber 9, client_id 2, mqtt_e2e 2
        ├── repositories/ (7) health_snapshot 7
        ├── services/ (24) vehicle 6, telemetry 9, vehicle_health 9
        └── simulator/ (18) config 7, telemetry_generator 11
```

---

## 6. Implementation Phases Discovered

### Phase 1 — Vehicle registry + telemetry ingestion (REST, PostgreSQL)
- `vehicles` and `telemetry_records` tables, migration `e01c2724f67b`.
- Vehicle CRUD (list/create/get/patch/delete), telemetry create + paginated +
  time-filtered list.
- Layer separation: routers → services → repositories → SQLAlchemy ORM models
  on a declarative `Base` with `UUIDPrimaryKeyMixin` and `TimestampMixin`.
- Centralized exception handler → 404/409/422/500 JSON with consistent `detail`.
- Dependency injection via `dependencies/database.py` (session factory per request).

### Phase 2 — MQTT ingestion pipeline
- Migration `7e38f4f3d70b`: adds `source_event_id` + partial unique index →
  **at-least-once delivery with exactly-once persistence**.
- `app/mqtt`: versioned envelopes, topic conventions, parser, aiomqtt client,
  publisher, and a resilient subscriber (backoff + bounded DB retries).
- `simulator/`: deterministic drive-cycle telemetry generator with 4 scenarios.
- Mosquitto broker config under `infrastructure/mosquitto`, plus `docker-compose`
  services (`mosquitto`, `mqtt-subscriber`, `simulator`).
- `tests/conftest.py` MQTT E2E fixtures; `make mqtt-test` runs `-m mqtt_e2e`.

### Phase 3 — Deterministic Vehicle Health Context
- Migration `a1b2c3d4e5f6` (`a1b2c3d4e5f6`, head): `vehicle_health_snapshots`
  with versioned `context_json`.
- `app/intelligence` pipeline: statistics → trends → baselines → rule engine →
  scoring → context assembly, all **deterministic and pure** (no DB/MQTT/API).
- Health endpoints: analyze (POST), latest (GET), history (GET).
- Findings are factual evidence only ("coolant temperature is elevated",
  never "water pump failed").
- `PHASE3_REPORT.md` written at the end of this phase (now superseded).

### Phase 3.5 — Supabase migration & connection hardening
- Switched the runtime `DATABASE_URL` to the Supabase direct connection
  (`db.poogyoxfbmqkhzrqazop.supabase.co:5432`), PostgreSQL 17.6, TLS.
- Pool configuration (`pool_size=5, max_overflow=5, pool_timeout=30,
  pool_recycle=1800, pool_pre_ping=True`) in `app/core/database.py`; tests keep
  `NullPool`.
- `scripts/check_db.py` — independent probe that normalizes asyncpg SSL handling.
- Makefile `db-check`, `db-current`, `db-heads`, `db-history` targets.
- Composition: `DATABASE_URL: ${DATABASE_URL:-...}` in `docker-compose.yml`
  (backend + mqtt-subscriber) so the stack can target Supabase.
- Test-safety guard: `tests/conftest.py` refuses Supabase/pooler hosts.
- README §10 documents connection choice, config, verify, migration, test
  safety, rollback, Docker notes, and RLS posture.
- Full runtime verification on Supabase (see §Phase 3.5 evidence).

---

## 7. Architecture

### 7.1 Current architecture (as implemented)

```
                         ┌────────────────────────────────────────────────┐
                         │   simulator/  (deterministic drive-cycle model)│
                         │   SIMULATOR_SCENARIO: normal | high_temperature│
                         │     | low_battery | high_engine_load           │
                         └───────────────┬────────────────────────────────┘
                                         │  MQTT publish
                                         ▼
                 ┌─────────────────────────────────────────────┐
                 │  Mosquitto broker   (localhost:1883 / :9001) │
                 │  topics: vehicles/{id}/telemetry            │
                 │          vehicles/{id}/status               │
                 └───────────────┬─────────────────────────────┘
                                 │  subscribe  vehicles/+/telemetry  (QoS 1)
                 ┌───────────────▼─────────────────────────────┐
                 │  app/mqtt/subscriber.py                     │
                 │   parser → TelemetryMessage (versioned,     │
                 │   extra="forbid", tz-aware timestamps)      │
                 │   → service/repository idempotent insert    │
                 └───────────────┬─────────────────────────────┘
                                 │ writes (dedup on source_event_id)
                 ┌───────────────▼─────────────────────────────┐
                 │  PostgreSQL (local digital_twin  OR  Supabase│
                 │  db.<ref>.supabase.co:5432 via ?ssl=require) │
                 │  vehicles / telemetry_records /              │
                 │  vehicle_health_snapshots                    │
                 └───────────────┬─────────────────────────────┘
                                 ▲
                 ┌───────────────┴─────────────────────────────┐
                 │  app/main.py — FastAPI (uvicorn, /api/v1)   │
                 │   health          health, health/db         │
                 │   vehicles        CRUD                      │
                 │   vehicles/{id}/telemetry  create/list      │
                 │   vehicles/{id}/health    analyze/latest/history │
                 └─────────────────────────────────────────────┘
                                 ▲
                                 │   triggers deterministic analysis
                 ┌───────────────┴─────────────────────────────┐
                 │  app/intelligence (pure, deterministic)     │
                 │   statistics → trends → baselines → rules → │
                 │   scoring → context (HealthContext v1.0)    │
                 │   persisted as immutable health_snapshots   │
                 └─────────────────────────────────────────────┘
```

### 7.2 Target architecture (original project vision — NOT implemented)
The intended Phase 4 agent layer and the broader "digital twin" vision
(LLM planning / retrieval over long-term context) are **not present** in the
repository. See §Not implemented.

### 7.3 Design principles observed in code
- **Transport-agnostic intelligence:** the analysis engine consumes typed
  `TelemetryPoint` samples and never touches DB/MQTT/API, so it is identical
  for MQTT, REST, replay, tests, or historical data.
- **Deterministic and explainable:** no ML randomness; every threshold has a
  documented meaning; each finding carries `confidence`, `observed_value`,
  `threshold`, and an `evidence` map; score breakdown is exposed via
  `score_details.components`.
- **Idempotency at ingestion:** service-level dedupe + partial unique index
  (`WHERE source_event_id IS NOT NULL`) → at-least-once MQTT with
  exactly-once persistence.
- **Immutable evidence:** re-analysis creates a *new* health snapshot; existing
  ones are never mutated.
- **Split config:** `Settings` (API/subscriber) and `SimulatorSettings`
  (simulator) share the `MQTT_*` names; simulator adds `SIMULATOR_*` aliases,
  verified by a Protocol in `client.py`.

---

## 8. Data Flow

### Ingestion path (telemetry)
1. Simulator sample → `TelemetryData` → envelope `TelemetryMessage`
   (`schema_version`, `event_id`, `vehicle_id`, tz-aware `timestamp`,
   nested `telemetry`) → publish on `vehicles/{vehicle_id}/telemetry`.
2. Subscriber parses topic + payload (`TelemetryMessageParser`); malformed
   envelopes/empty payloads/unknown vehicles (404) are **logged and skipped**.
3. Valid envelope → `TelemetryCreate` with `timestamp`, `source_event_id`,
   `raw_payload` = full JSON envelope → `TelemetryService.create_telemetry`.
4. Repository dedupes: if `(vehicle_id, source_event_id)` already exists the
   insert is skipped (partial unique index guarantees this at DB level).
5. Transient DB errors are retried up to `mqtt_message_retry_attempts` (3) with
   bounded exponential wait (1s, 2s, cap 5s).

### Health analysis path
1. Client calls `POST /api/v1/vehicles/{id}/health/analyze?window_minutes=`.
2. Service loads telemetry within window (+ older history for baselines,
   `health_baseline_window_minutes=360`).
3. `HealthAnalysisEngine.analyze`:
   `compute_data_quality` → `analyze_metrics` → `analyze_trends` →
   (history) `analyze_baselines` → rule engine `evaluate` → `score_findings` →
   `compute_confidence` → `build_context`.
   If `sample_count < minimum_samples (10)` → `INSUFFICIENT_DATA` finding,
   score `None`, status `unknown`.
4. Context serialized to `context_json` + summary columns and persisted as a
   new `vehicle_health_snapshots` row.
5. Read back via `GET /health` (latest) or `GET /health/history` (paginated).

---

## 9. Technology Stack

| Layer | Technology | Evidence |
|---|---|---|
| Language | Python 3.13 (project) | `pyproject.toml` |
| API | FastAPI + uvicorn | `main.py`, Makefile `dev` |
| Validation | Pydantic v2, pydantic-settings | models/schemas |
| ORM | SQLAlchemy 2 (async, asyncpg) | `core/database.py`, models |
| Migrations | Alembic | `alembic/versions` |
| DB | PostgreSQL (local) and Supabase (managed PG 17.6) | runtime verified |
| MQTT | aiomqtt (asyncio), Mosquitto broker | `app/mqtt` |
| Noise/scenarios | Python `random.Random` seeded (deterministic) | telemetry_generator |
| Quality | ruff (lint + format) | Makefile `lint`/`format`, pyproject |
| Tests | pytest | `tests/`, Makefile `test` |
| Package | `pip install -e ".[dev]"` | Makefile `install`, egg-info present |
| Infra | Docker / docker-compose (config only; not executed here) | compose + Dockerfile |

---

## 10. Database Schema

### 10.1 `vehicles` (Phase 1)

| Column | Type | Nullable | Default / Notes |
|---|---|---|---|
| `id` | UUID (PG) | no | PK; client-side `uuid4` default |
| `vin` | VARCHAR(50) | no | **unique + indexed** |
| `make` | VARCHAR(100) | no | |
| `model` | VARCHAR(100) | no | |
| `year` | INTEGER | no | |
| `engine_type` | VARCHAR(100) | yes | |
| `created_at` | TIMESTAMPTZ | no | `server_default now()` |
| `updated_at` | TIMESTAMPTZ | no | `server_default now()`, `onupdate now()` |

Relationships: `telemetry_records`, `health_snapshots` (cascade all/delete-orphan,
`passive_deletes=True`; FKs use `ON DELETE CASCADE` in DB).

### 10.2 `telemetry_records` (Phase 1, extended Phase 2)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID (PG) | no | PK |
| `vehicle_id` | UUID (PG) | no | FK → `vehicles.id` **ON DELETE CASCADE**, indexed |
| `timestamp` | TIMESTAMPTZ | no | indexed |
| `rpm` … `odometer` (11 metric columns) | FLOAT | yes | see metrics table below |
| `raw_payload` | JSONB | yes | full MQTT envelope (audit trail) |
| `source_event_id` | VARCHAR(64) | yes | MQTT event id (Phase 2) |
| `created_at` | TIMESTAMPTZ | no | `server_default now()` |

**Indexes:**
- `ix_telemetry_records_vehicle_id` (single col, from `index=True`)
- `ix_telemetry_records_timestamp` (single col)
- `ix_telemetry_records_vehicle_id_timestamp` (composite)
- `uq_telemetry_records_vehicle_source_event` — **UNIQUE (vehicle_id,
  source_event_id) WHERE source_event_id IS NOT NULL** (partial) → idempotency guarantee

The 11 metric columns mirror `TelemetryData` (extra="forbid" schema):
rpm, speed, engine_load, coolant_temperature, oil_temperature,
battery_voltage, fuel_level, intake_air_temperature, throttle_position,
engine_runtime, odometer — all optional floats.

### 10.3 `vehicle_health_snapshots` (Phase 3)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID (PG) | no | PK |
| `vehicle_id` | UUID (PG) | no | FK → `vehicles.id` **ON DELETE CASCADE** |
| `generated_at` | TIMESTAMPTZ | no | |
| `window_start` | TIMESTAMPTZ | no | |
| `window_end` | TIMESTAMPTZ | no | |
| `sample_count` | INTEGER | no | |
| `health_score` | FLOAT | yes | `None` when insufficient data |
| `health_status` | VARCHAR(20) | no | healthy / attention / critical / unknown |
| `confidence` | FLOAT | yes | 0–1 |
| `context_schema_version` | VARCHAR(16) | no | `"1.0"` |
| `context_json` | JSONB | no | full serialized `HealthContext` |
| `created_at` | TIMESTAMPTZ | no | `server_default now()` |

**Indexes:**
- `ix_vehicle_health_snapshots_vehicle_generated_at` (vehicle_id, generated_at)
- `ix_vehicle_health_snapshots_vehicle_status_generated`
  (vehicle_id, health_status, generated_at)

---

## 11. Migrations

| Revision | Name | Phase | Contents |
|---|---|---|---|
| `e01c2724f67b` | initial schema: vehicles and telemetry_records | 1 | both tables + indexes + FKs |
| `7e38f4f3d70b` | add `source_event_id` to telemetry_records | 2 | new column + partial unique index |
| `a1b2c3d4e5f6` | create vehicle_health_snapshots | 3 | snapshots table + indexes (**head**) |

- **Head:** `a1b2c3d4e5f6` — verified on local dev DB and on Supabase.
- `alembic upgrade head` executes cleanly on both; **downgrade path untested**.
- Supabase platform tables (`notes`, `tickets`) pre-existed in the project and
  were untouched by our migrations (verified: only our 3 migration files listed
  in `alembic_version` at that point was `a1b2c3d4e5f6`).

---

## 12. REST API Reference

Base prefix: `/api/v1` (`API_V1_PREFIX`). Docs: `/docs` (Swagger), `/openapi.json`.

### 12.1 Health
| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/health` | — | `{status:"ok", service:"digital-twin-api"}` |
| GET | `/health/db` | — | `{status, service, database:"ok"\|"unavailable"}`; **503** when DB down |
| GET | `/` | — | `{service, docs:"/docs"}` (not in schema) |

### 12.2 Vehicles
| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/vehicles` | `page` (≥1, dflt 1), `page_size` (1–100, dflt 20) | `PaginatedResponse[VehicleResponse]`, newest first |
| POST | `/vehicles` | body `VehicleCreate` | **201** `VehicleResponse` (VIN must be unique → 409) |
| GET | `/vehicles/{vehicle_id}` | — | `VehicleResponse` (404 if missing) |
| PATCH | `/vehicles/{vehicle_id}` | body `VehicleUpdate` | `VehicleResponse` (VIN immutable) |
| DELETE | `/vehicles/{vehicle_id}` | — | **204**; cascades to telemetry + snapshots |

### 12.3 Telemetry
| Method | Path | Query | Response |
|---|---|---|---|
| POST | `/vehicles/{vehicle_id}/telemetry` | body `TelemetryCreate` (optionally `source_event_id` for idempotency) | **201** `TelemetryResponse` |
| GET | `/vehicles/{vehicle_id}/telemetry` | `page`, `page_size` (1–500, dflt 50), `start_time`, `end_time` (ISO8601, inclusive) | `PaginatedResponse[TelemetryResponse]` newest first |

### 12.4 Vehicle Health
| Method | Path | Query | Response |
|---|---|---|---|
| POST | `/vehicles/{vehicle_id}/health/analyze` | `window_minutes` (1–1440, optional default 15) | **200** `HealthContextResponse` (full context JSON) |
| GET | `/vehicles/{vehicle_id}/health` | — | latest `HealthContextResponse`; **404** if none exists yet |
| GET | `/vehicles/{vehicle_id}/health/history` | `page`, `page_size` (1–100, dflt 20), `start_time`, `end_time` on `generated_at` | `PaginatedResponse[HealthSnapshotItem]` newest first |

### 12.5 Error semantics (global exception handlers)
| Situation | Status | Body |
|---|---|---|
| Resource missing | 404 | `{"detail": "<resource> not found"}` |
| Conflict (duplicate VIN) | 409 | `{"detail": <detail>}` |
| Generic database failure | 500 | `{"detail": "Internal server error"}` (logged) |
| Validation failure | 422 | `{"detail": [errors...]}` |
| Unhandled exception | 500 | `{"detail": "Internal server error"}` (logged with traceback) |

---

## 13. MQTT Pipeline

### 13.1 Topic conventions (centralized in `app/mqtt/topics.py`)
```
{prefix}/{vehicle_id}/telemetry   → raw telemetry samples
{prefix}/{vehicle_id}/status      → vehicle online/offline
{prefix}/+/telemetry              → subscriber pattern  (default prefix "vehicles")
```
`parse_*` returns `None` for non-matching/$-prefixed/wildcard topics so the
subscriber ignores unrelated traffic gracefully.

### 13.2 Telemetry envelope (versioned; `extra="forbid"`)
```json
{
  "schema_version": 1,
  "event_id": "ABC123",
  "vehicle_id": "11111111-2222-4333-8444-555555555555",
  "timestamp": "2026-01-01T00:00:00Z",
  "telemetry": { "...": 0.0 }
}
```
- `timestamp` **must be timezone-aware** (naive rejected).
- `TelemetryData` field ranges: rpm 0–10000, speed 0–400, engine_load 0–100,
  coolant/oil −60–200, battery 0–40, fuel 0–100, intake_air −60–120,
  throttle 0–100, engine_runtime ≥0, odometer ≥0.
- Status envelope: `{vehicle_id, status:"online"|"offline", timestamp}`.

### 13.3 Subscriber behavior (`app/mqtt/subscriber.py`)
- Connects via `create_mqtt_client` (aiomqtt, `clean_session=True`, QoS from
  settings = 1). Credentials only sent when username set (anonymous dev broker ok).
- Reconnect loop with exponential backoff 1, 2, 4, … capped at
  `mqtt_reconnect_max_seconds` (30).
- Graceful SIGINT/SIGTERM shutdown; bounded DB retry (3 attempts, wait
  `min(2**(n-1), 5)` s) for transient failures; **unknown vehicle → log + skip**.
- No direct SQLAlchemy persistence in the subscriber — it reuses
  service/repository layers (layering invariant).
- Windows: installs a `SelectorEventLoop` explicitly (aiomqtt requires
  `add_reader`).

### 13.4 Publisher / client
- `app/mqtt/publisher.py` builds message bytes and publishes topics; client
  factory (`client.py`) is shared by simulator and subscriber.

---

## 14. Simulator

### 14.1 Configuration (`simulator/config.py`)
- `SIMULATOR_VEHICLE_ID` **required** (refuses to run without it).
- `SIMULATOR_SCENARIO` ∈ `normal | high_temperature | low_battery |
  high_engine_load`; `SIMULATOR_INTERVAL_SECONDS` (1.0); `SIMULATOR_SEED` (42).
- Drive-cycle phase durations: off 2s, starting 3s, idle 10s, accelerating 15s,
  cruising 30s, decelerating 10s; `SIMULATOR_CRUISE_SPEED=60`.
- Initial state: odometer 45231.7, fuel 75.0, engine_runtime 0.
- MQTT fields reuse `MQTT_*`; default client id `dtwin-sim-<8 hex>` (unique per
  process → avoids session takeover).

### 14.2 Drive-cycle state machine (`simulator/vehicle.py`, generator)
OFF → STARTING → IDLE → ACCELERATING → CRUISING → DECELERATING → OFF …
Physical invariants enforced: fuel only decreases while engine runs; odometer
only increases (∝ speed); engine runtime only accumulates outside OFF; battery
sits near running set-point while running. Sensor values derive from
physically-plausible rules plus seeded Gaussian noise (deterministic per seed).

### 14.3 Scenario modifiers (`Scenario`)
| Scenario | Effect |
|---|---|
| `high_temperature` | coolant target 115°C (vs 90), oil target 108°C (vs 88) |
| `low_battery` | running voltage 11.9V (vs 13.9), offline 11.4V (vs 12.5) |
| `high_engine_load` | load multiplier 1.5 (clamped to 100%) |
| `normal` | no modifiers |

These are designed to trip the rule engine: coolant/oil > warning/critical,
battery < warning, engine_load mean > warning/critical.

---

## 15. Vehicle Health Intelligence (exact formulas & constants)

Source: `app/intelligence/` (all constant names are literal).

### 15.1 Supported metrics & units (`models.py`)
11 metrics: `rpm`(RPM), `speed`(km/h), `engine_load`(%), `coolant_temperature`(C),
`oil_temperature`(C), `battery_voltage`(V), `fuel_level`(%),
`intake_air_temperature`(C), `throttle_position`(%), `engine_runtime`(s),
`odometer`(km). `CONTEXT_SCHEMA_VERSION="1.0"`, `RULE_ENGINE_VERSION="1.0"`.

### 15.2 Statistics (`statistics.py`)
- Non-finite / `None` values are treated as missing; metric omitted when no
  valid value. Never emits NaN/Inf.
- Rounding `_DECIMALS=6`.
- `std_dev` = sample std dev (n−1 denominator); `None` if n < 2.
- `percentile` = linear interpolation (numpy “linear” compatible).
- `cv = std_dev/|mean|`; `None` when std_dev missing or `|mean| ≤ 1e-12`.

### 15.3 Trends (`trends.py`)
- Method: OLS regression of value vs elapsed seconds over the window.
- `TREND_MIN_SAMPLES=3`; fewer → `insufficient_data`.
- `normalized_slope = slope·span/|mean|` (`None` when span or |mean| ≈ 0).
- Direction hysteresis: `STABLE_EPSILON=0.01` → increasing / stable / decreasing.
- Strength on `|normalized_slope|`: `none < 0.01`, `weak < 0.08`,
  `moderate < 0.25`, else `strong`. Slope rounded 8, normalized rounded 6.

### 15.4 Baselines (`baselines.py`)
- Uses the vehicle's own history; center = median; spread = `1.4826·MAD`.
- `BASELINE_MIN_SAMPLES=5`; fewer or no current value → `insufficient_history`.
- `DEVIATION_THRESHOLD=2.0`: `(current−center)/spread > 2` → `elevated`,
  `< −2` → `depressed`, else `within`; zero-spread history → note + sign-based.
- No manufacturer spec involved.

### 15.5 Rule engine (`rules.py`, centralized `RuleThresholds`)
| Rule ID | Trigger | Severity |
|---|---|---|
| `COOLANT_TEMP_HIGH` | max > 110.0 / > 100.0 | critical / warning |
| `OIL_TEMP_HIGH` | max > 110.0 / > 100.0 | critical / warning |
| `BATTERY_VOLTAGE_LOW` | min < 10.5 / < 12.0 | critical / warning |
| `BATTERY_VOLTAGE_HIGH` | max > 15.0 | warning |
| `ENGINE_LOAD_HIGH` | mean > 60.0 / > 40.0 | critical / warning |
| `RPM_UNUSUAL` | mean > 4500.0 | warning |
| `FUEL_LEVEL_LOW` | min < 5.0 / < 15.0 | critical / warning |
| `RAPID_COOLANT_RISE` | last−first ≥ 8.0°C (n≥3) | warning |
| `RAPID_OIL_TEMP_RISE` | last−first ≥ 8.0°C (n≥3) | warning |
| `TELEMETRY_GAP` | max_gap > expected_interval·`gap_multiplier(3.0)` | info |
| `LOW_DATA_COVERAGE` | coverage < `coverage_minimum(0.5)` | info |
| `INSUFFICIENT_DATA` | sample_count < `minimum_samples(10)` (engine-level) | info |

- `_data_confidence` (text on findings) = `round(min(0.95, 0.5 + 0.5·coverage), 2)`.
- Findings sorted by `(rule_id, severity)`.

### 15.6 Scoring & status (`scoring.py`)
- `FINDING_PENALTIES`: info=0, warning=10, critical=30.
- Per-category penalty capped at `CATEGORY_PENALTY_CAP=40.0`.
- `score = clamp(100 − Σ cap(category_penalty), 0, 100)` (100 when no findings).
- Status: `score ≥ 80` healthy; `60 ≤ score < 80` attention; `< 60` critical;
  `None` → unknown.
- `score_details.components` expose per-category penalty + capped flag.

### 15.7 Confidence (`scoring.py`)
```
confidence = clamp(0.10 + 0.90·(0.30·coverage + 0.25·duration_ratio
                + 0.25·sample_sufficiency + 0.20·completeness), 0, 1)
```
where `duration_ratio = duration/window`, `sample_sufficiency =
min(1, sample_count/expected)`, `completeness = len(statistics)/11`.
Confidence measures confidence **in the assessment**, not vehicle health.

### 15.8 Orchestration (`engine.py`)
`compute_data_quality`: expected = `ceil(window_seconds / interval)`;
coverage = `min(1, sample_count/expected)` (or 1.0/0.0 edge cases); max_gap;
`timestamp_order_valid`. `analyze()` runs the pipeline, emits
`INSUFFICIENT_DATA` when samples < 10 → score `None`/status `unknown`; baselines
only when history length ≥ `baseline_minimum_samples(5)`.

---

## 16. Idempotency Design

Two complementing layers:

1. **Partial unique index** (`uq_telemetry_records_vehicle_source_event` on
   `(vehicle_id, source_event_id)` `WHERE source_event_id IS NOT NULL`) — the
   hard guarantee at the database level, allowing `NULL` source_event_id
   (e.g. REST-only inserts) to remain freely duplicate.
2. **Service/repository dedupe** — the insert paths check for existence first,
   giving clean behavior (skip, no duplicate row) under at-least-once MQTT.

Verification: the live Supabase run persisted 21 messages with 21 distinct
`source_event_id`s and **0 duplicate groups** (see Phase 3.5 evidence).

---

## 17. Test Strategy (categorized)

`make test` runs the suite; `make mqtt-test` (`-m mqtt_e2e`) runs the live-broker
tests. **204 collected: 202 passed, 2 deselected** (`mqtt_e2e`, require a real
broker; verified separately).

| Area | Module(s) | # tests | Coverage of |
|---|---|---|---|
| API | `tests/api/` | 33 | health 2, vehicles 14, telemetry 7, vehicle_health 10 |
| Config | `tests/core/` | 2 | settings loading |
| Intelligence | `tests/intelligence/` | 67 | statistics 11, trends 7, baselines 10, rules 19, scoring 12, engine 8 |
| MQTT | `tests/mqtt/` | 53 | schemas 21, topics 8, parser 9, publisher 2, subscriber 9, client_id 2, **mqtt_e2e 2 (deselected)** |
| Repositories | `tests/repositories/` | 7 | health snapshot repository |
| Services | `tests/services/` | 24 | vehicle 6, telemetry 9, vehicle health 9 |
| Simulator | `tests/simulator/` | 18 | config 7, telemetry generator 11 (determinism, invariants, scenarios) |

Notable properties tested: deterministic same-seed behavior, physical
invariants, scenario modifiers, sample/schema validation, trend/stat edge cases
(empty, single, constant, non-finite), rule threshold boundaries, scoring caps,
idempotency, cascade delete, pagination, time filtering, CRUD-during-ingestion,
and Envelope→DB round trips.

Results this audit: `pytest` → **202 passed, 2 deselected** in ~101 s
(measured on the local dev machine); ruff clean; earlier full MQTT E2E against a
live Mosquitto broker: **2 passed** in ~7.7 s.

---

## 18. Docker

- `docker-compose.yml` defines 5 services: `postgres` (16-alpine, healthcheck),
  `backend` (`build: .`, depends on healthy postgres, runs
  `alembic upgrade head && uvicorn ...`), `mosquitto` (2, ACL + password
  generation at start), `mqtt-subscriber`, `simulator`.
- **DATABASE_URL override:** both `backend` and `mqtt-subscriber` use
  `${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@postgres:5432/digital_twin}`,
  so exporting a Supabase URL runs the whole stack against managed PostgreSQL
  without a local `postgres` container.
- Simulator env mirrors the Make-level variables (`SIMULATOR_*`, defaults
  documented in README §10.8).
- **Not verified here:** Docker is unavailable in this environment; the compose
  file and Dockerfile were validated by static inspection only. Feature path
  was verified locally without Docker.

---

## 19. Phase 3.5 — Supabase Evidence

- **Project:** `poogyoxfbmqkhzrqazop` · **Host:** `db.poogyoxfbmqkhzrqazop.supabase.co:5432`
  (direct connection) · **PostgreSQL 17.6**, TLS encrypted `True`.
- **DATABASE_URL (redacted):** `postgresql+asyncpg://<user>:<password>@db.poogyoxfbmqkhzrqazop.supabase.co:5432/postgres?ssl=require` — live only in git-ignored `backend/.env`.
- **Why `?ssl=require`:** the SQLAlchemy asyncpg dialect forwards URL query
  params as `connect()` kwargs; asyncpg accepts `ssl` and rejects `sslmode`
  there, while a raw asyncpg DSN accepts `sslmode` and rejects `ssl`. `check_db.py`
  probes connectivity directly (strict ssl), then tolerantly normalizes the URL.
- **Migration:** `alembic upgrade head` applied cleanly on Supabase; current
  head `a1b2c3d4e5f6`. Supabase's own `notes`/`tickets` tables pre-existed and
  were untouched.
- **Schema check:** `telemetry_records` has 17 columns incl. `raw_payload`
  (JSONB) and `source_event_id`; `vehicle_health_snapshots` has 12 columns incl.
  `context_json` (JSONB); partial unique index present. **No ETL issue.**
- **Data:** local schema identical to Supabase (verified CREATE statements);
  both at head `a1b2c3d4e5f6`.
- **Runtime:** demo vehicle seeded
  (`11111111-2222-4333-8444-555555555555`, VIN `DEMO-SIM-0001`); API +
  subscriber + simulator + `/health/analyze` all ran against Supabase:
  1 vehicle / 21 telemetry rows / 21 distinct source_event_ids / 0 duplicates /
  1 health snapshot; `/api/v1/health/db` = ok; no API or subscriber errors.
- **Test safety:** `conftest.py` guard provably trips on a fake
  `.*.supabase.co` host, so `pytest` cannot silently target Supabase.

### 19.1 Data migration decision (CASE A)
Local dev data (11 vehicles / 4430 telemetry / 16 snapshots) was classified as
disposable dev data and **not migrated**. Local DB untouched.

### 19.2 Rollback
Revert `backend/.env` `DATABASE_URL` to
`postgresql+asyncpg://postgres:postgres@localhost:5432/digital_twin` and
restart services. (README §10.7.)

### 19.3 RLS posture
Row-level security is **not enabled**; deferred until a frontend/Data API
(service key) exists. README §10.9 documents this.

---

## 20. Not Implemented / Intentionally Deferred

Confirmed by repository-wide search + README §19. **Not present in this repo:**

| Item | Status |
|---|---|
| LangGraph / LangChain agent layer (Phase 4 vision) | **NOT IMPLEMENTED** |
| RAG, vector store (pgvector), document ingestion (Docling), BGE-M3 embeddings, reranker | **NOT IMPLEMENTED** |
| Any LLM integration / inference | **NOT IMPLEMENTED** |
| Authentication / authorization (API keys, OAuth, JWT) | **NOT IMPLEMENTED** |
| Frontend / dashboard (any web UI) | **NOT IMPLEMENTED** |
| Supabase Data API / Auth / Storage / supabase-py / supabase-js | **NOT IMPLEMENTED** (repos use psycopg/asyncpg directly) |
| Row-level security (Supabase) | **NOT VERIFIED** (deferred; README §10.9) |
| Cloud-managed MQTT broker | **NOT VERIFIED** (local Mosquitto only) |
| OBD-II physical hardware / real vehicle feed | **NOT IMPLEMENTED** (simulator only) |
| PDF/export reporting | **NOT IMPLEMENTED** |
| Production deployment automation (CI/CD, infra-as-code for cloud) | **NOT VERIFIED** |
| Alembic downgrade coverage | **NOT VERIFIED** (open) |
| Docker runtime verification | **NOT VERIFIED** (Docker unavailable here) |

The health engine already emits a versioned, JSON-serializable `HealthContext`
that was designed to be consumed by a future agent layer ("Phase 4") — the seam
exists, the user-facing consumer does not.

---

## 21. Future / Roadmap Suggestions (derived from code seams)

1. Agent layer (LangGraph) consuming `vehicle_health_snapshots.context_json`;
   long-term context via pgvector retrieval of historical contexts.
2. Auth layer before exposing the API beyond localhost.
3. Frontend consuming `/api/v1` (CORS already configured for localhost:3000/8000).
4. RLS policy definitions in Supabase once a service-key client exists.
5. Cloud MQTT (e.g. EMQX/AWS IoT) with the existing envelope contract.
6. Add a downgrade test for `a1b2c3d4e5f6` and a CI target that runs
   `pytest -m mqtt_e2e` against an ephemeral broker.

---

## 22. Onboarding / How to Run (no Docker)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[dev]"

# 1) database
#    local: create digital_twin; make sure DATABASE_URL points to it
alembic upgrade head
#    or Supabase: paste DIRECT connection string with ?ssl=require into .env

# 2) API
make dev                     # uvicorn app.main:app --reload  → http://localhost:8000/docs

# 3) broker + ingestion
make mqtt-broker             # local Mosquitto (infrastructure/mosquitto/mosquitto.local.conf)
make mqtt-subscriber         # subscriber (uses .env broker+db)

# 4) seed demo vehicle + simulator
make seed-demo-vehicle
make simulator               # publishes to the broker

# verify
make lint   # ruff check .
make test   # pytest  → 202 passed, 2 deselected
make mqtt-test  # pytest -m mqtt_e2e (needs live broker)

# Supabase assist
make db-check                # connectivity/TLS probe
make db-current              # alembic current
make db-heads                # alembic heads
make db-history              # alembic history --verbose
```

Key README sections: §7 MQTT format, §8 local dev, §9 Docker, §10 Supabase,
§11 schema & migrations, §12 Vehicle Health Context, §13 tests, §15 API docs,
§17 simulator behavior, §18 error semantics, §19 not implemented.

---

## 23. Second-Pass Verification Notes

All major factual claims in this report were re-checked against source or live
state during this audit:

- Test counts regenerated via `pytest --collect-only -q` → **204** (matches
  runtime 202 passed + 2 deselected).
- Intelligence constants re-read from `rules.py`, `scoring.py`, `trends.py`,
  `baselines.py`, `statistics.py`, `engine.py`, `models.py` (literal values above).
- API surface re-read from `api/routes/*`.
- Migration IDs confirmed from `alembic/versions/*`.
- Model columns/indexes re-read from `app/models/*`.
- Compose + Makefile + `.env.example` re-read verbatim.
- Supabase runtime state re-queried during Phase 3.5 (counts above).
- No secrets included; real `DATABASE_URL` living only in git-ignored `.env`.

---

## 24. Conclusion

The repository implements a coherent, layered, **deterministic** vehicle-health
backend across Phases 1, 2, 3, and 3.5, and the audit's evidence supports every
"IMPLEMENTED + VERIFIED" claim above:

- Full Phase 1 REST ingestion and Phase 2 MQTT ingestion are working and tested
  (idempotency proven end-to-end).
- Phase 3 intelligence is deterministic, documented, and fully unit-tested;
  thresholds and formulas are centralized and auditable.
- Phase 3.5 migrated the runtime database to Supabase over TLS with hardened
  configuration, protective test wiring, and a clean live smoke test (0
  duplicates).
- The only "NOT VERIFIED/UNRESOLVED" items are environmental (Docker runtime),
  intentionally deferred (auth, frontend, RLS, agent/LLM layer, cloud broker),
  or small open risks (downgrade coverage) — none are code defects.

This document supersedes `PHASE3_REPORT.md` and `FINAL_INTEGRATION.md` as the
single engineering account of the platform's current state.