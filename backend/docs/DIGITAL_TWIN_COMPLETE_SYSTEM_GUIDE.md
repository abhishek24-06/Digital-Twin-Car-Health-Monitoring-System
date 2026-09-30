# Digital Twin — Complete System Guide (Authoritative)

> **Scope.** This is the single authoritative reference for the Digital Twin
> Car Health Monitoring Platform backend (Phases 1–6). Every statement here was
> verified against the actual repository: source code, Alembic migrations,
> configuration, schemas, test suite, and live verification results. Where a
> capability is planned but not implemented, it is explicitly marked
> **NOT IMPLEMENTED** or **FUTURE**. Nothing is claimed that is not in the code.
>
> **Reference revision.** Head of the migration chain `d6a9b1c2e3f4`; this guide
> matches the tree at the time of writing.

---

## Table of contents

1. [System at a glance](#1-system-at-a-glance)
2. [Technology stack](#2-technology-stack)
3. [Directory map](#3-directory-map)
4. [Configuration & environment](#4-configuration--environment)
5. [Database schema & migrations](#5-database-schema--migrations)
6. [Data flow end-to-end](#6-data-flow-end-to-end)
7. [Component deep-dive](#7-component-deep-dive)
8. [End-to-end scenarios](#8-end-to-end-scenarios)
9. [Testing methodology](#9-testing-methodology)
10. [Security](#10-security)
11. [Performance & scaling](#11-performance--scaling)
12. [Observability & error handling](#12-observability--error-handling)
13. [Troubleshooting](#13-troubleshooting)
14. [Known limitations & planned work](#14-known-limitations--planned-work)
15. [Phase status](#15-phase-status)
16. [Appendix](#16-appendix)

---

## 1. System at a glance

The platform ingests OBD-II telemetry from vehicles (real devices over MQTT, or
the built-in deterministic simulator), stores it in PostgreSQL, and produces:

- **Vehicle Health Contexts** — deterministic, explainable health assessments
  computed from a configurable telemetry window (Phase 3).
- **Agentic diagnoses** — a LangGraph supervisor workflow that grounds
  natural-language queries and critical telemetry events against the
  deterministic health context and, in Phase 5, against manufacturer
  documentation retrieved through hybrid (dense+lexical) RAG (Phase 4/5).

There is **no scheduler** and **no background analytics job**: health analysis
and agent diagnosis are triggered explicitly via the REST API. Telemetry *is*
continuously ingested by a long-lived MQTT subscriber.

### 1.1 Pipeline: telemetry ingestion

```mermaid
flowchart LR
    DEV["Vehicle / Simulator<br/>simulator.main (QoS 1, retain=false)"]
    RST["REST API<br/>POST /api/v1/vehicles/{id}/telemetry"]
    BRK["Mosquitto broker<br/>vehicles/{id}/telemetry"]
    SUB["app.mqtt.subscriber<br/>(reconnect + backoff)"]
    PARS["TelemetryMessageParser<br/>decode + validate"]
    TS["TelemetryService<br/>(idempotency by source_event_id)"]
    REPO["TelemetryRepository"]
    PG[("PostgreSQL / Supabase<br/>telemetry_records")]

    DEV -->|"vehicles/{id}/telemetry"| BRK
    BRK --> SUB --> PARS --> TS
    RST --> TS
    TS --> REPO --> PG
```

Both ingestion paths share the exact same `TelemetryService →
TelemetryRepository` code. Idempotency lives in the service; the partial unique
index on `(vehicle_id, source_event_id)` is the database-level backstop against
concurrent duplicates.

### 1.2 Pipeline: health context & agent diagnosis

```mermaid
flowchart LR
    PG[("PostgreSQL<br/>telemetry_records")]
    VHS["VehicleHealthService"]
    ENG["HealthAnalysisEngine (deterministic, no LLM)"]
    ST["statistics"] --> TR["trends"] --> BL["baselines"] --> RU["rules"] --> SC["scoring/confidence"] --> CTX["HealthContext"]
    SNAP[("vehicle_health_snapshots (immutable JSONB)")]
    AG["AgentService (LangGraph)"]
    SUP["supervisor node"]
    RAGN["rag node<br/>(ManufacturerGuidanceTool)"]
    REA["reason node<br/>(LLM via providers)"]
    VAL["validate node<br/>(grounding + deterministic clamps)"]
    PER["persist node<br/>agent_diagnoses"]
    TOOL["VehicleContextTool<br/>(bounded JSON context)"]
    MGT["ManufacturerGuidanceTool<br/>(hybrid RAG evidence)"]

    PG --> VHS --> ENG --> CTX
    CTX --> SNAP
    CTX --> AG
    AG --> SUP --> TOOL --> CTX
    SUP --> RAGN --> MGT --> RAGN
    RAGN --> REA --> VAL --> PER
```

Sub-component detail:

```mermaid
flowchart LR
    SR["RAGService.search"]
    QB["QueryPlan<br/>(VIN/feature noise stripped)"]
    EMB["bge-m3 embeddings<br/>(1024-dim)"]
    REPO["RagRepository.hybrid_search<br/>(dense + FTS lexical)"]
    FUSE["fusion + dedup (alpha 0.6)"]
    SCOP["scope filter<br/>EXACT_VEHICLE > MODEL > MAKE > GENERIC"]
    RR["bge-reranker-v2-m3<br/>(threshold 0.2)"]
    PROV["provenance + citations"]
    AGENTAG["prompt: docs = data (never instructions)"]

    SR --> QB --> EMB --> REPO --> FUSE --> SCOP --> RR --> PROV --> AGENTAG
```

All component, router, data-flow, and test detail is in the sections below.

---

## 2. Technology stack

| Area             | Choice                                                         |
| ---------------- | -------------------------------------------------------------- |
| Language         | Python 3.12+ (`requires-python = ">=3.12"`)                    |
| Web framework    | FastAPI ≥0.115, Uvicorn                                        |
| Validation       | Pydantic v2, pydantic-settings                                 |
| ORM              | SQLAlchemy 2.x async + asyncpg                                 |
| Agent            | LangGraph state graph + supervisor pattern (Phase 4)           |
| LLM SDK          | LangChain `langchain-openai` ≥0.2 over OpenAI-compatible Chat Completions |
| LLM providers    | OpenRouter (primary), Groq (fallback), deterministic Mock (tests) |
| Vector store     | pgvector 0.8.2 (`vector(1024)`, HNSW cosine) over PostgreSQL   |
| Embedding        | `BAAI/bge-m3` (1024-dim) via `sentence-transformers`/HF        |
| Reranker         | `BAAI/bge-reranker-v2-m3`                                      |
| Document parsing | Docling (PDF/DOCX/…), plain-text/markdown parser               |
| SQL migrations   | Alembic (schema owned exclusively by Alembic — no `create_all` at startup) |
| MQTT client      | aiomqtt 2.x (asyncio wrapper over paho-mqtt)                   |
| Broker           | Mosquitto 2 (Docker credentialed / local loopback anonymous)   |
| Database         | PostgreSQL 16 local dev / Supabase managed PostgreSQL (deploy) |
| Tests            | pytest 8, pytest-asyncio, httpx (ASGI transport)               |
| Lint/format      | Ruff (E,F,W,I,UP,B,YTT; line-length 100; target py312)         |
| Container        | Docker, Docker Compose                                         |

---

## 3. Directory map

```
backend/
├── app/
│   ├── main.py                    # FastAPI app, lifespan, CORS, exception handlers
│   ├── api/
│   │   ├── router.py              # api_router aggregating all route modules
│   │   └── routes/                # health, vehicles, telemetry, vehicle_health, agent, rag
│   ├── core/
│   │   ├── config.py              # Settings (env/.env); MQTT + health settings
│   │   ├── database.py            # async engine (NullPool in tests) + session factory + probe
│   │   ├── exceptions.py          # AppError / NotFoundError / ConflictError / DatabaseError
│   │   └── logging.py             # root logger configured once per process
│   ├── dependencies/
│   │   └── database.py            # FastAPI dependency: async session per request
│   ├── models/                    # vehicles, telemetry, health_snapshot, agent_diagnosis, rag, base
│   ├── schemas/                   # vehicle, telemetry, health, vehicle_health, agent, rag, common
│   ├── repositories/              # vehicle, telemetry, health_snapshot, agent_diagnosis, rag_repository
│   ├── services/                  # vehicle, telemetry, vehicle_health
│   ├── intelligence/              # models, statistics, trends, baselines, rules, scoring, context, engine
│   ├── agent/                     # config, errors, triggers, schemas, determinism, grounding,
│   │                              # prompts, llm_service, state, nodes, graph, service, rag_dispatch,
│   │                              # citations, providers/{base,factory,openrouter,groq,mock},
│   │                              # tools/{vehicle_context,manufacturer_guidance}
│   ├── mqtt/                      # topics, schemas, parser, client, publisher, subscriber, exceptions
│   └── rag/                       # config, errors, schemas, scope, chunking, embeddings,
│                                  # query_builder, retrieval, ingestion, repository, rag_service,
│                                  # parser/{base,docling,plain_text}, reranker/base
├── simulator/                     # config, vehicle, telemetry_generator, publisher, main
├── scripts/                       # check_db, seed_demo_vehicle, smoke_agent_llm,
│                                  # ingest_documents, query_rag, phase5_real_model_smoke,
│                                  # phase5_agent_rag_verify
├── infrastructure/mosquitto/      # mosquitto.conf (Docker), mosquitto.local.conf, mosquitto.acl
├── alembic/                       # env.py, versions (6), script.py.mako
├── tests/                         # conftest.py, api/, services/, mqtt/, simulator/,
│                                  # intelligence/, agent/, rag/
├── .env.example  alembic.ini  Dockerfile  docker-compose.yml
├── Makefile  pyproject.toml  README.md
└── docs/                          # phase reports + this guide + quickstart
```

---

## 4. Configuration & environment

Configuration uses **pydantic-settings** (`app/core/config.py`): every value can
be set via environment variable or `backend/.env`. `.env` is git-ignored and
must never contain production secrets. The API fails clearly at startup if
`DATABASE_URL` is missing; the simulator refuses to start without
`SIMULATOR_VEHICLE_ID`.

### 4.1 Settings table

| Field (settings class)                 | Env var / alias                 | Default / bounds                     | Purpose |
| -------------------------------------- | ------------------------------- | ------------------------------------ | ------- |
| `app_name`                             | `APP_NAME`                      | `Digital Twin API`                   | App title / FastAPI title |
| `app_version`                          | — (also `APP_VERSION`)          | `0.1.0`                              | Version in OpenAPI |
| `app_env`                              | `APP_ENV`                       | `development`                        | Used for `DEBUG`, test pool selection |
| `debug`                                | `DEBUG`                         | `false`                              | SQL echo / log verbosity |
| `database_url`                         | `DATABASE_URL`                  | **required**                         | asyncpg DSN (`?ssl=require` for Supabase) |
| `cors_origins`                         | `CORS_ORIGINS`                  | `["http://localhost:3000"]`          | JSON array of allowed origins |
| `mqtt_broker_host`                     | `MQTT_BROKER_HOST`              | `localhost`                          | Broker hostname |
| `mqtt_broker_port`                     | `MQTT_BROKER_PORT`              | `1883`                               | Broker port |
| `mqtt_username` / `mqtt_password`      | `MQTT_USERNAME` / `MQTT_PASSWORD` | empty (anonymous)                  | Credentials passed only when both set |
| `mqtt_client_id`                       | `MQTT_CLIENT_ID`                | per-process `dtwin-sub-<hex8>`       | Unique client id per process (avoid session takeover on Windows) |
| `mqtt_keepalive`                       | `MQTT_KEEPALIVE`                | `60`                                 | Broker keepalive seconds |
| `mqtt_qos`                             | `MQTT_QOS`                      | `1`                                  | Envelope QoS |
| `mqtt_topic_prefix`                    | `MQTT_TOPIC_PREFIX`             | `vehicles`                           | `{prefix}/{vehicle_id}/telemetry` + `/status`; subscribe `{prefix}/+/telemetry` |
| `mqtt_reconnect_max_seconds`           | `MQTT_RECONNECT_MAX_SECONDS`    | `30.0`                               | Cap for exponential backoff reconnects |
| `mqtt_message_retry_attempts`          | `MQTT_MESSAGE_RETRY_ATTEMPTS`   | `3`                                  | Bounded DB retries before giving up a message |
| `health_analysis_window_minutes`       | `HEALTH_ANALYSIS_WINDOW_MINUTES`| `15`                                 | Default analysis window |
| `health_minimum_samples`               | `HEALTH_MINIMUM_SAMPLES`        | `10`                                 | Min samples for a confident assessment |
| `health_expected_interval_seconds`     | `HEALTH_EXPECTED_INTERVAL_SECONDS` | `1.0`                              | Expected telemetry interval (gap estimation) |
| `health_baseline_window_minutes`       | `HEALTH_BASELINE_WINDOW_MINUTES`| `360`                                | History used for vehicle baselines |
| `health_baseline_minimum_samples`      | `HEALTH_BASELINE_MINIMUM_SAMPLES` | `5`                                | Min history for a baseline comparison |
| `llm_primary_provider`                 | `LLM_PRIMARY_PROVIDER`          | `openrouter`                         | Tried first (`openrouter\|groq\|mock`) |
| `llm_fallback_provider`                | `LLM_FALLBACK_PROVIDER`         | `groq`                               | Built lazily; skipped when unconfigured |
| `openrouter_api_key` / `openrouter_model` | `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | `None` / `""`            | Primary provider credentials/model |
| `groq_api_key` / `groq_model`          | `GROQ_API_KEY` / `GROQ_MODEL`   | `None` / `""`                        | Fallback provider credentials/model |
| `llm_request_timeout_seconds`          | `LLM_REQUEST_TIMEOUT_SECONDS`   | `60.0`                               | LLM call timeout |
| `llm_max_retries`                      | `LLM_MAX_RETRIES`               | `2`                                  | Retry count on retryable provider errors |
| `llm_temperature`                      | `LLM_TEMPERATURE`               | `0.1`                                | Prompt sampling temperature |
| `llm_max_tokens`                       | `LLM_MAX_TOKENS`                | `1500`                               | Output cap |
| `llm_context_max_chars`                | `LLM_CONTEXT_MAX_CHARS`         | `24000`                              | Context serialization cap fed to the LLM |
| `agent_critical_event_cooldown_seconds`| `AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS` | `300`                        | Dedup window for identical critical events |
| `run_llm_smoke_test`                   | `RUN_LLM_SMOKE_TEST`            | `false`                              | Gates `scripts/smoke_agent_llm.py` |
| `rag_enabled`                          | `RAG_ENABLED`                   | `true` (false in tests)              | Global RAG gate |
| `rag_embedding_model`                  | `RAG_EMBEDDING_MODEL`           | `BAAI/bge-m3`                        | Embedding model id |
| `rag_embedding_dimension`              | `RAG_EMBEDDING_DIMENSION`       | `1024`                               | Fixed vector dimension |
| `rag_embedding_device`                 | `RAG_EMBEDDING_DEVICE`          | `auto`                               | Compute device |
| `rag_embedding_batch_size`             | `RAG_EMBEDDING_BATCH_SIZE`      | `16`                                 | Embedding batch size |
| `rag_embedding_max_length`             | `RAG_EMBEDDING_MAX_LENGTH`      | `1024`                               | Tokenizer max length |
| `rag_embedding_normalize`              | `RAG_EMBEDDING_NORMALIZE`       | `true`                               | Cosine normalization |
| `rag_reranker_model`                   | `RAG_RERANKER_MODEL`            | `BAAI/bge-reranker-v2-m3`            | Reranker model id |
| `rag_reranker_device`                  | `RAG_RERANKER_DEVICE`           | `auto`                               | Reranker compute device |
| `rag_reranker_max_length`              | `RAG_RERANKER_MAX_LENGTH`       | `512`                                | Reranker tokenizer max length |
| `rag_chunk_size`                       | `RAG_CHUNK_SIZE`                | `800`                                | Chunker target chars |
| `rag_chunk_overlap`                    | `RAG_CHUNK_OVERLAP`             | `120`                                | Chunker overlap chars |
| `rag_retrieval_top_k`                  | `RAG_RETRIEVAL_TOP_K`           | `25`                                 | Candidate fetch limit |
| `rag_rerank_top_k`                     | `RAG_RERANK_TOP_K`              | `30`                                 | Rerank shortlist cap |
| `rag_final_top_k`                      | `RAG_FINAL_TOP_K`               | `5`                                  | Final evidence cap |
| `rag_hybrid_alpha`                     | `RAG_HYBRID_ALPHA`              | `0.6`                                | Dense weight in hybrid fusion (1−α lexical) |
| `rag_min_rerank_score`                 | `RAG_MIN_RERANK_SCORE`          | `0.2`                                | Rerank admission threshold |
| `rag_min_score`                        | `RAG_MIN_SCORE`                 | `0.0`                                | Final score floor |
| `rag_max_document_bytes`               | `RAG_MAX_DOCUMENT_BYTES`        | 50 MiB                               | Ingestion guard |
| `rag_max_document_pages`               | `RAG_MAX_DOCUMENT_PAGES`        | `2000`                               | Ingestion guard |
| `rag_max_chunks`                       | `RAG_MAX_CHUNKS`                | `20000`                              | Ingestion guard |
| `rag_document_roots`                   | `RAG_DOCUMENT_ROOTS`            | default corpus roots                 | Restricts CLI ingestion paths |
| `rag_query_max_chars`                  | `RAG_QUERY_MAX_CHARS`           | `500`                                | Query leniency guard |
| `rag_evidence_max_chars`               | `RAG_EVIDENCE_MAX_CHARS`        | `1800`                               | Per-evidence context cap |
| `rag_max_upload_size_mb`               | `RAG_MAX_UPLOAD_SIZE_MB`        | `50`                                 | Admin upload ceiling (413 above it) |

**Tests**: `tests/conftest.py` forces `RAG_ENABLED=false`, `APP_ENV=test`,
`DEBUG=false`, and `DATABASE_URL` to `TEST_DATABASE_URL` (default
`postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_test`) **before
any app model imports**, and refuses to start if the test URL host looks hosted
(`supabase`/`pooler`).

### 4.2 Simulator settings (separate `Settings` class)

| Field                  | Env var / alias                           | Default    |
| ---------------------- | ----------------------------------------- | ---------- |
| `vehicle_id`           | `SIMULATOR_VEHICLE_ID`                    | **required** |
| `scenario`             | `SIMULATOR_SCENARIO`                      | `normal` (`normal\|high_temperature\|low_battery\|high_engine_load`) |
| `interval_seconds`     | `SIMULATOR_INTERVAL_SECONDS`              | `1.0`      |
| `seed`                 | `SIMULATOR_SEED`                          | `42`       |
| `initial_odometer`     | `SIMULATOR_INITIAL_ODOMETER`              | `45231.7`  |
| `initial_fuel_level`   | `SIMULATOR_INITIAL_FUEL_LEVEL`            | `75.0`     |
| `initial_engine_runtime` | `SIMULATOR_INITIAL_ENGINE_RUNTIME`      | `1820.0`   |
| `off_seconds` / `starting_seconds` / `idle_seconds` / `accelerating_seconds` / `cruising_seconds` / `decelerating_seconds` | `SIMULATOR_OFF_SECONDS` / `SIMULATOR_STARTING_SECONDS` / `SIMULATOR_IDLE_SECONDS` / `SIMULATOR_ACCELERATING_SECONDS` / `SIMULATOR_CRUISING_SECONDS` / `SIMULATOR_DECELERATING_SECONDS` | `2 / 3 / 10 / 15 / 30 / 10` |
| `cruise_speed`         | `SIMULATOR_CRUISE_SPEED`                  | `60.0`     |
| `mqtt_*`               | `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` / `MQTT_USERNAME` / `MQTT_PASSWORD` / `MQTT_TOPIC_PREFIX` / … | same platform defaults |
| `mqtt_client_id`       | per-process `dtwin-sim-<hex8>`            | unique     |

---

## 5. Database schema & migrations

Schema is owned **exclusively by Alembic**; the application never calls
`create_all()` at startup. Migration chain (all applied on Supabase, head
`d6a9b1c2e3f4`):

```
e01c2724f67b  initial scaffold (vehicles, telemetry_records)
e01c2724f67b ──► 7e38f4f3d70b  add source_event_id + partial UNIQUE index
               ──► a1b2c3d4e5f6  vehicle_health_snapshots
               ──► c7f2e8a1b3d4  agent_diagnoses
               ──► 4f9d3c2b1a8e  RAG tables + CREATE EXTENSION vector + HNSW/GIN
               ──► b8c3e1d4a9f7  rag_* columns on agent_diagnoses
               ──► d6a9b1c2e3f4  Phase 6: users, refresh_tokens, vehicle ownership
```

### 5.1 `vehicles`

| Column        | Type      | Notes                               |
| ------------- | --------- | ----------------------------------- |
| `id`          | uuid PK   | client-side `uuid4` default         |
| `vin`         | string    | unique; normalized uppercase at API boundary |
| `make`, `model`, `year`, `engine_type` | | Pydantic: year ∈ 1900–2100, VIN 5–50 chars |
| `owner_user_id` | uuid FK | → `users.id`, `ON DELETE SET NULL`, indexed (Phase 6) |
| `source_type` | string    | CHECK `simulator|real`, default `simulator` (Phase 6) |
| `status`      | string    | CHECK `active|disabled`, default `active` (Phase 6) |
| `simulation_enabled` | bool | default `false` (Phase 6) |
| `created_at`, `updated_at` | timestamptz | |

Owning is assigned at creation (`owner_user_id` = the authenticated caller).
Endpoints enforce ownership for non-admin users (404 for anything unowned or
owned by someone else).

### 5.2 `telemetry_records`

- `id` uuid PK; `vehicle_id` FK → `vehicles.id` `ON DELETE CASCADE`.
- `timestamp` timestamptz (timezone enforced at the MQTT boundary).
- 11 metric columns: `rpm`, `speed`, `engine_load`, `coolant_temperature`,
  `oil_temperature`, `battery_voltage`, `fuel_level`,
  `intake_air_temperature`, `throttle_position`, `engine_runtime`, `odometer`.
- `source_event_id` nullable; **partial unique index**
  `(vehicle_id, source_event_id) WHERE source_event_id IS NOT NULL` — one event
  id per vehicle; rows ingested with identical ids (MQTT or REST) are deduped.

### 5.3 `vehicle_health_snapshots` (immutable)

`id`, `vehicle_id` FK CASCADE, `generated_at`, `window_start`, `window_end`,
`sample_count`, `health_score`, `health_status`, `confidence`,
`context_schema_version`, `context_json` (JSONB, full context), `created_at`.
Indexes: `(vehicle_id, generated_at)` and `(vehicle_id, health_status,
generated_at)`. Snapshots are never mutated — re-analysis inserts a new row.

### 5.4 `agent_diagnoses`

`id`, `vehicle_id` FK CASCADE, `agent_run_id`, `trigger_type`, `user_query`,
`diagnosis` (JSONB, grounded structured response), plus promoted queryable
columns: `severity`, `confidence`, `status`, `error_code`, `provider`, `model`,
`fallback_used`, `latency_ms`, `input_tokens`, `output_tokens`,
`context_timestamp` — and Phase 5: `rag_used`, `rag_evidence_count`,
`rag_embedding_model`, `rag_reranker_model`, `rag_scope` (JSONB); Phase 6 adds
`user_id` (uuid FK → `users.id`, `ON DELETE SET NULL`) recording who triggered
the run.
Indexes: `(vehicle_id, created_at)` and `(vehicle_id, trigger_type, created_at)`.

### 5.A Phase 6 identity tables (migration `d6a9b1c2e3f4`)

**`users`** — `id` uuid PK, `email` (unique, case-normalized), `password_hash`
(bcrypt), `role` (CHECK `user|admin`), `full_name` (nullable),
`is_active` (bool), `created_at`, `updated_at`. Only the `user` role is
assignable via the public API; admin promotion is a privileged, DB-level
action.

**`refresh_tokens`** — `id` uuid PK, `user_id` FK → `users.id` `ON DELETE
CASCADE`, `token_hash` (SHA-256 of the raw token, indexed — raw tokens are
never stored), `expires_at` (timestamptz), `revoked_at` (nullable).
Tokens are single-use: a refresh rotates the row, and reuse of an already
revoked token revokes **all** of that user's tokens (theft detection).

### 5.5 RAG tables (migration `4f9d3c2b1a8e` + `b8c3e1d4a9f7`)

**`rag_documents`** — identity + scope only:
`id`, `source_type` (default `manufacturer`), `canonical_source` (**UNIQUE**),
`source_uri`, `manufacturer`, `make`, `model`, `model_year_start/end`,
`document_type`, `title`, `language`, `created_at`, `updated_at`. Indexes on
`(make, model)` and `(manufacturer)`. Scope fields are nullable on purpose:
`NULL` never invents a constraint.

**`rag_document_versions`** — immutable snapshots:
`id`, `document_id` FK, `version` (int), `content_hash` (sha256, indexed),
`source_filename`, `parser_name`, `parser_version`, `language`, `page_count`,
`metadata` (JSON), `embedding_model`, `embedding_dimension` (default 1024),
`chunking_version`, `ingestion_status` (`pending|unchanged|completed|failed`),
`error_message`, `created_at`. `UNIQUE(document_id, version)`.

**`rag_chunks`**:
`id`, `document_version_id` FK, `chunk_index` (0-based), `chunk_type`
(`section|continuation|preamble`), `title`, `section_title`, `heading_path`
(JSON), `page_start/end`, `start_char/end_char`, `content_plain`, `scope`
(`GENERIC|MAKE|MODEL|EXACT_VEHICLE`), `make`, `model`, `year_start/end`,
`embedding_store` **`vector(1024)`** (+ **HNSW `vector_cosine_ops`** index),
`content_tsv` (+ **GIN** index, populated by a migration trigger), `created_at`.
`UNIQUE(document_version_id, chunk_index)`.

Embedding columns are created via a lazy factory (`make_embedding_column`) so
the package stays importable when the extension is absent locally. The local
`digital_twin_test` database has **no pgvector** installed, so the pgvector-gated
integration tests skip there; they run live against Supabase via
`scripts/phase5_agent_rag_verify.py`.

---

## 6. Data flow end-to-end

1. **Capture.** A vehicle/`simulator.main` publishes a telemetry envelope
   (QoS 1, `retain=false`) to `vehicles/{vehicle_id}/telemetry`; it also
   publishes `online`/`offline` status envelopes to `vehicles/{vehicle_id}/status`
   (status messages are **not persisted**; informational only).
2. **Ingest.** `app/mqtt/subscriber.py` (long-lived, reconnecting) delivers to
   `TelemetryMessageParser`, which decodes/validates, then calls
   `TelemetryService.create_telemetry()`. REST `POST .../telemetry` calls the
   same service. Duplicate `source_event_id` → no-op; unknown/malformed/out of
   range → logged + skipped (never crashes the loop).
3. **Store.** `TelemetryRepository` inserts rows; the partial unique index
   backstops concurrent duplicates (IntegrityError mapped to a silent skip).
4. **Analyze.** `POST /vehicles/{id}/health/analyze` →
   `VehicleHealthService`: loads window + baseline telemetry, feeds typed
   `TelemetryPoint(timestamp, values)` into the pure engine
   (statistics → trends → baselines → rules → scoring → confidence →
   `HealthContext`), persists an immutable snapshot, returns the context.
5. **Reason.** `POST /vehicles/{id}/agent/query` (or a critical telemetry event)
   → `AgentService`: supervisor gathers bounded context (VehicleContextTool),
   dispatches to RAG when appropriate (ManufacturerGuidanceTool retrieves
   scoped evidence), the reason node calls the LLM with a structured-output
   contract, the validate node grounds evidence and clamps severity/confidence
   deterministically, and persist writes `agent_diagnoses`.
6. **Retrieve (RAG).** Corpus builds via `scripts/ingest_documents.py`
   (parser → structure-aware chunking → bge-m3 embeddings → vector + FTS
   rows). Searches run dense+lexical hybrid fusion (α=0.6), scope filtering,
   reranking (threshold ≥ 0.2), and citation provenance.
7. **Observe.** `/api/v1/health`, `/api/v1/health/db`, `/api/v1/rag/health`,
   `/openapi.json`, and structured log lines.

---

## 7. Component deep-dive

### 7.1 API layer (`app/main.py`, `app/api/`, `app/dependencies/`)

- `main.py` registers the router under `api_v1_prefix`, installs CORS, and
  wires the full exception-handler map (see §12). Lifespan initializes the async
  engine and logs a warning (but still serves) when the DB is unreachable.
- `dependencies/database.py` yields an `AsyncSession` per request
  (rollback/close on exit).
- Route modules and their behaviors:

| Route module | Base path | Notable validation / contract |
| ------------ | --------- | ----------------------------- |
| `health.py` | `/health`, `/health/db` | `/health` = liveness, no DB touch; `/health/db` runs `SELECT 1`, returns 503 + `{"status":"degraded"}` when down |
| `vehicles.py` | `/vehicles` | list (page_size ≤ 100, default 20), create 201 (VIN uppercased, 5–50; year 1900–2100; 409 on duplicate VIN), get/patch/delete `/{vehicle_id}` (delete cascades) |
| `telemetry.py` | `/vehicles/{id}/telemetry` | list (page_size ≤ 500, default 50; `start_time`/`end_time` ISO filters), create 201 (`extra="forbid"`; optional `source_event_id`; idempotent) |
| `vehicle_health.py` | `/vehicles/{id}/health` | `POST /analyze` (200; `window_minutes` 1–1440, default from settings), `GET ""` latest (404 when none), `GET /history` (paginated, newest first) |
| `agent.py` | `/vehicles/{id}/agent` | `POST /query` (query 1–2000 chars, stripped), `POST /events/critical` (rule_ids ≤ 100; cooldown dedup), `GET /dashboard` (no LLM), `GET /diagnoses`, `GET /diagnoses/latest` (404 when none) |
| `rag.py` | `/rag` | `GET /health` (503 with stable detail when disabled / pgvector missing), `GET /search` (query required, optional `VehicleScope`; empty query → 422) |

Pydantic validation is centralized in `app/schemas/`: `VehicleCreate/Update/
Response`, `TelemetryCreate/Response`, `HealthResponse`/`HealthDBResponse`,
`HealthContextResponse`, `VehicleHealthResponse`, `PaginatedResponse[T]`,
`AgentQueryRequest`, `CriticalEventRequest`, `AgentDiagnosisItem`
(including `rag_*` fields), `DashboardResponse`.

### 7.2 Service layer (`app/services/`)

- **`VehicleService`** — create/get/by VIN/list/update/delete; commits at the
  operation boundary; maps `IntegrityError` → `ConflictError`.
- **`TelemetryService`** — `create_telemetry` is **idempotent** by
  `source_event_id`; raises `NotFoundError` for unknown vehicles; reused by
  both REST and MQTT paths.
- **`VehicleHealthService`** — loads `window_minutes` telemetry plus the
  bounded baseline window (**window limit = expected samples × 2 + 100**),
  maps ORM rows → `TelemetryPoint`, runs the engine, persists the immutable
  snapshot via `HealthSnapshotRepository`.

### 7.3 Repository layer (`app/repositories/`)

Raw-SQL / ORM persistence with no business rules, all surfacing `NotFoundError`
/ `ConflictError`:

- `VehicleRepository` — `get_by_id`, `get_by_vin`, `list_vehicles` (paginated),
  `create`, `update`.
- `TelemetryRepository` — `create`, `get_by_source_event_id`,
  `list_by_vehicle` (time filter + pagination).
- `HealthSnapshotRepository` — `create`, `get_by_id`, `get_latest_by_vehicle`,
  `list_by_vehicle`.
- `AgentDiagnosisRepository` — `create`, `get_by_id`, `get_latest_by_vehicle`,
  `list_by_vehicle` (optional `trigger_type`/`status` filters).
- `RagRepository` (raw asyncpg-style over `AsyncConnection`, caller transaction)
  — `hybrid_search`, scope-contradiction filtering, vector literal rendering,
  health/corpus counts. Reads only **completed** versions.

### 7.4 Intelligence engine — Phase 3 (deterministic)

`app/intelligence/` is a **pure, transport-agnostic** package: no DB, no MQTT,
no API. It consumes `TelemetryPoint(timestamp, values)` and emits a typed,
versioned, JSON-serializable `HealthContext`.

Pipeline (each stage fully unit-tested):

| Stage            | What it produces                                          |
| ---------------- | --------------------------------------------------------- |
| `statistics.py`  | Robust summary stats per metric (mean/median/min/max/IQR/std-dev/CV), never NaN/Inf |
| `trends.py`      | OLS slope + normalized slope → `increasing / decreasing / stable` |
| `baselines.py`   | Median + scaled MAD (1.4826·MAD) of the vehicle's own history; `|dev| > 2.0` → `within / elevated / depressed` |
| `rules.py`       | `RuleThresholds` → **factual findings** (never mechanical diagnoses) |
| `scoring.py`     | Score = 100 − penalties (info 0 / warning 10 / critical 30; **40/category cap**); status ≥80 `healthy`, 60–79 `attention`, <60 `critical`, insufficient data → `unknown` |
| `confidence`     | Data-quality confidence **in the assessment** (coverage, duration, sample sufficiency, metric completeness) — explicitly NOT a health probability |
| `context.py`     | `HealthContext` assembly (`context_schema_version` = `1.0`, `rule_engine_version` = `1.0`) |
| `engine.py`      | Orchestration: statistics → trends → baselines → rules → scoring → confidence |

`RuleThresholds` (verified in code):

| Metric                  | Thresholds                                              |
| ----------------------- | ------------------------------------------------------- |
| coolant temperature     | high ≥ 100, critical ≥ 110; rapid rise > 8 within window |
| oil temperature         | high ≥ 100, critical ≥ 110                              |
| battery voltage         | low < 12 / critical < 10.5; over-charge > 15            |
| engine load (mean)      | high > 40 / severe > 60                                 |
| rpm (mean)              | high > 4500                                             |
| fuel level              | low < 15 / critical < 5                                 |
| data coverage           | `coverage_minimum: 0.5`; `INSUFFICIENT_DATA` rule if samples < `HEALTH_MINIMUM_SAMPLES` |
| gap detection           | `gap_multiplier: 3` of expected interval                |

Metric units map (`METRIC_UNITS`, 11 metrics): `rpm` RPM, `speed` km/h,
`engine_load` %, `coolant_temperature`/`oil_temperature`/`intake_air_temperature`
°C, `battery_voltage` V, `fuel_level` %, `throttle_position` %,
`engine_runtime` s, `odometer` km.

**Explicitly NOT ML / not predictive:** no model, no priors, no manual data —
all findings are statements about the telemetry.

### 7.5 Agent — Phase 4 (`app/agent/`)

LangGraph **supervisor** workflow. Verified graph flow:

```
START
  └─► supervisor   (gathers bounded context via VehicleContextTool;
                     decides needs_llm = has_context; needs_rag via rag_dispatch)
        │
        ├─ [needs_rag]  rag node → ManufacturerGuidanceTool (hybrid RAG,
        │                  threshold-gated, provenance) → injects guidance
        │                  into the prompt — docs = DATA, never instructions
        ├─ [needs_llm]  reason node → LLM (structured-output contract,
        │                  JSON only, no chain-of-thought)
        └─ [no context] validate node directly (canned grounded reasoning)
        │
        ▼
     validate   (grounding + deterministic clamps — see below)
        ▼
     persist    (writes agent_diagnoses; sets stop/abort conditions)
        ▼
      END
```

Deterministic control (the LLM can never override):

- **Severity** (`derive_severity`): the highest-severity finding wins
  (rank critical > warning > info); with no findings, falls back to
  `health_status` (critical → critical, attention → warning, else info).
  The LLM's assessed severity is **clamped to ≤ rule-severity** per finding.
- **Confidence** (`derive_confidence`): `score_confidence * 0.6 +
  data_factor * 0.4` where `data_factor = 0.5 + 0.5·coverage`, bounded to
  **[0.05, 0.95]**. The LLM's confidence must stay within **±0.2** of the
  deterministic value.
- **Evidence grounding** (`ground_evidence`): rule ids/metrics not present in
  the deterministic context are dropped with `validation_warnings`; values are
  compared with a 10% tolerance and deduplicated. Fabricated RAG citations are
  dropped (`build_citations_from_sources`), out-of-range/duplicate indexes are
  removed with warnings, and **negative grounding** means zero retrieved
  evidence ⇒ zero manufacturer claims.
- **Persist integrity**: the response is reassembled from validated state and
  `AgentDiagnosisRepository` writes it; no chain-of-thought is persisted.

LLM provider layer (`providers/`): `base.py` uses
`with_structured_output(DiagnosisContent, method="function_calling",
include_raw=True)`; retries use exponential backoff (0.2 s → 2 s); the
**fallback-eligible set** is `{TIMEOUT, RATE_LIMIT, CONNECTION, SERVER,
UNKNOWN, AUTH}` — BAD_REQUEST and structured-output failures are never retried
or rerouted. Providers: `openrouter.py` (base `https://openrouter.ai/api/v1`),
`groq.py` (base `https://api.groq.com/openai/v1`), `mock.py` (deterministic,
used by the whole test suite); `factory.py` maps `mock|groq|openrouter`.
Neither real provider hard-codes a model.

Triggers (`triggers.py`): `USER_QUERY`, `CRITICAL_TELEMETRY_EVENT`
(`POST /events/critical` — identical rule sets within
`AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS` return the existing diagnosis, no new
LLM call), and `DASHBOARD_LOAD` (**no-LLM** hook that still persists).

Prompts (`prompts.py` `SYSTEM_PROMPT`): exactly one JSON object; hypotheses are
wording-corrected; severity never exceeds rule severity; confidence within 0.2
when no rationale; context is treated as **untrusted data**; `cited_sources`
are 1-based indexes.

Grounding/citations edge behavior is negative-gapped: degraded RAG
(empty/malformed evidence, or tool `available=False`) degrades the prompt
instead of crashing the plan.

### 7.6 RAG — Phase 5 (`app/rag/`)

- **Gate**: `RAG_ENABLED` (default `true`; forced `false` in the hermetic test
  suite). Real models are loaded **only** when enabled and used; the offline
  suite never touches Hugging Face.
- **Embeddings** (`embeddings.py`): adapter factory
  (`get_embedding_adapter`), real `bge-m3` + deterministic stub for tests,
  fixed 1024-dim with dimension validation.
- **Reranker** (`reranker/base.py`): adapter factory (`get_reranker_adapter`),
  real `bge-reranker-v2-m3` + hash-deterministic `StubRerankerAdapter`;
  `threshold_filter` shared by both paths.
- **Chunking** (`chunking.py`): `chunk_by_structure`, `CHUNKING_VERSION=
  "structural-1.0.0"`, target 800 chars / overlap 120; heading hierarchy →
  `heading_path`; chunk types `section|continuation|preamble`; `approx_pages`
  using ~4400 chars/page.
- **Parsers** (`parser/`): `base.py` (`ParseResult`, `ParsedSection`,
  `make_plain_result`, `sections_from_text`, `sha256_hex`); `docling.py`
  (registry: 14 DOCLING extensions incl. PDF/DOCX; PLAIN_TEXT_EXTENSIONS;
  lazy import, loud `RAGParseError`, **no silent fallback**); `plain_text.py`
  (`.txt/.md/.text`, `----- Page 12 -----` markers, BOM/zero-width stripping).
- **Query builder** (`query_builder.py`): `QueryPlan` with raw/text/
  `lexical_variants`/`decoded_vin`; `strip_vin` regex
  `\b[0-9A-HJ-NPR-Z]{17}\b`.
- **Retrieval** (`retrieval.py`): `hybrid_search` → fusion (`rag_hybrid_alpha`,
  default 0.6 dense) → dedup → **scope filter** → `rerank_and_select`
  (top-k 25 → rerank 30 → final 5, threshold ≥ `rag_min_rerank_score`).
- **Scope** (`scope.py`): `derive_tier` — `EXACT_VEHICLE` (make+model+year) >
  `MODEL` > `MAKE` > `GENERIC`; conservative tier boost (a stronger chunk may
  beat a weaker one, never the reverse).
- **Ingestion** (`ingestion.py`): idempotent + atomic + **immutable versioning**
  via sha256 content hash; identical content ⇒ `unchanged v<n>`, never a
  duplicate version row; `IngestionReport` per file; never raises on a
  file-level failure.
- **Repository** (`repositories/rag_repository.py`): raw-SQL pgvector/FTS over
  the caller's `AsyncConnection`, dense + lexical, vector literal rendering,
  only completed versions, health/corpus stats for `/api/v1/rag/health`.
- **Errors** (`errors.py`): `RAGError` taxonomy — `RAGUnavailableError`,
  `RAGEnabledError`, `RAGConfigurationError`, `RAGVectorUnavailableError`,
  `RAGParseError`, `RAGDocumentNotFoundError`, `RAGDiagnosticsUnavailableError`.
- **Agent integration**: `documents = data, never instructions` guard;
  provenance citations; `rag_used`, `rag_evidence_count`,
  `rag_embedding_model`, `rag_reranker_model`, `rag_scope` persisted on every
  diagnosis.

> **Note:** the Phase 5 report's `app/rag/diagnostics.py` / `evaluation.py`
> references were historical planning entries; neither module exists in the
> tree. Corpus health is served by `/api/v1/rag/health` via `rag_service.py` +
> `rag_repository.py`; offline eval is covered by `tests/rag/` and
> `scripts/phase5_agent_rag_verify.py`. The three docs that cited them have
> been corrected.

### 7.7 MQTT — Phase 2 (`app/mqtt/`)

- **Topics** (`topics.py`, single source of truth): `{prefix}/{vehicle_id}/
  telemetry`, `{prefix}/{vehicle_id}/status`, subscribe
  `{prefix}/+/telemetry` (default prefix `vehicles`).
- **Protocol** (`schemas.py`): `TelemetryMessage` (`schema_version` = 1,
  `event_id` unique per vehicle, `vehicle_id`, tz-aware `timestamp`,
  bounded `telemetry` map — metric range validation, unknown fields rejected);
  `StatusMessage` (`online|offline`). Naive timestamps are rejected.
- **Parser** (`parser.py`): decode + validate; raises `TopicParseError` /
  `InvalidMessageError` (malformed input is logged and skipped, never fatal).
- **Client** (`client.py`): `create_mqtt_client` passes credentials only when
  both set; `run_async` installs a Windows **SelectorEventLoop** (aiomqtt
  `add_reader` requirement).
- **Publisher** (`publisher.py`): long-lived, QoS 1, `retain=false`.
- **Subscriber** (`subscriber.py`): reconnect with exponential backoff capped
  at `MQTT_RECONNECT_MAX_SECONDS`; graceful SIGINT/SIGTERM shutdown; bounded DB
  retries (`MQTT_MESSAGE_RETRY_ATTEMPTS`); malformed/unknown vehicle/duplicate
  → log-and-skip; delegates to `TelemetryService` (no persistence logic).

### 7.8 Simulator — Phase 2 (`simulator/`)

Deterministic drive cycle at a fixed interval:

```
OFF (2s) → STARTING (3s) → IDLE (10s) → ACCELERATING (15s) →
CRUISING (30s) → DECELERATING (10s) → IDLE → … (repeat)
```

- Physical invariants enforced by `SimulationEngine`: fuel decreases only while
  running; odometer increases only with speed; engine runtime accumulates only
  when not `OFF`; voltage tracks the running set-point.
- Scenario modifiers (`telemetry_generator.py`): `high_temperature`
  (coolant/oil targets ~115/108 °C vs 90/88), `low_battery` (running set-point
  ~11.9 V vs 13.9; offline 11.4 V vs 12.5), `high_engine_load` (load multiplier
  1.5 up to 100%).
- Publishes `online` at start and `offline` on graceful shutdown; `main.py`
  runs with `python -m simulator.main`.
- Drive phase durations/seed/interval/cruise speed are all `SIMULATOR_*`
  configurable; the same seed reproduces the same run.

### 7.9 Mosquitto broker configs

- **Docker** (`mosquitto.conf`): listener 1883, `allow_anonymous false`,
  password file generated at container start from `MQTT_USERNAME`/`MQTT_PASSWORD`
  (Compose defaults `mqtt`/`mqtt`, dev-only), ACL file, persistence volume.
- **Local** (`mosquitto.local.conf`): loopback-only, anonymous, persistence at
  `./infrastructure/mosquitto/persist/`.
- **ACL** (`mosquitto.acl`): dev user `mqtt` has `readwrite vehicles/#`.

### 7.10 Scripts (`scripts/`)

| Script | Purpose | Key CLI |
| ------ | ------- | ------- |
| `check_db.py` | Independent asyncpg TLS/DNS probe; prints server version + TLS status | `make db-check` |
| `seed_demo_vehicle.py` | Idempotently create the fixed demo vehicle | `make seed-demo-vehicle` |
| `smoke_agent_llm.py` | Gate-controlled live LLM smoke | `RUN_LLM_SMOKE_TEST=true python -m scripts.smoke_agent_llm` (or `make agent-llm-smoke`) |
| `ingest_documents.py` | CLI corpus intake (real bge-m3 by default; `--stub-embeddings` for tests/eval) | see §8.4; exit 0 all OK / 1 any failure |
| `query_rag.py` | CLI hybrid search + citations + full scoring trail (`--json`, `--stub`, `--no-rerank`, `--top-k`) | see §8.4 |
| `phase5_real_model_smoke.py` | Real BGE-M3/reranker smoke outside pytest | argc-gated flags |
| `phase5_agent_rag_verify.py` | Live E2E verifier (real models vs Supabase; pins `HF_HUB_OFFLINE=1` etc.) | `python scripts/phase5_agent_rag_verify.py` |

---

## 8. End-to-end scenarios

### 8.1 Local stack (no Docker)

Prereqs: Python 3.12+, PostgreSQL 16+, a Mosquitto binary, aiomqtt installed.

```bash
cd backend
python -m venv .venv; .venv\Scripts\activate        # or: make install
pip install -e ".[dev]"
copy .env.example .env                              # edit DATABASE_URL etc.
alembic upgrade head                                # or: make migrate
T.Set^  # (PowerShell) set TEST_DATABASE_URL for tests — see §9

# Terminals:
mosquitto -c infrastructure/mosquitto/mosquitto.local.conf   # broker
uvicorn app.main:app --reload                                # API  (make dev)
python -m app.mqtt.subscriber                                # subscriber
python -m scripts.seed_demo_vehicle                          # demo vehicle
python -m simulator.main                                     # simulator
```

Verify: `curl http://localhost:8000/api/v1/health/db` reports reachable;
`GET /api/v1/vehicles/11111111-2222-4333-8444-555555555555/telemetry?page_size=3`
returns telemetry rows.

### 8.2 Docker stack

```bash
docker compose up --build -d     # or: make up
docker compose logs -f           # or: make logs
docker compose down              # or: make down
```

Starts `postgres` (healthchecked), `backend` (runs `alembic upgrade head` then
serves on 8000), `mosquitto` (credentialed dev user, healthchecked), and
`mqtt-subscriber` + `simulator` (both `restart: unless-stopped`). Compose reads
`DATABASE_URL` (defaults to its own postgres) so the stack can run against any
managed PostgreSQL. Broker password file is generated inside the container —
credentials are never committed.

### 8.3 Master E2E scenario (telemetry → health → agent → RAG)

```bash
# 1) Liveness + DB
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/db

# 2) Register a vehicle (REST path)
curl -X POST http://localhost:8000/api/v1/vehicles \
  -H "Content-Type: application/json" \
  -d '{"vin":"TESTVIN123456789","make":"Toyota","model":"Camry",
       "year":2024,"engine_type":"2.5L Petrol"}'

# 3) Ingest telemetry (REST) — repeat a few times to accumulate samples
curl -X POST http://localhost:8000/api/v1/vehicles/<vehicle_id>/telemetry \
  -H "Content-Type: application/json" \
  -d '{"timestamp":"2026-09-20T08:30:12Z","rpm":3200,"speed":74.0,
       "engine_load":82.4,"coolant_temperature":104.2,"oil_temperature":97.0,
       "battery_voltage":12.1,"fuel_level":64.0,"intake_air_temperature":32.0,
       "throttle_position":41.0,"engine_runtime":1820,"odometer":42150.2,
       "source_event_id":"optional-unique-per-vehicle"}'

# 4) Analyze + read health
curl -X POST http://localhost:8000/api/v1/vehicles/<vehicle_id>/health/analyze
curl http://localhost:8000/api/v1/vehicles/<vehicle_id>/health
curl "http://localhost:8000/api/v1/vehicles/<vehicle_id>/health/history?page=1&page_size=20"

# 5) Agent query (LLM; provider keys in .env) + no-LLM dashboard
curl -X POST http://localhost:8000/api/v1/vehicles/<vehicle_id>/agent/query \
  -H "Content-Type: application/json" -d '{"query":"Should I worry about the coolant?"}'
curl http://localhost:8000/api/v1/vehicles/<vehicle_id>/agent/dashboard

# 6) RAG admin + search (requires corpus + pgvector DB)
curl http://localhost:8000/api/v1/rag/health
curl "http://localhost:8000/api/v1/rag/search?q=coolant&make=Toyota&model=Camry&year=2024"

# 6b) Admin document management (Phase 6.x; admin bearer token required)
curl -X POST http://localhost:8000/api/v1/admin/rag/documents \
  -H "Authorization: Bearer <admin_token>" \
  -F "file=@service_manual.pdf" \
  -F "canonical=rep://acme/camry-2024" -F "make=Acme" -F "model=Camry" -F "year=2024"
curl -H "Authorization: Bearer <admin_token>" \
  "http://localhost:8000/api/v1/admin/rag/documents?page=1&page_size=20&make=Acme"
curl -H "Authorization: Bearer <admin_token>" \
  http://localhost:8000/api/v1/admin/rag/documents/<document_id>
curl -X DELETE -H "Authorization: Bearer <admin_token>" \
  http://localhost:8000/api/v1/admin/rag/documents/<document_id>
```

### 8.4 RAG corpus CLI

```bash
# Ingest (bge-m3 real; --stub-embeddings for deterministic eval)
python scripts/ingest_documents.py "data/toyota_camry_2024_cooling.md" \
    --make Toyota --model Camry --year 2024
python scripts/ingest_documents.py service_manual.pdf \
    --canonical rep://acme/camry-2024 --make Acme --model Camry --year 2024

# Query
python scripts/query_rag.py "coolant level" --make Toyota --model Camry \
    --year 2024 --top-k 3 --json

# Live E2E verification (real models, Supabase pgvector)
python scripts/phase5_agent_rag_verify.py
```

---

## 9. Testing methodology

### 9.1 Running the suite

```bash
set TEST_DATABASE_URL=postgresql+asyncpg://postgres:root@localhost:5432/digital_twin_test
pytest                     # or: make test   (skips broker e2e)
pytest -m mqtt_e2e         # or: make mqtt-test  (requires a running broker)
make lint                  # ruff check .
make format                # ruff check --fix + ruff format .
```

`pyproject.toml` pins `asyncio_mode = "auto"`, `testpaths = ["tests"]`, and
default `addopts = "-q -m 'not mqtt_e2e'"` (marker `mqtt_e2e`).

### 9.2 Harness behavior

- Creates/uses `digital_twin_test`, builds the schema from the models
  (skipping `rag_*` tables when pgvector is unavailable), truncates between
  tests (`clean_db`), tears down afterwards.
- **Refuses to start** when the test URL host looks hosted
  (`supabase`/`pooler`) — destructive fixtures must never hit a shared DB.
- Agent tests run on `MockLLMProvider` — no API keys required; live smoke is
  gated by `RUN_LLM_SMOKE_TEST=true`.
- RAG tests run on **stub** embedder/reranker with `RAG_ENABLED=false`;
  pgvector-gated integration tests skip when the local server lacks the
  extension.

### 9.3 Current results (reference build)

Full suite: **293 passed, 7 skipped (5 pgvector-gated + 2 agent-RAG
integration), 2 deselected (`mqtt_e2e`), exit 0**; `ruff check` clean and
`ruff format --check` clean on all files. Live Phase 5 verification passed on
Supabase: idempotent `v1` ingestion; Honda-vs-Toyota scope isolation;
negative grounding; prompt-injection defense; citation integrity; `rag_*`
persistence; RAG-disabled fallback.

### 9.4 Coverage layout

| Tree | Covers |
| ---- | ------ |
| `tests/mqtt/` | topic build/parse, envelope validation (ranges/timezone/unknown fields), parser, subscriber (mocked MQTT) |
| `tests/simulator/` | state machine, physical invariants, config/env handling |
| `tests/intelligence/` | statistics, trends, baselines, rules, scoring, engine/context |
| `tests/services/` | idempotent ingestion (+ concurrent IntegrityError path), snapshot persistence, pagination |
| `tests/api/` | all Phase 1/2/3 endpoint contracts |
| `tests/agent/` | settings, provider factory, error classification, retry/fallback routing, determinism, grounding, full agent API |
| `tests/rag/` | chunking/scope/parser, stub adapters, retrieval select+rerank, service/repo round-trips, agent guidance tool, admin API contracts |
| `tests/api/test_auth.py` | register/login/refresh rotation/logout flows, token tampering, weak-password and role-escalation 422s, login parity 401s (Phase 6) |
| `tests/api/test_authorization.py` | IDOR matrix across vehicles/telemetry/health/agent: unauthenticated 401, non-owner 404, admin bypass, profile PATCH 422 (Phase 6) |
| `tests/core/test_security_settings.py` | JWT_SECRET requirements (missing/short/insecure), algorithm whitelist, expiry bounds (Phase 6) |

---

## 10. Security

- **Credentials**: keys live in `.env` (git-ignored) or real env vars; never in
  logs or responses; provider exceptions sanitized into the agent taxonomy.
- **LLM boundary**: the model only sees bounded serialized context via
  `VehicleContextTool`; it never touches the DB, SQL, or repositories.
- **RAG anti-prompt-injection**: retrieved documents are treated as **data,
  never instructions** (live-verified). Negative grounding prevents claiming
  documents that were never retrieved.
- **Dedup/safety rails**: test harness refuses hosted databases; subscriber
  never crashes on bad input; bounded retries prevent hot loops.
- **Phase 6 identity**:
  - Passwords hashed with bcrypt (default cost); refresh tokens stored only as
    SHA-256 hashes and rotated on every use; reuse-after-revocation revokes all
    of the user's tokens (theft detection).
  - Access JWTs are HMAC-signed with `JWT_SECRET` (min 32 chars enforced) and
    short-lived (`auth_access_token_minutes`, default 20); the user is re-read
    from the DB per request so `is_active`/`role` can't go stale.
  - Register never accepts `role`/`is_active` (422 on extra fields); login
    returns the same 401 for unknown email vs wrong password (no account
    probing); unauthenticated/non-owner access to vehicle data returns 404, so
    vehicle existence is never leaked.
  - `require_admin` gates `/api/v1/rag/health`; `/api/v1/rag/search` requires
    any authenticated user; health endpoints stay public.
- **RLS**: **not enabled** (documented posture). The backend connects with a
  privileged login; RLS should be revisited for a public-facing Data API /
  frontend with separate `authenticated`/`anon` roles.
- **CORS**: dev default `["http://localhost:3000"]`; adjust in deployment.
- **Authentication/JWT**: **IMPLEMENTED in Phase 6** (see above). Not included:
  fine-grained per-vehicle sharing, MFA, and account-recovery flows (FUTURE).

## 11. Performance & scaling

- **DB pool** (non-test): `pool_size=5, max_overflow=5, pool_timeout=30,
  pool_recycle=1800, pool_pre_ping=True` — deliberately small and bounded for
  managed providers; test env uses `NullPool`.
- **Indexes**: partial unique index for idempotency; composite indexes on
  snapshots/diagnoses; HNSW cosine index for `vector(1024)`; GIN for FTS.
- **Bounded work**: analysis windows bounded (1–1440 min) with a capped window
  load; baselines bounded; contexts capped at `llm_context_max_chars` (24 000);
  RAG evidence capped at `rag_evidence_max_chars` (1800) with final top-k 5;
  pagination capped at the API layer (100 vehicles / 500 telemetry).
- **RAG latency**: bge-m3 encodings are precomputed at ingestion; searches are
  index-accelerated; reranking limited to a shortlist (30).
- **Known ceiling**: the emedding/reranker models load into RAM/VRAM once per
  process; high concurrency would benefit from a separate, pre-warmed inference
  service (FUTURE). No sharding, no multi-tenant isolation, no TimescaleDB
  continuous aggregates.

## 12. Observability & error handling

- **Logging**: root handler formatted
  `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s` (JSON formatter =
  FUTURE); noisy third-party loggers quieted (`uvicorn.access`, `httpx`,
  `httpcore`).
- **Health**: `/api/v1/health` (liveness, no DB) and `/api/v1/health/db`
  (`SELECT 1`, 503 degraded); `/api/v1/rag/health` reports adapters,
  pgvector availability, and corpus counts. Docker images ship a curl
  HEALTHCHECK on `/api/v1/health`.
- **HTTP error contract** (wired in `main.py`):

| HTTP | Meaning |
| ---- | ------- |
| 404 | Resource not found (vehicles, telemetry, health, diagnoses) |
| 409 | Conflict (duplicate VIN) |
| 422 | Validation failed (structured errors) |
| 500 | Database error / agent misconfiguration / graph execution failure (details never leak) |
| 502 | LLM provider error (bad_request, auth, unavailable, provider, structured output invalid) |
| 503 | LLM rate limiting; also `/health/db` DB unreachable |
| 504 | LLM provider timeout |

- **MQTT**: malformed/unknown/duplicate → log-and-skip; transient DB errors →
  bounded retries. Duplicate REST/MQTT `source_event_id` → silent no-op.
- **RAG**: disabled/missing-pgvector → stable 503 detail on `/api/v1/rag/health`;
  empty query → 422; parser/model failures → typed `RAGError`s.

## 13. Troubleshooting

| Symptom | Likely cause / fix |
| ------- | ------------------ |
| App starts but `/health/db` degraded | `DATABASE_URL` unreachable; check network/TLS, `make db-check` |
| Subscriber crashes repeatedly on Windows | Two processes share an MQTT client id → session takeover. Leave `MQTT_CLIENT_ID` unset (per-process unique default) |
| Subscriber keeps reconnecting | Broker down; check `mosquitto` conf + credentials (`MQTT_USERNAME`/`MQTT_PASSWORD`, docker ACL) |
| Supabase connection times out | Prefer **direct** `db.<ref>.supabase.co:5432`; fall back to Session pooler only on IPv4-only networks; never Transaction mode (asyncpg needs `statement_cache_size=0`); append `?ssl=require` |
| `tests/rag/` integrations skip | Local DB lacks pgvector (`supports_pgvector()` probe). Install/`CREATE EXTENSION vector` or rely on `phase5_agent_rag_verify.py` against Supabase |
| Agent endpoints return 502/503/504 | Provider key missing/invalid, rate limited, or timeout; check `.env` keys + `LLM_*` settings; `RUN_LLM_SMOKE_TEST=true python -m scripts.smoke_agent_llm` |
| `RAGSearchUnavailable` / 503 on RAG | `RAG_ENABLED=false` or pgvector missing on target DB |
| Model download fails at first RAG use | Offline/repo restriction; pre-cache `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3` (verifier pins `HF_HUB_OFFLINE=1`) |
| `tests/conftest.py` refuses to start | `TEST_DATABASE_URL` points at a hosted DB (`supabase`/`pooler`) — point it at a dedicated local DB |
| `alembic current` ≠ `d6a9b1c2e3f4` | Not migrated; run `make migrate`; verify with `make db-heads`/`make db-history` |
| Login/refresh returns 401 after re-issuing a token | Refresh tokens are single-use by design — always persisted/rotated on the client; a reused revoked token revokes all sessions (theft detection) |
| Vehicle endpoints return 404 in Phase 6 | Not owned by the authenticated user (or unauthenticated) — 404 deliberately hides vehicle existence; admins bypass ownership |
| `JWT_SECRET` startup failure | Missing or <32 chars; generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| The health score says `unknown` | Fewer than `HEALTH_MINIMUM_SAMPLES` in the window — run the simulator longer or POST telemetry |

## 14. Known limitations & planned work

- **NOT IMPLEMENTED / FUTURE**: Phase 7 PDF report generation; Phase 8
  Next.js frontend; ML prediction / anomaly
  analytics; TimescaleDB continuous aggregates; status-message persistence;
  JSON log formatter; background schedulers for analysis; online RAG
  evaluation module (`app/rag/evaluation.py` was dropped); RLS policies.
- Vehicle sharing (multiple owners per vehicle) and soft delete are **not**
  implemented — ownership is single-user (`owner_user_id`).
- `TelemetryCreate`/MQTT ranges are static bounds, not per-vehicle model
  inference.
- The agent has no long-term memory beyond persisted diagnoses and effectively
  one RAG tool; no function/tool-calling loop over arbitrary APIs.
- REST API has no rate limiting (broker-level ACLs apply to MQTT only).
- The simulator is deterministic test/development tooling, not a production
  device emulator.

## 15. Phase status

| Phase | Scope | Status |
| ----- | ----- | ------ |
| 1  | Foundation: FastAPI + async SQLAlchemy + Alembic + vehicle/telemetry CRUD | COMPLETE |
| 2  | MQTT ingestion: broker, envelopes, subscriber, simulator, idempotency | COMPLETE |
| 3  | Vehicle Health Intelligence: deterministic engine + snapshots + API | COMPLETE |
| 3.5 | Supabase managed PostgreSQL via configuration (no code change) | COMPLETE |
| 4  | Agentic reasoning: LangGraph supervisor, LLM providers, grounding, persistence | COMPLETE |
| 5  | Manufacturer-documentation RAG: pgvector, hybrid retrieval, agent grounding | COMPLETE |
| 6  | Identity, roles & vehicle ownership: JWT + refresh rotation, bcrypt, IDOR protection | IMPLEMENTED (this guide reflects it) |
| 7  | (future phases / dashboard) | NOT STARTED |

## 16. Appendix

### 16.1 Full REST reference

| Method | Path | Notes |
| ------ | ---- | ----- |
| GET    | `/api/v1/health` | Liveness (no DB touch) |
| GET    | `/api/v1/health/db` | Database reachability (`SELECT 1`); `status:"degraded"` + 503 when down |
| POST   | `/api/v1/auth/register` | 201 `/api/v1/auth/*`; role/is_active forbidden (422); email case-normalized |
| POST   | `/api/v1/auth/login` | 200 tokens; identical 401 for bad email vs bad password |
| POST   | `/api/v1/auth/refresh` | Rotates refresh token (single-use); reuse → revoke all user tokens |
| POST   | `/api/v1/auth/logout` | 204; idempotent revoke |
| GET    | `/api/v1/auth/me` | Current user (401 guard) |
| GET    | `/api/v1/users/me` | User profile (auth required) |
| PATCH  | `/api/v1/users/me` | Update `full_name` only; other fields 422 |
| GET    | `/api/v1/vehicles` | Paginated; page_size ≤ 100 (default 20); owner-filtered (auth req.) |
| POST   | `/api/v1/vehicles` | 201; VIN 5–50 uppercased, year 1900–2100; 409 duplicate VIN; owner=caller |
| GET    | `/api/v1/vehicles/{id}` | 404 when missing/unowned |
| PATCH  | `/api/v1/vehicles/{id}` | Update mutable metadata; `vin`/`owner_user_id`/`status` 422; owner/admin only |
| DELETE | `/api/v1/vehicles/{id}` | Cascade delete telemetry/snapshots/diagnoses; owner/admin only (204) |
| GET    | `/api/v1/vehicles/{id}/telemetry` | Paginated ≤ 500 (default 50), time filters; owner/admin |
| POST   | `/api/v1/vehicles/{id}/telemetry` | 201; idempotent via `source_event_id`; `extra="forbid"`; owner/admin |
| POST   | `/api/v1/vehicles/{id}/health/analyze` | 200; `window_minutes` 1–1440; persists snapshot; owner/admin |
| GET    | `/api/v1/vehicles/{id}/health` | Latest snapshot; 404 if none/unowned |
| GET    | `/api/v1/vehicles/{id}/health/history` | Paginated, newest first; owner/admin |
| POST   | `/api/v1/vehicles/{id}/agent/query` | LLM diagnosis; query 1–2000 chars stripped; owner/admin |
| POST   | `/api/v1/vehicles/{id}/agent/events/critical` | Diagnose critical event; cooldown dedup; rule_ids ≤ 100; owner/admin |
| GET    | `/api/v1/vehicles/{id}/agent/dashboard` | Health context + latest diagnosis; **no LLM**; owner/admin |
| GET    | `/api/v1/vehicles/{id}/agent/diagnoses` | Paginated history; owner/admin |
| GET    | `/api/v1/vehicles/{id}/agent/diagnoses/latest` | Latest; 404 when none; owner/admin |
| GET    | `/api/v1/rag/health` | Adapters, pgvector, corpus counts; 503 when disabled; **admin only** (403) |
| GET    | `/api/v1/rag/search` | Query + optional `VehicleScope`; evidence + rerank scores; empty query → 422; any authenticated user |

Swagger `/docs`, ReDoc `/redoc`, OpenAPI `/openapi.json`. Non-public endpoints
demand `Authorization: Bearer <access_token>`; non-admin callers see 404 (not
403) for vehicles they don't own.

### 16.2 MQTT envelope formats

Telemetry (`vehicles/{id}/telemetry`):

```json
{
  "schema_version": 1,
  "event_id": "a1b2c3d4e5f60718",
  "vehicle_id": "11111111-2222-4333-8444-555555555555",
  "timestamp": "2026-09-20T10:00:00.123456+00:00",
  "telemetry": {
    "rpm": 2145.3, "speed": 61.2, "engine_load": 34.0,
    "coolant_temperature": 91.2, "oil_temperature": 88.1,
    "battery_voltage": 13.94, "fuel_level": 74.96,
    "intake_air_temperature": 33.4, "throttle_position": 19.1,
    "engine_runtime": 1820.5, "odometer": 45232.1
  }
}
```

- QoS 1, `retain=false`. `event_id` must be unique per vehicle (⇒
  `source_event_id`). `timestamp` must be tz-aware. Unknown fields or
  out-of-range metrics ⇒ discard + log.

Status (`vehicles/{id}/status`):

```json
{ "vehicle_id": "11111111-2222-4333-8444-555555555555", "status": "online",
  "timestamp": "2026-09-20T10:00:00+00:00" }
```

`online` at start, `offline` on graceful shutdown; informational, **not
persisted**.

### 16.3 Verify baseline (what "all green" means)

1. `make test` → **349 collected: 342 passed / 7 skipped** (pgvector-gated, covered
   live) / 0 deselected, exit 0.
2. `make lint` + `ruff format --check .` → clean.
3. `make db-current` on Supabase → `d6a9b1c2e3f4 (head)`; corpus clean
   (0/0/0 docs/versions/chunks) after verification cleanup.
4. `/openapi.json` route inventory matches §16.1.
5. Live Phase 5 verifier (`phase5_agent_rag_verify.py`) → all guardrail checks
   PASS (idempotent ingestion, scope isolation, negative grounding, injection
   defense, citation integrity, rag_* persistence, RAG-disabled fallback).

*End of guide.*