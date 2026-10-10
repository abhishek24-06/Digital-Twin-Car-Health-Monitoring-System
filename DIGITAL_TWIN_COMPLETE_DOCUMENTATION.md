# Digital Twin — Car Health Monitoring Platform

## Complete Technical Documentation of the Current Implementation

> **Document scope:** This document describes the **actual, current implementation** found in this repository — verified against source code, tests, migrations, configuration, and the **live OpenAPI document** generated from the running application code. Features that are not implemented are explicitly labelled as *not implemented* or *future work*. Nothing in this document is inferred from an old roadmap.

| Item | Value |
|---|---|
| Repository | `C:\Users\Abhishek\Desktop\Digital Twin` |
| Branch | `main` (HEAD `3c630c2` — *Added Simulation in UI*, plus the uncommitted Workflow Monitor feature) |
| Backend | Python ≥3.12 (this environment runs 3.14) · FastAPI · SQLAlchemy 2 async · PostgreSQL (Supabase/local) · pgvector · MQTT · LangGraph |
| Frontend | Next.js 16 (App Router) · React 19 · TypeScript 5 · Tailwind v4 · TanStack Query · Zustand |
| Verification date | 2026-10-08 (live test runs, live OpenAPI dump, file-path audit) |

---

## Table of Contents

1. [Repository Audit & Implemented Stack](#1--repository-audit--implemented-stack)
2. [Architecture](#2--architecture)
3. [Project Directory Structure](#3--project-directory-structure)
4. [Important Files — Backend](#4--important-files--backend)
5. [Important Files — Frontend, Scripts, Config](#5--important-files--frontend-scripts-config)
6. [Database](#6--database)
7. [Telemetry Pipeline](#7--telemetry-pipeline)
8. [Vehicle Simulator](#8--vehicle-simulator)
9. [MQTT](#9--mqtt)
10. [Health Intelligence](#10--health-intelligence)
11. [RAG / Manufacturer Guidance](#11--rag--manufacturer-guidance)
12. [Document Ingestion Workflow (Observability)](#12--document-ingestion-workflow--observability)
13. [RAG Query Workflow](#13--rag-query-workflow)
14. [LangGraph Agent](#14--langgraph-agent)
15. [LLM Providers](#15--llm-providers)
16. [Authentication](#16--authentication)
17. [Frontend](#17--frontend)
18. [Simulation Control](#18--simulation-control)
19. [Workflow Monitor / Live Observability](#19--workflow-monitor--live-observability)
20. [API Reference](#20--api-reference)
21. [Environment Variables](#21--environment-variables)
22. [Installation (Windows PowerShell)](#22--installation-windows-powershell)
23. [Database Setup](#23--database-setup)
24. [Mosquitto Setup](#24--mosquitto-setup)
25. [Running the System](#25--running-the-system)
26. [How to Use the System](#26--how-to-use-the-system)
27. [Faculty Demonstration Script](#27--faculty-demonstration-script)
28. [Testing](#28--testing)
29. [Troubleshooting](#29--troubleshooting)
30. [Security](#30--security)
31. [Limitations](#31--limitations)
32. [Future Enhancements](#32--future-enhancements)
33. [Final Validation Report](#33--final-validation-report)

---

# 1 — Repository Audit & Implemented Stack

## 1.1 Repository audit (git state at documentation time)

```
main branch, HEAD 3c630c2

Modified (M):    backend/.env.example, backend/app/agent/nodes.py,
                 backend/app/api/router.py, backend/app/api/routes/simulation.py,
                 backend/app/core/config.py, backend/app/mqtt/subscriber.py,
                 backend/app/rag/ingestion.py, backend/app/rag/rag_service.py,
                 backend/app/services/health_monitor.py,
                 backend/app/services/simulation_manager.py,
                 frontend/src/components/layout/nav-items.tsx,
                 frontend/src/types/api.ts, tasks/plan.md, tasks/todo.md

Untracked (??):  backend/app/api/routes/workflow.py
                 backend/app/schemas/workflow.py
                 backend/app/services/workflow_event_bus.py
                 backend/tests/services/test_workflow_event_bus.py
                 frontend/src/app/(app)/workflow/
                 frontend/src/app/api/workflow/
                 frontend/src/components/workflow/
                 frontend/src/hooks/use-workflow.ts
                 frontend/src/services/workflow.ts
```

**Status of the Workflow Monitor feature:** the feature is **implemented in the working tree** (backend routes, event bus, instrumented pipelines, frontend page/components/hooks/SSE proxy, plus a passing event-bus test suite) but is **not yet committed to git**. This document documents it as implemented code.

## 1.2 Verified technology stack

### Backend (`backend/pyproject.toml` — package `digital-twin-api`, version `0.1.0`, Python `>=3.12`)

**Runtime dependencies (as declared):**

| Package | Constraint | Purpose |
|---|---|---|
| `fastapi` | `>=0.115.0` | HTTP API framework |
| `uvicorn[standard]` | `>=0.32.0` | ASGI server |
| `sqlalchemy[asyncio]` | `>=2.0.36` | Async ORM (SQLAlchemy 2.0 style) |
| `asyncpg` | `>=0.30.0` | PostgreSQL async driver |
| `alembic` | `>=1.14.0` | Schema migrations |
| `pydantic` | `>=2.9.0` | Validation / schemas |
| `pydantic-settings` | `>=2.6.0` | Env-driven settings |
| `email-validator` | `>=2.2.0` | `EmailStr` support |
| `aiomqtt` | `>=2.2.0` | Async MQTT client (paho-based) |
| `langchain-core` / `langchain-openai` | `>=0.3.0` / `>=0.2.0` | LLM chat model abstractions |
| `langgraph` | `>=0.2.0` | Agent graph runtime |
| `bcrypt` | `>=4.0.0` | Password hashing |
| `PyJWT` | `>=2.8.0` | JWT encode/decode |
| `python-multipart` | `>=0.0.9` | Multipart uploads (RAG documents) |
| `pgvector` | `>=0.3.6` | pgvector column types |
| `numpy` | `>=1.26.0` | Required at import time by `app/models/rag.py` |

**Extras:**
- `dev`: `pytest>=8.3.0`, `pytest-asyncio>=0.24.0`, `httpx>=0.27.0`, `ruff>=0.7.0`
- `rag` (heavy, optional at install time): `docling>=2.0.0`, `sentence-transformers>=3.0.0`, `torch>=2.2.0`, `transformers>=4.40.0`, `scipy>=1.11.0`

**Tooling configuration (from `pyproject.toml`):**
- pytest: `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `addopts = "-q -m 'not mqtt_e2e'"`, marker `mqtt_e2e` (broker-required tests, run via `make mqtt-test`).
- ruff: `target-version = "py312"`, `line-length = 100`, lint rules `E,F,W,I,UP,B,YTT` (ignoring `E501`), format double quotes / space indent; `alembic/versions` excluded.

### Frontend (`frontend/package.json` — `digital-twin-frontend`, version `1.0.0`)

| Package | Version | Purpose |
|---|---|---|
| `next` | `^16.3.7` | App Router framework |
| `react` / `react-dom` | `^19.3.0` | UI library |
| `typescript` | `^5.9.3` | Type system |
| `@tanstack/react-query` | `^5.104.0` | Server-state cache |
| `zustand` | `^5.0.8` | Client UI state (session, selected vehicle) |
| `tailwindcss` + `@tailwindcss/postcss` | `^4.3.3` | CSS-first styling (no `tailwind.config` file) |
| `tw-animate-css` | `^1.4.0` | Keyframe utilities |
| Radix primitives (`react-dialog`, `react-dropdown-menu`, `react-label`, `react-slot`, `react-tabs`, `react-tooltip`) | `^1.1.x / ^2.1.x` | Accessible unstyled components |
| `class-variance-authority`, `clsx`, `tailwind-merge` | `^0.7.1`, `^2.1.1`, `^3.3.1` | `cn()` + variant styling (shadcn pattern, hand-written) |
| `lucide-react` | `^0.545.0` | Icons |
| `recharts` | `^3.10.1` | Telemetry charts |
| `vitest` (+ `jsdom`, Testing Library) | `^4.0.9` (dev) | Component/unit testing |

**Scripts:** `dev` = `next dev`, `build` = `next build`, `lint` = `eslint .`, `typecheck` = `tsc --noEmit`, `test` = `vitest run`.

### Data / messaging / infrastructure

- **PostgreSQL 16 + pgvector** — image `pgvector/pgvector:pg16` in `backend/docker-compose.yml`; production target may be **Supabase** (pooled, TLS) via `DATABASE_URL`.
- **MQTT broker** — Mosquitto 2 (`eclipse-mosquitto:2` in Docker; local Windows install for development).
- **Vector search** — pgvector HNSW (`vector_cosine_ops`) + PostgreSQL full-text `TSVECTOR` with GIN index (hybrid retrieval).
- **Embeddings / reranking** — local `sentence-transformers` models: `BAAI/bge-m3` (1024-dim) and `BAAI/bge-reranker-v2-m3`.
- **Document parsing** — Docling (14 binary formats) + a built-in plain-text/Markdown parser.
- **LLM** — OpenRouter (primary) → Groq (fallback) → deterministic `mock` provider.
- **CI** — GitHub Actions (`.github/workflows/ci.yml`): backend job (ruff, format check, migrations, pgvector verify, pytest against a `pgvector/pgvector:pg16` service) and frontend job (Node 24: `npm ci`, typecheck, lint, vitest).

### Verification evidence (run on 2026-10-08)

| Check | Command | Result |
|---|---|---|
| Backend tests | `python -m pytest --tb=no` | **1 failed, 541 passed, 10 skipped, 4 deselected** (5 m 45 s) — the single failure is a pre-existing expectation mismatch documented in [§28](#28--testing) |
| Backend lint | `python -m ruff check .` | **All checks passed!** |
| Frontend tests | `npm test` (vitest run) | **92 passed (12 files)**, 5.5 s |
| Frontend typecheck | `npm run typecheck` | **No errors** |
| Frontend lint | `npm run lint` (eslint) | **No errors** |
| Live OpenAPI | `app.openapi()` from `app.main.app` | **31 paths / 40 operations** (listed in [§20](#20--api-reference)) |

---

# 2 — Architecture

## 2.1 Overall architecture

```mermaid
flowchart TB
    subgraph Browser["Browser (Next.js frontend)"]
        UI["React 19 screens<br/>Dashboard · Vehicles · Simulation<br/>Guidance · Workflow Monitor"]
        QL["TanStack Query cache"]
        SSE1["EventSource (SSE)"]
    end

    subgraph Web["Next.js server (port 3000)"]
        PROXY["Route handlers:<br/>/api/session/* · SSE proxies"]
    end

    subgraph API["FastAPI backend (port 8000)"]
        R["API routes /api/v1/*"]
        SVC["Services:<br/>auth · vehicle · telemetry · health<br/>simulation manager · subscriber supervisor"]
        WB["WorkflowEventBus<br/>(in-memory ring buffer 500)"]
        MON["Background health monitor task"]
    end

    subgraph Data["Data layer"]
        PG[("PostgreSQL / Supabase<br/>+ pgvector")]
    end

    subgraph Ingest["Telemetry ingest path"]
        SIM["Vehicle simulator<br/>(child process)"]
        MOSQ["Mosquitto :1883"]
        SUB["MQTT subscriber<br/>(supervised child process)"]
    end

    subgraph Doc["RAG path"]
        DOCS[("Manufacturer documents<br/>data/documents")]
        EMB["BGE-M3 embeddings<br/>+ BGE reranker"]
    end

    subgraph LLM["LLM providers"]
        OR["OpenRouter"]
        GQ["Groq"]
        MOCK["mock (offline)"]
    end

    UI --> QL
    QL --> R
    UI --> SSE1 --> PROXY
    PROXY -->|"Bearer from httpOnly cookie"| R
    R --> SVC
    SVC --> PG
    MON --> PG
    SVC --> WB
    WB -->|"SSE"| PROXY
    SIM --> MOSQ --> SUB --> SVC
    DOCS --> EMB --> PG
    R --> PG
    SVC -->|"AgentService"| OR
    SVC -.->|fallback| GQ
    SVC -.->|"dev/test"| MOCK
```

**Core flow:** `Frontend → FastAPI → Services → PostgreSQL/Supabase`.

**Telemetry flow:** `Simulator → MQTT → Mosquitto → MQTT Subscriber → Telemetry Persistence → Health Intelligence → Health Snapshots → Frontend`.

**RAG flow:** `Manufacturer Documents → Parsing → Chunking → Embeddings → pgvector → Retrieval → Reranking → (verbatim guidance / Agent) → Answer + Sources`.

## 2.2 Telemetry architecture

```mermaid
sequenceDiagram
    participant Sim as Simulator process
    participant Mos as Mosquitto
    participant Sub as MQTT subscriber
    participant Tsp as TelemetryService
    participant DB as PostgreSQL
    participant HM as Health monitor
    participant FE as Frontend

    Sim->>Sim: driving-state machine, seed RNG
    Sim->>Mos: PUBLISH vehicles/{id}/telemetry (QoS 1)
    Mos-->>Sub: deliver (subscribe vehicles/+/telemetry)
    Sub->>Sub: parse + validate envelope (schema v1)
    Sub->>Tsp: create_telemetry(vehicle_id, TelemetryCreate)
    Tsp->>DB: INSERT telemetry_records (idempotent by source_event_id)
    Sub-->>Sub: publish TELEMETRY_PERSISTED workflow event
    HM->>DB: query vehicles with newer telemetry than last snapshot
    HM->>HM: window analysis → score → confidence → status
    HM->>DB: INSERT vehicle_health_snapshots (immutable)
    FE->>DB: GET /telemetry, GET /health (via API)
    FE->>FE: SSE live stream (proxied) renders new samples
```

## 2.3 RAG architecture

```mermaid
flowchart LR
    subgraph Ingest["Ingestion (admin upload)"]
        F["File (17 extensions)"] --> P["Parser<br/>plain-text · Docling"]
        P --> H["SHA-256 content hash<br/>version resolution"]
        H --> C["Structure-aware chunking<br/>size 800 / overlap 120"]
        C --> E1["BGE-M3 embeddings<br/>1024-dim, L2 normalized"]
        E1 --> V[("pgvector<br/>rag_chunks.embedding_store<br/>HNSW + tsvector GIN")]
    end
    subgraph Query["Query (search / agent guidance)"]
        Q["User question<br/>(VIN stripped, ≤500 chars)"] --> E2["BGE-M3 query embedding"]
        E2 --> HY["Hybrid search: cosine dense + ts_rank_cd lexical<br/>α = 0.6, scope filter (make/model/year), top 30"]
        HY --> RR["BGE-reranker-v2-m3 cross-encoder<br/>score ≥ 0.2 → top 5"]
        RR --> CTX["Citations + verbatim guidance<br/>(1 800 chars per chunk)"]
        CTX --> AG["Agent / API response"]
    end
    V --> HY
```

## 2.4 Health intelligence architecture

```mermaid
flowchart TB
    W["Telemetry window<br/>15 min (default), limit computed"] --> DQ["Data quality<br/>coverage · sample count · duration"]
    DQ --> ST["Statistics<br/>mean/median/std/percentiles/CV"]
    DQ --> TR["Trends<br/>OLS slope → increasing/decreasing/stable"]
    DQ --> BL["Baselines<br/>6 h history, median + 1.4826·MAD, ±2σ bands"]
    ST --> RU["Rule engine<br/>13 rules (temperature, electrical, engine, fuel, data quality)"]
    RU --> SC["Scoring<br/>100 − penalties (info 0 / warning 10 / critical 30)<br/>cap 40 per category"]
    SC --> CF["Confidence<br/>0.10 + 0.90·(0.30·coverage + 0.25·duration + 0.25·samples + 0.20·completeness)"]
    SC --> SN["Health status<br/>≥80 healthy · ≥60 attention · else critical"]
    DQ --> SU{Samples?}
    SU -->|"0"| ND["no_data (score None)"]
    SU -->|"< 10"| LD["limited_data + provisional flag"]
    SU -->|"≥ 10"| SN
    SN --> HP["Immutable HealthSnapshot row (JSONB context)"]
    ND --> HP
    LD --> HP
    HP -->|"status = critical"| AGT["Agent critical-event escalation<br/>(5 min cooldown)"]
```

## 2.5 Agent / LangGraph architecture

```mermaid
flowchart LR
    IN["User query / critical event"] --> SUP["supervisor node<br/>loads Vehicle Health Context<br/>decides needs_rag / needs_llm"]
    SUP -->|needs_rag| RAG["rag node<br/>Manufacturer Guidance Tool<br/>(read-only retrieval)"]
    SUP -->|needs_llm only| REASON
    SUP -->|neither| VAL2["validate<br/>(canned grounded reasoning)"]
    RAG --> REASON["reason node<br/>builds prompt, calls LLMService<br/>structured JSON output"]
    REASON --> VAL["validate node<br/>ground evidence, clamp severity/confidence,<br/>verify citations"]
    VAL --> PER["persist node<br/>agent_diagnoses row"]
    VAL2 --> PER --> END["DiagnosisResponse"]
```

`LLMService` retry/fallback is shown in [§15](#15--llm-providers).

## 2.6 Authentication architecture

```mermaid
flowchart LR
    subgraph FE["Frontend"]
        FORM["Login/Register form"] --> NX["/api/session/login (Next route handler)"]
        NX -->|"stores httpOnly cookies"| CK["dt_at (access, 12 h)<br/>dt_rt (refresh, 30 d, path /api/session)"]
        CL["api-client.ts<br/>(in-memory access token)"] -->|"Authorization: Bearer"| API
        ES["EventSource"] -->|"cookie-based"| PX["/api/.../stream proxies"]
    end
    subgraph BE["FastAPI"]
        API["Routes"] --> AUTH["get_current_user<br/>JWT decode + DB re-read"]
        AUTH --> OWN["ensure_vehicle_access<br/>(404 for non-owners)"]
        NX2["/auth/* endpoints"] --> SVC2["AuthService<br/>bcrypt · rotation · reuse detection"]
    end
    PX --> AUTH
    NX --> API
    SVC2 --> DB2[("users / refresh_tokens<br/>(SHA-256 hashes only)")]
    OWN --> DB2
```

## 2.7 Frontend / backend split

```mermaid
flowchart TB
    subgraph Browser["Browser"]
        P1["Data requests (vehicles, telemetry, health, RAG, agent, workflow-recent)"]
        P2["Session lifecycle (login, refresh, logout, session probe)"]
        P3["SSE streams (telemetry, workflow events)"]
    end
    subgraph Next["Next.js route handlers"]
        DIRECT["Direct fetch to NEXT_PUBLIC_API_URL<br/>with in-memory Bearer token"]
        SES["/api/session/*  (server-side, httpOnly cookies)"]
        SX["/api/vehicles/{id}/telemetry/stream<br/>/api/workflow/events/stream"]
    end
    FAPI["FastAPI /api/v1"]
    P1 --> DIRECT --> FAPI
    P2 --> SES -->|"forward + set cookies"| FAPI
    P3 --> SX -->|"attach Bearer from dt_at cookie"| FAPI
```

Only three concerns route through the Next.js server: **session lifecycle** (so the refresh cookie never reaches JavaScript) and the **two SSE streams** (because `EventSource` cannot send headers). Everything else talks to FastAPI directly with `fetch`.

## 2.8 Runtime process architecture

```mermaid
flowchart TB
    subgraph Host["Windows development host"]
        UV["uvicorn app.main:app :8000<br/>(process 1)"]
        ND["next dev :3000<br/>(process 2)"]
        MO["mosquitto :1883<br/>(process 3 — local.conf, anonymous)"]
        UV ---|lifespan| HM2["asyncio task: health-monitor"]
        UV ---|lifespan| SS["SubscriberSupervisor<br/>spawns → app.mqtt.subscriber child process<br/>auto-restart, backoff 1→16 s, PID marker"]
        UV ---|lifespan| SM["SimulationManager<br/>spawns → simulator.main child process per vehicle<br/>PID marker + log file + orphan cleanup"]
        SS --> MO
        SM --> MO
    end
```

FastAPI owns supervision: on startup it starts the health-monitor task, calls `simulation_manager.cleanup_stale()`, and calls `subscriber_supervisor.ensure_running()`; on shutdown it shuts down subscriber, simulations, monitor, and the DB engine (see `app/main.py` lifespan).

---

# 3 — Project Directory Structure

Source, configuration, tests, migrations and scripts only (generated/cache folders such as `.venv`, `node_modules`, `.next`, `__pycache__`, `.ruff_cache`, `.pytest_cache`, `.git` are omitted):

```
Digital Twin/
├── backend/
│   ├── alembic/
│   │   ├── env.py                    # URL injected from app settings, target metadata
│   │   ├── script.py.mako
│   │   └── versions/                 # 8 migrations (head b7d9f1e2a3c4)
│   ├── app/
│   │   ├── main.py                   # FastAPI app + lifespan + CORS + exception handlers
│   │   ├── agent/                    # LangGraph agent (graph, nodes, providers, tools)
│   │   │   ├── providers/            # openrouter / groq / mock
│   │   │   └── tools/                # vehicle_context, manufacturer_guidance
│   │   ├── api/
│   │   │   ├── router.py             # aggregates all routes under /api/v1
│   │   │   └── routes/               # auth, health, users, vehicles, telemetry,
│   │   │                             # vehicle_health, simulation, agent, rag,
│   │   │                             # admin_rag, workflow
│   │   ├── core/                     # config, database, db_target, exceptions,
│   │   │                             # logging, rate_limit, security
│   │   ├── dependencies/             # get_db + auth dependencies
│   │   ├── intelligence/             # deterministic health engine (engine, rules,
│   │   │                             # scoring, statistics, trends, baselines, models)
│   │   ├── models/                   # ORM: user, refresh_token, vehicle, telemetry,
│   │   │                             # health_snapshot, rag, agent_diagnosis, base
│   │   ├── mqtt/                     # client, publisher, subscriber, parser, topics
│   │   ├── rag/                      # ingestion, chunking, embeddings, retrieval,
│   │   │   ├── parser/               # repository, query_builder, rag_service…
│   │   │   └── reranker/             # plain-text + Docling parsers, CrossEncoder reranker
│   │   ├── repositories/             # vehicle, user, telemetry, refresh_token,
│   │   │                             # health_snapshot, agent_diagnosis
│   │   ├── schemas/                  # auth, user, vehicle, telemetry, health,
│   │   │                             # vehicle_health, simulation, rag, agent, workflow
│   │   └── services/                 # auth, vehicle, telemetry, vehicle_access,
│   │                                 # vehicle_health, health_monitor, simulation_manager,
│   │                                 # subscriber_manager, workflow_event_bus
│   ├── simulator/                    # main, config, vehicle, telemetry_generator, publisher
│   ├── scripts/                      # seed_demo_vehicle, ingest_documents, query_rag,
│   │                                 # verify_pgvector, reset_local_db, check_db, …
│   ├── infrastructure/mosquitto/     # mosquitto.conf, mosquitto.local.conf, mosquitto.acl
│   ├── docs/                         # historical complete system guide (superseded)
│   ├── tests/                        # 51 test files: api, services, rag, mqtt, agent,
│   │                                 # intelligence, repositories, core, simulator
│   ├── .env.example                  # every backend variable documented
│   ├── alembic.ini
│   ├── docker-compose.yml            # postgres, backend, mosquitto, mqtt-subscriber, simulator
│   ├── Dockerfile
│   ├── Makefile                      # 25 phony targets (+ .venv helper)
│   ├── openapi.json                  # static snapshot (stale — see §20)
│   ├── pyproject.toml
│   └── README.md                     # historical backend guide
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── (auth)/login, register/
│   │   │   ├── (app)/dashboard, vehicles, vehicles/[id]/{health,telemetry,diagnosis,history},
│   │   │   │        simulations, workflow, rag, admin/rag, profile/
│   │   │   ├── api/session/*         # session proxy routes
│   │   │   ├── api/vehicles/[id]/telemetry/stream/   # telemetry SSE proxy
│   │   │   ├── api/workflow/events/stream/           # workflow SSE proxy
│   │   │   ├── globals.css           # Tailwind v4 @theme tokens
│   │   │   ├── layout.tsx, page.tsx, error.tsx, not-found.tsx
│   │   ├── components/               # layout, auth, dashboard, vehicles, simulations,
│   │   │                             # profile, rag, admin, workflow, health, diagnosis,
│   │   │                             # states, telemetry, ui (10 primitives)
│   │   ├── hooks/                    # use-auth, use-vehicle-data, use-telemetry-stream,
│   │   │                             # use-simulations, use-workflow, mutations, …
│   │   ├── lib/                      # api-client, api-error, session-server, session-store,
│   │   │                             # query-keys, metrics, format, telemetry-stream, utils
│   │   ├── services/                 # auth, vehicles, simulations, rag, workflow
│   │   ├── stores/                   # providers, query-provider, theme, vehicle-selection
│   │   ├── types/api.ts              # backend contract (831 lines)
│   │   └── test/utils.tsx            # renderWithProviders
│   ├── .env.example                  # BACKEND_API_URL, NEXT_PUBLIC_API_URL
│   ├── eslint.config.mjs, tsconfig.json, next.config.ts,
│   ├── postcss.config.mjs, vitest.config.mts, vitest.setup.ts
│   └── package.json / package-lock.json
├── scripts/
│   ├── dt-start.ps1                  # start mosquitto + api + subscriber (tracked, hidden)
│   ├── dt-stop.ps1                   # stop tracked processes
│   └── dt-status.ps1                 # status + port probes + health probe
├── data/                             # data/documents — local document roots for RAG
├── tasks/plan.md, todo.md            # Workflow Monitor implementation plan & checklist
├── .github/workflows/ci.yml          # backend + frontend CI
├── DIGITAL_TWIN_CURRENT_SYSTEM_GUIDE.md
├── P0_SIMULATION_CONTROL_FINAL_REPORT.md
├── opencode.json, setup-opencode-digital-twin.ps1, skills-lock.json, package-lock.json
```

**Counts measured at documentation time:** 129 Python source files under `backend/app` + `backend/simulator` (excluding `__pycache__`), 117 TypeScript/TypeScript-React files under `frontend/src`, 12 frontend test files, 51 backend test files.

---

# 4 — Important Files — Backend

> Each entry answers: path · purpose · key symbols · who calls it · what it calls · role.

## 4.1 Application entry

### `backend/app/main.py`
- **Purpose:** application bootstrap and lifecycle.
- **Key symbols:** `lifespan(app)`, `_start_health_monitor()`, `app = FastAPI(...)`, `root()` (`GET /`, hidden from schema).
- **Lifespan startup:** `configure_logging` → `init_engine(settings)` → `check_database_connection()` (warn-only) → start background `health-monitor` task (if `health_monitor_enabled`) → `simulation_manager.cleanup_stale()` (kills orphan simulators) → `subscriber_supervisor.ensure_running()` (starts MQTT subscriber; warns if not running).
- **Lifespan shutdown:** subscriber shutdown → simulation shutdown → cancel monitor → `dispose_engine()`.
- **Middleware:** exactly one — `CORSMiddleware` (`allow_origins=settings.cors_origins`, credentials, all methods/headers).
- **Exception handlers:** maps every domain error to HTTP (full table in [§29.3](#293-http-error-mapping-evidence)) — 404/409/401/403/429/502/503/504/500/422/413/400, plus a catch-all 500 and a sanitized `RequestValidationError` (422).
- **Role:** single composition root; everything else is imported through it.

## 4.2 Core module (`app/core/`)

| File | Purpose & key symbols | Called by / calls |
|---|---|---|
| `config.py` | `Settings(BaseSettings)` (env + `.env`, case-insensitive, `extra="ignore"`), `get_settings()` (`lru_cache`). Holds app, database, CORS, MQTT, health, monitor, auth/JWT, rate-limit, stream, simulation, workflow settings. Validators enforce simulation bounds, **JWT secret ≥32 chars outside dev/local (with denylist)**, monitor/rate-limit/stream/workflow ranges. `sync_database_url` property. | Read everywhere; `.env` via pydantic-settings |
| `database.py` | `init_engine` (test → `NullPool`; else pool 5/5, pre-ping, recycle 1800), `get_engine`, `get_session_factory`, `dispose_engine`, `check_database_connection` (`SELECT 1`, never raises) | lifespan, `get_db`, health monitor, alembic indirectly |
| `db_target.py` | `classify_database_url` → `supabase\|local\|remote`, `describe_database_url` (credentials redacted), `require_local_database` guard | scripts (`reset_local_db`), startup warnings |
| `exceptions.py` | `AppError` base → `NotFoundError` 404, `ConflictError` 409, `DatabaseError` 500, `AuthenticationError` 401, `AuthorizationError` 403, `RateLimitError` 429 (+`retry_after_seconds`), `SimulationError` 502 | raised by services/repos; mapped in `main.py` |
| `logging.py` | `configure_logging(debug)` — idempotent stdout handler, `asctime | level | name | message`, quiets uvicorn/httpx | lifespan |
| `rate_limit.py` | `RateLimiter` (thread-safe sliding window), `RateLimitDependency(scope)`, `client_host()` (leftmost `X-Forwarded-For`) | auth routes: scopes `auth:login`, `auth:register`, `auth:refresh` |
| `security.py` | `hash_password`/`verify_password` (bcrypt, `BCRYPT_MAX_PASSWORD_BYTES = 72`), `create_access_token` (claims `sub/type/iat/exp`, HS256), `generate_refresh_token_value` (`secrets.token_urlsafe(48)`), `hash_refresh_token_value` (SHA-256 hex), `decode_access_token` | `AuthService`, auth dependencies |

## 4.3 API layer

### `backend/app/api/router.py`
Aggregates every route module into `api_router` (mounted with `prefix=/api/v1`): `/health`, `/auth`, users (full paths), `/vehicles`, `/vehicles/{id}/telemetry`, `/vehicles/{id}/health`, `/vehicles/{id}/agent`, `/vehicles/{id}/simulation`, `/simulations`, `/rag`, `/admin`, and `workflow.router` (declares its own `/workflow` prefix).

### Route files (`backend/app/api/routes/`)
Thin handlers: schema validation → dependency → service → response. Full endpoint inventory in [§20](#20--api-reference). Files: `auth.py`, `health.py`, `users.py`, `vehicles.py`, `telemetry.py`, `vehicle_health.py`, `simulation.py` (also derives `degraded` state — see §18), `agent.py`, `rag.py`, `admin_rag.py`, `workflow.py`.

### `backend/app/dependencies/`
- `database.py` — `get_db()` yields an `AsyncSession`; factories composing session → repository → service (`get_vehicle_service`, `get_telemetry_service`, `get_agent_service`, `get_rag_service` (lazy), `get_admin_rag_service`, `get_auth_service`, …).
- `auth.py` — `get_current_user` (HTTPBearer, `type == "access"`, loads user from DB per request so role/active are never stale), `require_admin` (403 unless `role == "admin"`).

## 4.4 Models (`app/models/`) — see §6 for full schema

| File | Table | Role |
|---|---|---|
| `base.py` | — | `Base(DeclarativeBase)`, `UUIDPrimaryKeyMixin`, `TimestampMixin` |
| `user.py` | `users` | accounts, roles (`user`/`admin` check constraint) |
| `refresh_token.py` | `refresh_tokens` | SHA-256 hashes only, expiry, revocation |
| `vehicle.py` | `vehicles` | owned vehicles, `owner_user_id` FK (SET NULL), source/status checks |
| `telemetry.py` | `telemetry_records` | 11 metric columns + `raw_payload` JSONB + `source_event_id` dedupe |
| `health_snapshot.py` | `vehicle_health_snapshots` | immutable analysis results (`context_json` JSONB) |
| `rag.py` | `rag_documents`, `rag_document_versions`, `rag_chunks` | versioned corpus; `vector(1024)` + `TSVECTOR` columns |
| `agent_diagnosis.py` | `agent_diagnoses` | diagnosis JSONB + provider/model/fallback/latency/tokens + RAG provenance |

`app/models/__init__.py` imports all concrete models at import time (`_ensure_registered`) so Alembic and tests see every table.

## 4.5 Repositories (`app/repositories/`)

All SQL lives here (SQLAlchemy 2.0 `select`); integrity errors become `ConflictError`.

| File | Key operations |
|---|---|
| `vehicle_repository.py` | `get_by_id`, `get_by_id_and_owner`, `get_by_vin`, `list`/`list_by_owner` (paged, newest first), `create`/`update` (VIN conflict → 409), `delete` |
| `user_repository.py` | `get_by_id`, `get_by_email`, `create` (email conflict) |
| `telemetry_repository.py` | `create`, `get_by_source_event` (idempotency), `list_by_vehicle` (paged, time-filtered), `get_recent_telemetry` (window, oldest-first), `list_since` (exclusive cursor for SSE), `get_latest_timestamps` |
| `refresh_token_repository.py` | `create`, `get_by_hash`, `revoke`, `revoke_all_for_user` |
| `health_snapshot_repository.py` | `create`, `get_latest_by_vehicle`, `list_by_vehicle`, **`list_vehicle_ids_with_newer_telemetry`** (background monitor work queue + throttle) |
| `agent_diagnosis_repository.py` | `create`, `get_latest_by_vehicle`, `list_by_vehicle` |
| `app/rag/repository.py` | raw SQL: hybrid/dense/lexical search over `rag_chunks` (pgvector `<=>` + `ts_rank_cd`), scope filter, document/version/chunk writes, admin listing, health counts (`_ensure_vector()` gate) |

## 4.6 Services (`app/services/`)

| File | Purpose & key logic |
|---|---|
| `auth_service.py` | `register` (normalizes email, always role `user`), `authenticate` (no email probing), `issue_token_pair`, **`rotate`** — reuse of an already-revoked refresh token revokes **all** of that user's tokens (theft detection), `revoke` (idempotent), `change_password` (revokes all refresh tokens). Owns all commits. |
| `vehicle_access.py` | `ensure_vehicle_access` — central ownership gate under routers; non-admins get 404 for others' vehicles (no information leak). |
| `vehicle_service.py` / `telemetry_service.py` | CRUD + idempotent ingest (dedupe on `source_event_id`, `IntegrityError` backstop returns the existing row). |
| `vehicle_health_service.py` | Builds the analysis window (15 min default), fetches recent telemetry + 6 h baseline history, runs `HealthAnalysisEngine`, persists a new `HealthSnapshot` per analysis. |
| `health_monitor.py` | Background loop: picks vehicles whose telemetry is newer than their last snapshot (throttled 60 s, max 25/pass), analyzes, publishes health workflow events, **escalates only `critical`** to `AgentService.run_critical_event` (failures isolated). |
| `simulation_manager.py` | Simulator process lifecycle (start/stop/restart/status, PID files, supervision, orphan cleanup, Windows venv-launcher spawn fix) — see §18. |
| `subscriber_manager.py` | `SubscriberSupervisor` — spawns `python -m app.mqtt.subscriber` as a child process, auto-restart backoff `1 → 16 s`, PID-marker orphan reclamation, `ensure_running()`/`restart()`/`health()`/`shutdown()`. |
| `workflow_event_bus.py` | In-memory observability bus — ring buffer (`deque(maxlen=500)`), non-blocking `publish`, per-subscriber `asyncio.Queue(100)`, `get_recent` (newest first), `get_status`, `clear`, `close`. See §19. |

## 4.7 Schemas (`app/schemas/`)

Request/response contracts: `auth.py` (register/login/refresh/logout/change-password, 8–72 char + 72-byte bcrypt validator), `user.py`, `vehicle.py` (VIN 5–50 uppercased, year 1900–2100), `telemetry.py` (per-field ranges), `common.py` (`PaginatedResponse[T]`), `health.py`, `vehicle_health.py` (`HealthContextResponse.from_context`), `simulation.py` (`SimulationState` incl. `degraded`, interval 0.1–60 s), `rag.py`, `agent.py`, `workflow.py` (events, filters, sanitization — §19).

## 4.8 MQTT (`app/mqtt/`), simulator (`simulator/`), intelligence (`app/intelligence/`)

Documented in detail in [§8](#8--vehicle-simulator), [§9](#9--mqtt), [§10](#10--health-intelligence).

---

---

# 5 — Important Files — Frontend, Scripts, Config

## 5.1 Core frontend infrastructure (`frontend/src/lib/`)

| File | Purpose & key symbols |
|---|---|
| `api-client.ts` | The single HTTP layer. `API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"`. `apiRequest()` does **proactive renewal** when the JWT `exp` is near, and on **401 → renew once → replay once → else anonymous**. `renewSession()` is single-flight. `SESSION_ROUTES` never receive `Authorization`. Wrappers `api.get/post/postForm/patch/delete`. |
| `api-error.ts` | `ApiError` (status, message, code, `isValidationError`, `isConflict`, `isServerOrNetwork`), preserves FastAPI error envelopes. |
| `session-server.ts` | Server-only cookie helpers: `dt_at` / `dt_rt`, `backendFetch`, `refreshAccessToken`, `writeSessionCookies`, `clearSessionCookies` (path-scoped deletion). |
| `session-store.ts` | `useSessionStore` (zustand): access token **in memory only** (never localStorage), `expiresAt`, `user`. |
| `query-keys.ts` | Central TanStack keys: `vehicles`, `simulations`, `telemetry`, `health`, `agent*`, `rag*`. |
| `metrics.ts` | Mirrors backend `METRIC_UNITS` (11 metrics), `TIME_RANGES` (15 m/1 h/6 h/24 h/7 d), labels/units/decimals. |
| `telemetry-stream.ts` | Shared `EventSource` factory + backoff helpers. |
| `format.ts`, `utils.ts` | Formatters; `cn()` = clsx + tailwind-merge. |

## 5.2 Services (`frontend/src/services/`)

| File | Backend calls |
|---|---|
| `auth.ts` | Via Next session proxy: `session`, `login`, `register`, `logout`; direct bearer: `me()` → `GET /auth/me`, `updateProfile()` → `PATCH /users/me`. |
| `vehicles.ts` | `vehiclesApi` (list/get/create/update/delete), `telemetryApi` (list/post), `healthApi` (get/analyze/history), `agentApi` (dashboard/query/critical/diagnoses/latest). |
| `simulations.ts` | `GET /simulations`, `GET|POST|DELETE /vehicles/{id}/simulation`, `POST …/restart`. |
| `rag.ts` | `ragApi.search` (`GET /rag/search`), `ragApi.health`; `adminRagApi.list/get/upload/remove` (multipart via `postForm`). |
| `workflow.ts` | `getRecentEvents(filters)` → `GET /workflow/events/recent`, `getWorkflowStatus()` → `GET /workflow/status`, `createWorkflowEventSource(filters?)` → `new EventSource("/api/workflow/events/stream?…")`. |

## 5.3 Hooks (`frontend/src/hooks/`)

| Hook | Role |
|---|---|
| `use-auth-guard.ts` | Session bootstrap, redirect unauthenticated users to `/login`, loading gate (no flash). |
| `use-active-vehicle.ts` | Resolves the active vehicle (store + `?vehicle=` param, falls back to first). |
| `use-vehicle-data.ts` | `useVehicles`, `useVehicle`, `useHealth`, `useHealthHistory`, `useAgentDashboard/Latest/History`, `useTelemetryWindow` (range → anchored `start_time`/`end_time` so paging never shifts data). |
| `use-telemetry-stream.ts` | SSE consumer: `status (idle/connecting/open/reconnecting/error)`, ring buffer of samples, auto-reconnect, injectable factory for tests. |
| `use-simulations.ts` | `useSimulations` (polls while any run active) + start/stop/restart mutations with optimistic updates + invalidation. |
| `use-workflow.ts` | `useWorkflowStatus`, `useRecentWorkflowEvents(filters)`, `useWorkflowEventStream(filters)` — SSE + recent fallback, reconnection, invalidates status/queries on each event. |
| `use-mutations.ts` | Vehicle CRUD, health analyze, agent ask/critical, profile update (invalidate on success). |

## 5.4 Providers & state (`frontend/src/stores/`)

`providers.tsx` composes `QueryProvider → ThemeProvider → TooltipProvider → VehicleSelectionProvider`. `query-provider.tsx` sets retry/staleTime defaults; `theme-provider.tsx` persists light/dark class on `<html>`; `vehicle-selection.ts` is the selected-vehicle store.

## 5.5 Scripts (`scripts/`)

| Script | What it does |
|---|---|
| `dt-start.ps1 [-ApiPort 8000]` | Starts the **local non-Docker stack** as hidden, tracked background processes under `%TEMP%\dtwin` (one `.pid` + `.out.log`/`.err.log` per component). Prints the **DB target** parsed from `backend/.env` `DATABASE_URL` (classified LOCAL/SUPABASE/REMOTE, never shows credentials) so a silent local-vs-Supabase split is visible. Locates Python at `backend\.venv\Scripts\python.exe`, finds Mosquitto (`$env:DT_MOSQUITTO_EXE` → `%ProgramFiles%\mosquitto\mosquitto.exe` → PATH), then starts: **mosquitto** (`-c infrastructure/mosquitto/mosquitto.local.conf`), **api** (`-m uvicorn app.main:app --host 127.0.0.1 --port <ApiPort>`), **subscriber** (`-m app.mqtt.subscriber`). Ends by running `dt-status.ps1`. Does **not** touch per-vehicle simulators (owned by the Simulation Control API). |
| `dt-stop.ps1` | Stops only tracked components (mosquitto, api, subscriber) by PID file; removes markers; reports stale PIDs; no-op if nothing tracked. |
| `dt-status.ps1 [-ApiPort 8000]` | Reports `running (PID n)` / `stopped` per component, TCP-probes **1883** and the API port, and if the API is up calls `GET /api/v1/health` printing `status` + `service`. |

Backend utility scripts (`backend/scripts/`): `seed_demo_vehicle.py` (idempotent demo vehicle `11111111-2222-4333-8444-555555555555` / VIN `DEMO-SIM-0001`), `ingest_documents.py`, `query_rag.py`, `verify_pgvector.py`, `reset_local_db.py` (hard-refuses non-local DBs), `check_db.py`, `make_migration.py`, `phase5_real_model_smoke.py`, `phase5_agent_rag_verify.py`, `smoke_agent_llm.py` (gated by `RUN_LLM_SMOKE_TEST=true`).

## 5.6 Configuration files

| File | Notes |
|---|---|
| `backend/alembic.ini` | `script_location = alembic`; `sqlalchemy.url` **commented out** — injected in `alembic/env.py` from `get_settings().database_url` (with `%` escaping) |
| `backend/docker-compose.yml` | 5 services: `postgres` (pgvector/pg16, healthcheck), `backend` (`alembic upgrade head && uvicorn --reload`), `mosquitto` (passwd+ACL, healthcheck), `mqtt-subscriber`, `simulator`; volumes `pgdata`, `mqtt-data` |
| `backend/Dockerfile` | `python:3.12-slim`, installs `-e ".[rag]"`, `HEALTHCHECK curl /api/v1/health` |
| `backend/Makefile` | 25 phony targets: `install`, `dev`, `test`, `lint`, `format`, `migrate`, `db-verify`, `db-check`, `db-current/heads/history`, `db-reset-local`, `migration`, `docker-up/down`, `shell`, `up/down/logs`, `seed-demo-vehicle`, `mqtt-subscriber`, `simulator`, `mqtt-test`, `mqtt-broker`, `agent-llm-smoke` (plus a `.venv` bootstrap target) |
| `frontend/next.config.ts` | `reactStrictMode: true`, `typedRoutes: false`, `poweredByHeader: false`, **no rewrites** |
| `.github/workflows/ci.yml` | 2 jobs — backend (ruff, `ruff format --check`, `alembic upgrade head`, `verify_pgvector`, `pytest -q` against a pgvector service DB) and frontend (Node 24, `npm ci`, typecheck, lint, `npm test`) |

---

# 6 — Database

## 6.1 Platform

- **PostgreSQL 16 with pgvector** (local container `pgvector/pgvector:pg16` or **Supabase** with pooling + TLS). Connection string: `DATABASE_URL=postgresql+asyncpg://…`.
- **pgvector** extension is required for RAG (`rag_chunks.embedding_store vector(1024)`). The migration creates it defensively with actionable error messages; `python -m scripts.verify_pgvector` probes extension/index/operators independently.
- All timestamps are `TIMESTAMPTZ`; all primary keys are `UUID` (client-generated `uuid4`).

## 6.2 Tables (9 ORM tables)

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | VARCHAR(320) | unique index `ix_users_email` |
| `password_hash` | VARCHAR(255) | bcrypt |
| `role` | VARCHAR(16) | CHECK `('user','admin')` |
| `full_name` | VARCHAR(120) nullable | |
| `is_active` | BOOLEAN | |
| `created_at`/`updated_at` | TIMESTAMPTZ | server default `now()` |

### `refresh_tokens`
`id` UUID PK · `user_id` UUID FK→users **CASCADE** · `token_hash` VARCHAR(64) (SHA-256 hex, unique index) · `expires_at` TIMESTAMPTZ · `revoked_at` TIMESTAMPTZ nullable. Indexes on `token_hash`, `user_id`, `expires_at`. **Only hashes are stored.**

### `vehicles`
`id` UUID PK · `vin` VARCHAR(50) **unique** · `make` VARCHAR(100) · `model` VARCHAR(100) · `year` INT · `engine_type` VARCHAR(100) nullable · `owner_user_id` UUID FK→users **ON DELETE SET NULL** (indexed) · `source_type` VARCHAR(16) DEFAULT `'simulator'` CHECK `('simulator','real')` · `status` VARCHAR(16) DEFAULT `'active'` CHECK `('active','disabled')` · `simulation_enabled` BOOLEAN DEFAULT false · timestamps.

### `telemetry_records`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `vehicle_id` | UUID FK→vehicles **CASCADE** | indexed |
| `timestamp` | TIMESTAMPTZ | indexed |
| `rpm, speed, engine_load, coolant_temperature, oil_temperature, battery_voltage, fuel_level, intake_air_temperature, throttle_position, engine_runtime, odometer` | FLOAT nullable | the 11 metric columns |
| `raw_payload` | JSONB nullable | full MQTT envelope |
| `source_event_id` | VARCHAR(64) nullable | idempotency key |
| `created_at` | TIMESTAMPTZ | server default |

Indexes: `(vehicle_id, timestamp)` composite; **partial UNIQUE** `(vehicle_id, source_event_id) WHERE source_event_id IS NOT NULL`.

### `vehicle_health_snapshots` (immutable)
`id` UUID PK · `vehicle_id` FK CASCADE · `generated_at`, `window_start`, `window_end` TIMESTAMPTZ · `sample_count` INT · `health_score` FLOAT nullable · `health_status` VARCHAR(20) · `confidence` FLOAT nullable · `context_schema_version` VARCHAR(16) · `context_json` JSONB (full `HealthContext`) · `created_at`.
Indexes: `(vehicle_id, generated_at)` and `(vehicle_id, health_status, generated_at)`. **No update path exists** — every analysis inserts a new row.

### `agent_diagnoses`
`id` UUID PK · `vehicle_id` FK CASCADE · `user_id` FK→users SET NULL (attribution; null for system triggers) · `agent_run_id` VARCHAR(64) · `trigger_type` VARCHAR(32) · `user_query` TEXT · `diagnosis` JSONB · `severity` VARCHAR(16) · `confidence` FLOAT · `status` VARCHAR(16) DEFAULT `'completed'` · `error_code` · `provider` · `model` · `fallback_used` BOOL · `latency_ms` FLOAT · `input_tokens`/`output_tokens` INT · `context_timestamp` · RAG provenance: `rag_used`, `rag_evidence_count`, `rag_embedding_model`, `rag_reranker_model`, `rag_scope` JSONB · timestamps. Indexes: `(vehicle_id, created_at)`, `(vehicle_id, trigger_type, created_at)`.

### `rag_documents`
`id` UUID PK · `source_type` VARCHAR(32) DEFAULT `'manufacturer'` · **`canonical_source` VARCHAR(512) UNIQUE** · `source_uri` · `manufacturer` · `make` · `model` · `model_year_start`/`model_year_end` INT · `document_type` DEFAULT `'generic'` · `title` · `language` · timestamps. Indexes on `(make, model)` and `manufacturer`.

### `rag_document_versions`
`id` UUID PK · `document_id` FK→rag_documents · `version` INT · **UNIQUE (document_id, version)** · `content_hash` VARCHAR(64) (indexed) · `source_filename` · `parser_name`/`parser_version` · `language` · `page_count` · `metadata` JSON · `embedding_model` · `embedding_dimension` (1024) · `chunking_version` (`structural-1.0.0`) · `ingestion_status` VARCHAR(16) (`pending|completed|failed`) · `error_message` · `created_at`.

### `rag_chunks`
`id` UUID PK · `document_version_id` FK→rag_document_versions · `chunk_index` INT · **UNIQUE (document_version_id, chunk_index)** · `chunk_type` (`section|continuation|preamble`) · `title` · `section_title` · `heading_path` JSON · `page_start`/`page_end` · `start_char`/`end_char` · `content_plain` TEXT · **`content_tsv` TSVECTOR** (filled at INSERT via `to_tsvector('english', …)`) · `scope` VARCHAR(32) DEFAULT `'GENERIC'` · `make`/`model`/`year_start`/`year_end` · **`embedding_store vector(1024)`** (nullable) · `created_at`. Indexes: GIN `ix_rag_chunk_content_tsv`, **HNSW `ix_rag_chunk_embedding USING hnsw (embedding_store vector_cosine_ops)`**, plus `(document_version_id)` and `(scope)`.

## 6.3 Alembic migration history (8 revisions — head `b7d9f1e2a3c4`)

| # | Revision | Creates / changes |
|---|---|---|
| 1 | `e01c2724f67b` | **root** — `vehicles` + `telemetry_records` (with `(vehicle_id, timestamp)` index) |
| 2 | `7e38f4f3d70b` | `source_event_id` column + partial unique index |
| 3 | `a1b2c3d4e5f6` | `vehicle_health_snapshots` |
| 4 | `c7f2e8a1b3d4` | `agent_diagnoses` |
| 5 | `4f9d3c2b1a8e` | `rag_documents` + `rag_document_versions` + `rag_chunks` (pgvector `vector(1024)`, `TSVECTOR`, GIN, HNSW) + defensive `CREATE EXTENSION IF NOT EXISTS vector` |
| 6 | `b8c3e1d4a9f7` | RAG provenance columns on `agent_diagnoses` |
| 7 | `d6a9b1c2e3f4` | Phase 6 identity: `users`, `refresh_tokens`, vehicle ownership/`source_type`/`status`/`simulation_enabled`, `agent_diagnoses.user_id` |
| 8 | `b7d9f1e2a3c4` | **HEAD** — idempotent re-creation of `ix_rag_chunk_embedding` (HNSW) after an out-of-band schema rebuild; verifies the `hnsw` access method exists first |

**How migrations run:** `alembic upgrade head` (or `make migrate`). `env.py` takes the URL from application settings (`get_settings().database_url`), uses `asyncio.run` + `connection.run_sync`, and sets `target_metadata = Base.metadata`.

---

---

# 7 — Telemetry Pipeline

This section walks the complete message lifecycle exactly as implemented.

## 7.1 End-to-end lifecycle (15 steps)

1. **Simulator starts.** Either the Simulation Control API spawns `python -m simulator.main` as a child process of the backend (with `SIMULATOR_VEHICLE_ID`, `SIMULATOR_SCENARIO`, `SIMULATOR_INTERVAL_SECONDS`, `SIMULATOR_SEED`, MQTT settings in its environment), or you run it manually for development. It connects to the broker as a publisher and first publishes `status: online` on `vehicles/{id}/status`.
2. **Vehicle state is generated.** `SimulationEngine` runs a deterministic six-state driving machine (`off → starting → idle → accelerating → cruising → decelerating → idle…`) driven by a **seeded** `random.Random(seed)` (default seed `42`), with scenario-specific physical modifiers.
3. **Telemetry is generated.** Every `interval_seconds` (default **1.0 s**) the engine produces an 11-field sample (rounding: most fields 1 dp, `battery_voltage`/`fuel_level` 2 dp, `odometer` 3 dp).
4. **Telemetry is serialized.** `TelemetryMessage.model_dump_json()` produces a versioned JSON envelope (below).
5. **MQTT topic is selected.** `build_telemetry_topic(vehicle_id)` → **`vehicles/{vehicle_id}/telemetry`**.
6. **Message is published.** `MQTTPublisher` publishes with **QoS 1**, `retain=false`. Before the loop it also publishes `vehicles/{vehicle_id}/status` = `online`; on shutdown `offline`.
7. **Mosquitto receives it.** Local broker on `127.0.0.1:1883` (`mosquitto.local.conf`, anonymous, loopback) or the Docker broker (credentialed, ACL `topic readwrite vehicles/#` for user `mqtt`).
8. **MQTT subscriber receives it.** The supervised subscriber process is connected to **`vehicles/+/telemetry`** at QoS 1 (reconnect backoff 1 s → 30 s cap). On connect it emits a `MQTT_RECEIVED / running` workflow event.
9. **Message is parsed/validated.** `TelemetryMessageParser.parse(topic, payload)`: topic must be `prefix/{uuid}/level`, payload must be a JSON object, `TelemetryMessage` must validate (schema_version 1–255, tz-aware timestamp, per-field ranges), and the envelope `vehicle_id` must match the topic. Failures → `TELEMETRY_VALIDATION_ERROR` event, message skipped.
10. **Persistence is attempted with retry.** Up to `mqtt_message_retry_attempts` (3) attempts with `min(2**(n-1), 5)` s waits for `DatabaseError/OSError/RuntimeError`; an unknown vehicle (`NotFoundError`) is discarded immediately.
11. **TelemetryService processes it.** `_ensure_vehicle_exists` → **idempotency check** on `source_event_id` (duplicate returns the existing row, no insert) → insert → `IntegrityError` backstop re-queries the dedupe key → commit. Emits `TELEMETRY_PERSISTED / success` with `duration_ms`.
12. **Health monitor detects new telemetry.** Every 10 s the monitor queries `list_vehicle_ids_with_newer_telemetry` (telemetry newer than last snapshot; per-vehicle throttle 60 s; max 25 vehicles/pass).
13. **Health intelligence processes it.** The 15-minute window is analyzed (statistics, trends, baselines, rules, scoring, confidence) — §10.
14. **Health snapshot is generated.** A new immutable `vehicle_health_snapshots` row is inserted; only `critical` escalates to the agent (5-minute cooldown).
15. **Frontend reads the resulting state.** `GET /vehicles/{id}/telemetry` (paged), the SSE `…/telemetry/stream` (proxied), `GET …/health`, and the workflow page reads live pipeline events.

## 7.2 MQTT topics (exact)

| Purpose | Topic | Notes |
|---|---|---|
| Telemetry publish/subscribe | `vehicles/{vehicle_uuid}/telemetry` | subscriber pattern `vehicles/+/telemetry` |
| Presence status | `vehicles/{vehicle_uuid}/status` | `online` / `offline` |
| Prefix | `MQTT_TOPIC_PREFIX` default `vehicles` | parsers reject topics that are not exactly 3 segments with a UUID middle segment |

## 7.3 Telemetry schema (MQTT envelope, `schema_version = 1`)

```json
{
  "schema_version": 1,
  "event_id": "9f0e1d2c3b4a59688776655443322110",
  "vehicle_id": "11111111-2222-4333-8444-555555555555",
  "timestamp": "2026-10-08T14:21:05.412Z",
  "telemetry": {
    "rpm": 850.0,
    "speed": 0.0,
    "engine_load": 12.0,
    "coolant_temperature": 90.0,
    "oil_temperature": 88.0,
    "battery_voltage": 13.9,
    "fuel_level": 75.0,
    "intake_air_temperature": 30.0,
    "throttle_position": 2.5,
    "engine_runtime": 123.4,
    "odometer": 45231.7
  }
}
```

## 7.4 Telemetry fields, units and validation ranges

| Field | Unit | Valid range (envelope validation) |
|---|---|---|
| `rpm` | RPM | 0 – 10000 |
| `speed` | km/h | 0 – 400 |
| `engine_load` | % | 0 – 100 |
| `coolant_temperature` | °C | −60 – 200 |
| `oil_temperature` | °C | −60 – 200 |
| `battery_voltage` | V | 0 – 40 |
| `fuel_level` | % | 0 – 100 |
| `intake_air_temperature` | °C | −60 – 120 |
| `throttle_position` | % | 0 – 100 |
| `engine_runtime` | s | ≥ 0 |
| `odometer` | km | ≥ 0 |

**Rate:** one sample per `interval_seconds` (default 1.0 s; Simulation Control allows 0.1–60 s).

## 7.5 Simulator scenarios / states

Scenarios (`ScenarioName`): `normal`, `high_temperature`, `low_battery`, `high_engine_load`.

| Modifier | normal | high_temperature | low_battery | high_engine_load |
|---|---|---|---|---|
| `coolant_target` °C | 90.0 | **115.0** | 90.0 | 90.0 |
| `oil_target` °C | 88.0 | **108.0** | 88.0 | 88.0 |
| `running_voltage` V | 13.9 | 13.9 | **11.9** | 13.9 |
| `offline_voltage` V | 12.5 | 12.5 | **11.4** | 12.5 |
| `load_multiplier` | 1.0 | 1.0 | 1.0 | **1.5** |

Driving states: `off, starting, idle, accelerating, cruising, decelerating` (state durations configurable; cruise speed default 60 km/h).

**Vehicle IDs (documented demo values, safe to expose):** the seeded demo vehicle is `11111111-2222-4333-8444-555555555555` (VIN `DEMO-SIM-0001`, *Acme Motors Demo Sedan*, 2026, `2.0L Petrol` — `backend/scripts/seed_demo_vehicle.py`). `.env.example` shows `SIMULATOR_VEHICLE_ID=43f54f26-0985-435d-acb6-3c0c3004a20a` as a placeholder. Real vehicles created through the UI have their own UUIDs.

---

# 8 — Vehicle Simulator

## 8.1 Files & entry point

| File | Role |
|---|---|
| `simulator/main.py` | Entry point: `python -m simulator.main`. Reads `SimulatorSettings`, configures logging, installs SIGINT/SIGTERM handlers, runs `run_forever(settings, stop_event)`. |
| `simulator/config.py` | `SimulatorSettings` — `SIMULATOR_VEHICLE_ID` (**required** UUID), `SIMULATOR_SCENARIO` (default `normal`), `SIMULATOR_INTERVAL_SECONDS` (1.0, > 0), `SIMULATOR_SEED` (42), initial odometer 45231.7 km / fuel 75 % / runtime 0, state durations (off 2 s, starting 3 s, idle 10 s, accelerating 15 s, cruising 30 s, decelerating 10 s), `SIMULATOR_CRUISE_SPEED` 60 km/h, plus shared `MQTT_*` settings; client id default `dtwin-sim-{8 hex}` (≤23 chars for MQTT v3.1.1). |
| `simulator/vehicle.py` | `DrivingState`, `VehicleState` dataclass (all sensor fields + units), `NEXT_STATE` transition map, `SimulationEngine` with seeded RNG and the per-state sensor equations (e.g. cruising rpm ≈ `2000 + speed*2 ± 60`, fuel burn `0.35 + engine_load*0.015` %/h, `odometer += speed/3600·dt`). |
| `simulator/telemetry_generator.py` | `Scenario` modifiers (table above) + `_build_telemetry()` producing rounded `TelemetryData`. |
| `simulator/publisher.py` | `SimulatorPublisher = MQTTPublisher` (reuses `app.mqtt.publisher`). |

## 8.2 Deterministic behaviour

The engine owns a `random.Random(seed)`; **the same seed replays the same drive** (asserted by `tests/simulator/test_telemetry_generator.py`). Physics are clamped (fuel 0–100, battery 0–30 V, load/throttle 0–100) and temperatures ease toward scenario targets with per-state rates.

## 8.3 Simulation lifecycle & process supervision

Implemented in `backend/app/services/simulation_manager.py`:

- **Start** — `start(vehicle_id, scenario, interval_seconds, seed)`: publishes `SIMULATION_START_REQUESTED/STARTED` workflow events; **409 Conflict** if a simulation is already `starting/running/stopping` for that vehicle; spawns the child process; waits for the settled event (`grace × 2 + 5 s`); publishes `SIMULATION_STARTED / success` (metadata includes PID).
- **Spawn** — command built by `python_module_command("simulator.main")`. On Windows, if `sys.executable` is a venv launcher redirector, it executes the **base interpreter** directly and injects `__PYVENV_LAUNCHER__` into the child environment so exactly **one** real worker process starts (fix for the historic double-spawn bug — `P0_SIMULATION_CONTROL_FINAL_REPORT.md`). Environment includes the scenario/seed/interval + MQTT settings; `cwd = backend/`; stdout+stderr go to `{runtime_dir}/{vehicle_id}.log`; Windows uses `CREATE_NEW_PROCESS_GROUP`.
- **PID marker** — `{runtime_dir}/{vehicle_id}.{pid}.pid` containing `pid` and the **owner backend PID** (used to avoid killing another backend's child).
- **Supervision** — a `monitor_task` races `process.wait()` against the 3 s startup grace. Exiting before grace → status `error` with `_exit_reason` including the **last 40 log lines**. Clean `stop()`/`stopping` → status `stopped`. Unexpected exit publishes `SIMULATION_PROCESS_EXIT / error`.
- **Stop** — idempotent; terminate → wait `stop_timeout` (5 s) → kill → wait again; removes the PID file; status `stopped`.
- **Restart** — terminate existing (if any) then spawn with the new configuration; publishes `SIMULATION_RESTART_*` events.
- **Failure handling** — spawn `OSError` → `SimulationError` (HTTP 502). Crash log tail is folded into the API-visible `error`.
- **Duplicate-process avoidance** — three layers: (1) per-vehicle `asyncio.Lock` + conflict check, (2) PID-marker files owned by this backend, (3) `cleanup_stale()` at startup kills orphaned simulator PIDs from crashed backends (skipping markers owned by a *live* different backend), and orphan reclaim for the subscriber.
- **Process liveness** — POSIX `os.kill(pid, 0)`; Windows `OpenProcess` + `WaitForSingleObject`.

## 8.4 How Simulation Control interacts with the simulator

The frontend never touches processes directly — it calls the REST endpoints in [§18](#18--simulation-control); the API translates them into `SimulationManager` operations on the shared singleton (built in lifespan, injectable via `dependency_overrides` for tests).

---

# 9 — MQTT

## 9.1 Roles

| Component | File | Role |
|---|---|---|
| Broker | Mosquitto 2 | Local dev: `infrastructure/mosquitto/mosquitto.local.conf` → `listener 1883 127.0.0.1`, `allow_anonymous true`. Docker: `mosquitto.conf` (`allow_anonymous false`, generated `mosquitto.passwd`, `acl_file` granting user `mqtt` `topic readwrite vehicles/#`, persistence on). |
| Client factory | `app/mqtt/client.py` | `create_mqtt_client(settings)` → `aiomqtt.Client` (keepalive 60, clean session, credentials only when `MQTT_USERNAME` set). `run_async` installs a `SelectorEventLoop` on Windows. |
| Publisher | `app/mqtt/publisher.py` | `MQTTPublisher` async context manager; `publish_telemetry`/`publish_status`; **QoS = `mqtt_qos` (1)**, `retain=False`. |
| Subscriber | `app/mqtt/subscriber.py` | Subscribes `vehicles/+/telemetry` QoS 1; exponential reconnect backoff 1 s → `mqtt_reconnect_max_seconds` (30 s); per-message parse → validate → persist with retry; publishes workflow events (`MQTT_RECEIVED`, `TELEMETRY_PARSED`, `TELEMETRY_PERSISTED`, errors). Runnable as `python -m app.mqtt.subscriber` with SIGINT/SIGTERM handlers. |
| Parser | `app/mqtt/parser.py` | `TelemetryMessageParser` — topic structure, JSON decode, schema validation, envelope/topic `vehicle_id` match. |
| Envelopes | `app/mqtt/schemas.py` | `TelemetryMessage`, `TelemetryData` (ranges), `StatusMessage`; `extra="forbid"`, tz-aware timestamps required, `SCHEMA_VERSION = 1`. |
| Topics | `app/mqtt/topics.py` | Builders/parsers documented in §7.2. |

## 9.2 Configuration defaults

| Env var | Default |
|---|---|
| `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` | `localhost` / `1883` |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | unset (anonymous) |
| `MQTT_CLIENT_ID` | `dtwin-sub-{8 hex}` (auto-unique per process) |
| `MQTT_KEEPALIVE` | `60` |
| `MQTT_QOS` | `1` |
| `MQTT_TOPIC_PREFIX` | `vehicles` |
| `MQTT_RECONNECT_MAX_SECONDS` | `30.0` |
| `MQTT_MESSAGE_RETRY_ATTEMPTS` | `3` |

## 9.3 Relationship: Simulator → Mosquitto → Subscriber → PostgreSQL

`Simulator (publisher)` → `Mosquitto :1883` → `MQTT subscriber (backend child process)` → `TelemetryService` → `PostgreSQL`. **The backend supervises the subscriber:** `app/main.py` lifespan calls `subscriber_supervisor.ensure_running()` at startup (starting it if the PID marker is dead, reclaiming orphans), monitors it with auto-restart backoff `1 → 16 s`, and shuts it down on exit (`app/services/subscriber_manager.py`). If the subscriber is down, Simulation Control reports `degraded` immediately.

## 9.4 Running MQTT locally

```powershell
# Option A — helper script (starts broker + API + subscriber)
.\scripts\dt-start.ps1

# Option B — make target (uses mosquitto.local.conf)
make mqtt-broker      # in backend/, needs mosquitto on PATH or %ProgramFiles%\mosquitto
```

The Docker alternative is `docker compose up mosquitto` in `backend/`.

---

---

# 10 — Health Intelligence

**What:** deterministic (non-ML) analysis of a telemetry window that produces a score, status, confidence, findings, trends and baselines, persisted as an immutable snapshot.
**Why:** give the vehicle an auditable, reproducible health verdict derived only from real measurements — no black box.
**Where:** `backend/app/intelligence/` (engine) + `backend/app/services/vehicle_health_service.py` (window fetch + persistence) + `backend/app/services/health_monitor.py` (background scheduling).

## 10.1 Concepts

| Concept | Implementation | Value |
|---|---|---|
| **Telemetry window** | `health_analysis_window_minutes` | 15 min default; overridable per request (`window_minutes`, 1–1440) |
| **Sample count / sufficiency** | `DataSufficiency` = `no_data \| limited_data \| sufficient_data` | 0 samples → no data; **< 10 samples** (`health_minimum_samples`) → limited data (provisional); ≥ 10 → sufficient |
| **Data quality** | coverage (expected vs received samples, expected interval 1 s), duration, completeness across the 11 metrics | feeds confidence |
| **Provisional health** | `provisional=True` + `provisional_rating` set when `limited_data` | explicitly labelled *"provisional assessment with low confidence, not a definitive verdict"* (LIMITED_DATA finding); disappears when enough samples arrive |
| **Health score** | `100 − penalties`, penalties `info 0 / warning 10 / critical 30`, **capped at 40 per category**, no findings → 100; clamped 0–100 | `scoring.py` |
| **Health rating (status from score)** | ≥ **80 → healthy**, ≥ **60 → attention**, else **critical**; score `None` → `unknown` | `STATUS_HEALTHY_MIN/ATTENTION_MIN` |
| **Health status** | `healthy \| attention \| critical \| unknown \| no_data \| limited_data` | `no_data`/`limited_data` **override** the scored status (build-time override) |
| **Confidence** | `0.10 + 0.90·(0.30·coverage + 0.25·duration_ratio + 0.25·sample_sufficiency + 0.20·completeness)`, rounded to 4 dp | measures confidence in the *telemetry-based assessment* (0–1) |
| **Baseline comparison** | 6 h history (`health_baseline_window_minutes=360`), min 5 samples; median + scaled MAD (`1.4826`); deviation > +2.0 → `elevated`, < −2.0 → `depressed`, else `within`; insufficient → `insufficient_history` | `baselines.py` |
| **Rule evaluation** | 13 deterministic rules (below) producing `Finding{rule_id, severity, category, confidence, evidence}` | `rules.py` |
| **Health snapshot** | new `vehicle_health_snapshots` row per analysis with full `HealthContext` JSONB | **immutable — never updated** |
| **Health monitor** | background loop (10 s interval) evaluating due vehicles (telemetry newer than snapshot, throttled 60 s, max 25/pass) | `health_monitor.py` |

**Rule IDs:** `COOLANT_TEMP_HIGH`, `OIL_TEMP_HIGH`, `BATTERY_VOLTAGE_LOW`, `BATTERY_VOLTAGE_HIGH`, `ENGINE_LOAD_HIGH`, `RPM_UNUSUAL`, `FUEL_LEVEL_LOW`, `RAPID_COOLANT_RISE`, `RAPID_OIL_TEMP_RISE`, `TELEMETRY_GAP` (info), `LOW_DATA_COVERAGE` (info), plus `INSUFFICIENT_DATA` and `LIMITED_DATA`.

**Key thresholds (`RuleThresholds`):** coolant/oil warning 100 °C, critical 110 °C; rapid rise 8 °C; battery warning < 12.0 V / critical < 10.5 V / high > 15.0 V; engine load mean warning 40 % / critical 60 %; rpm mean warning 4500; fuel warning 15 % / critical 5 %; gap multiplier 3×; coverage minimum 0.5.

**Trends:** OLS slope of value vs elapsed seconds; normalized slope → `increasing|decreasing|stable`, strength `none|weak|moderate|strong` (min 3 samples).

## 10.2 Status semantics (honest data states)

| Status | Meaning |
|---|---|
| `no_data` | Zero samples in the window — score `None`, confidence `None`, an `INSUFFICIENT_DATA` info finding explains it |
| `limited_data` | Fewer than 10 samples — rules still run on what exists, status forced to `limited_data`, snapshot flagged **provisional** |
| `healthy` / `attention` / `critical` | Scored verdict (≥80 / ≥60 / <60) from full rule evaluation |
| `unknown` | Score unavailable for reasons other than the above |
| `UNKNOWN` (agent-facing `determinism` layer) | `derive_severity` falls back to `info` when no context exists |

**How health changes with more data:** each analysis is a fresh snapshot; as samples accumulate `limited_data → sufficient_data`, the provisional flag clears, baselines unlock (≥5 history samples), and scores/statuses converge.

## 10.3 Source files

`intelligence/engine.py` (orchestration + sufficiency branches), `models.py` (`CONTEXT_SCHEMA_VERSION = "1.1"`, `RULE_ENGINE_VERSION = "1.0"`, 11 `METRIC_UNITS`), `statistics.py`, `trends.py`, `baselines.py`, `rules.py`, `scoring.py`, plus `services/vehicle_health_service.py` (windowing + snapshot creation) and `services/health_monitor.py` (scheduling + critical escalation).

---

# 11 — RAG / Manufacturer Guidance

**What:** a local vector + full-text corpus of manufacturer documents with hybrid retrieval and cross-encoder reranking, exposed as an evidence search API and as grounding for the agent.

## 11.1 The pipeline as implemented

```
Document upload (admin, multipart)
    ↓  get_parser_for(suffix) — plain-text (.txt/.md/.text) | Docling (14 formats) | unsupported (error)
Text extraction (canonical Markdown-heading text, SHA-256 content hash)
    ↓  version resolution: same hash → "unchanged"; failed/pending retry reuses row; new content → version+1
Section detection (Markdown ATX headings, heading path/breadcrumbs, page spans @ 4400 chars/page)
    ↓  chunk_by_structure — chunk_size 800 chars, overlap 120, never splits a heading line, CHUNKING_VERSION "structural-1.0.0"
Metadata attachment (scope tier GENERIC/MAKE/MODEL/EXACT_VEHICLE, make/model/year, per-chunk indices)
    ↓  BAAI/bge-m3 — 1024-dim, L2-normalized, batch 16, max_length 1024
Embedding
    ↓  pgvector: rag_chunks.embedding_store vector(1024) + content_tsv TSVECTOR
Vector storage + index (HNSW cosine ops + GIN)
    ↓
Ready (version ingestion_status = "completed"; INDEX_READY event)
```

**Query path:** `raw question → strip VIN (17-char) + build_plan → cap 500 chars → BGE-M3 query embedding → hybrid search (dense cosine `1 - (a <=> b)` blended with `ts_rank_cd` lexical, α = 0.6, vehicle scope filter, completed versions only, top 30) → rerank (BGE-reranker-v2-m3 CrossEncoder, sigmoid scores, top 30 → keep ≥ 0.2 → top 5) → citations + verbatim guidance (≤1800 chars/chunk) → response`.

## 11.2 Actual values (from `app/rag/config.py`)

| Setting | Value |
|---|---|
| Supported formats | `.txt .md .text` (plain parser) + `.pdf .docx .doc .rtf .pptx .ppt .html .mhtml .xlsx .xls .odt .ods .odp .epub` (Docling) — **17 extensions**, no silent fallback |
| Chunk size / overlap | **800 / 120** chars |
| Embedding model | **`BAAI/bge-m3`**, dimension **1024**, L2-normalized (`stub` option for tests/CI) |
| Reranker model | **`BAAI/bge-reranker-v2-m3`** (max_length 512; sigmoid → [0,1]) |
| Vector index | **HNSW** (`vector_cosine_ops`); lexical **GIN** on `tsvector` |
| Retrieval | hybrid α = **0.6**, candidates **30**, final **5** (`RAG_RETRIEVAL_TOP_K=25` is declared but unused by call sites) |
| Min rerank score | **0.2** |
| Scope handling | chunk `scope` tier + SQL filter on make/model/year-range; tier boost +0.10 make / +0.15 model / +0.05 year |
| Source attribution | every evidence item carries document id/version, chunk id, filename, title, section, heading path, page span, per-signal scores |
| Limits | upload 50 MB (`RAG_MAX_UPLOAD_SIZE_MB`), parse ≤ 2000 pages / 50 MiB, ≤ 20 000 chunks/document, query ≤ 500 chars, evidence ≤ 1800 chars |
| Chunking metadata | `chunking_version = "structural-1.0.0"`; page spans approximated at 4400 chars/page |

**Filters:** `/rag/search` accepts `q`, `make`, `model`, `year`, `top_k` (1–20). Document listing filters: exact `make`/`model`/`canonical`, year range containment, version status.

**LLM involvement:** the **search endpoint contains no LLM** — guidance is assembled verbatim from retrieved chunks with `[n]` source markers. The LLM only appears in the agent path (§14), which receives this guidance as evidence.

## 11.3 Key files

`app/rag/config.py` (all constants), `parser/` (`PlainTextParser` v1.1.0, `DoclingParser` v2.130.x, routing in `__init__.py`), `chunking.py`, `embeddings.py`, `retrieval.py` (`rerank_and_select`), `reranker/base.py`, `query_builder.py`, `repository.py` (raw SQL), `rag_service.py` (orchestration), `admin_documents.py` (upload/list/detail/delete), `scope.py`, `schemas.py`, `errors.py`; ORM in `app/models/rag.py`; API in `routes/rag.py` + `routes/admin_rag.py`.

---

# 12 — Document Ingestion Workflow (Observability)

**Status: implemented.** The Workflow Monitor is a real, in-memory, event-based observability system (no database persistence). Every stage below is emitted by the actual ingestion code in `app/rag/ingestion.py`.

## 12.1 Actual ingestion events

```
DOCUMENT_UPLOAD_STARTED / started        (filename, size, canonical source)
    → DOCUMENT_RECEIVED / success
    → DOCUMENT_PARSE_STARTED / running    (parser name)
    → DOCUMENT_PARSED / success           (pages, char_count)
    → TEXT_EXTRACTED / success
    → SECTIONS_DETECTED / success         (section count)
    → CHUNKING_STARTED / running          (chunk_size, chunk_overlap)
    → CHUNKS_CREATED / success
    → METADATA_ATTACHED / success         (make/model/year scope)
    → EMBEDDING_STARTED / running
    → EMBEDDINGS_GENERATED / success      (duration_ms, model, dimensions)
    → VECTOR_STORAGE_STARTED / running
    → CHUNKS_STORED / success
    → INDEX_READY / success
    → INGESTION_COMPLETED / success       (or reason "unchanged")
failure path → INGESTION_ERROR / error    (version marked failed)
```

## 12.2 The event system itself (`WorkflowEvent`)

- **Model** (`app/schemas/workflow.py`, frozen, `extra="forbid"`): `event_id`, `timestamp`, `workflow`, `stage`, `status`, `message`, optional `vehicle_id`, `document_id`, `correlation_id`, `duration_ms`, `metadata`.
- **Enums:** `WorkflowType` = `telemetry | rag_ingestion | rag_query | health | agent | simulation | system`; `WorkflowStatus` = `started | running | success | warning | error`; `WorkflowStage` = ~70 snake_case stages grouped per workflow (full list in the source; e.g. telemetry stages `simulator_started … telemetry_error`, agent stages `agent_request_received … agent_error`, system stages `subscriber_started/stopped/error`).
- **Event bus** (`app/services/workflow_event_bus.py`): bounded `deque(maxlen=500)` ring buffer (`WORKFLOW_EVENT_BUFFER_SIZE`, 50–5000), max 50 subscribers (`WORKFLOW_MAX_SUBSCRIBERS`), per-subscriber `asyncio.Queue(100)`. `publish()` is **non-blocking fire-and-forget** (a slow subscriber is dropped on `QueueFull` — observability never crashes the core). `get_recent(limit, offset)` returns **newest first**; `get_status()` returns buffer stats; `clear()` empties the view only; `close()` poisons subscribers. Singleton via `get_workflow_event_bus()`.
- **Transport — SSE + recent:**
  - `GET /api/v1/workflow/events/stream` — Server-Sent Events, heartbeat comment every 15 s (`WORKFLOW_SSE_HEARTBEAT_SECONDS`), filters `workflow/status/vehicle_id/document_id`, headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`, closes on client disconnect.
  - `GET /api/v1/workflow/events/recent` — paged history of the buffer (`limit` 1–500 default 100, `offset`), filters including `stage`, `correlation_id`, `since/until`.
  - `GET /api/v1/workflow/status` — pipeline liveness (`telemetry_pipeline_active`, `rag_pipeline_active`, `agent_pipeline_active`, `subscriber_running`, `active_simulations`, buffer stats).
- **Frontend stream:** `EventSource` through the Next.js proxy `frontend/src/app/api/workflow/events/stream/route.ts` (attaches the bearer token from the `dt_at` cookie, forwards query params, cancels upstream on client disconnect).
- **Filtering:** the `filters.tsx` component feeds the same filters to both the SSE query string and the recent-events fetch; `use-workflow.ts` merges the live stream into the cached list and reconnects with backoff.
- **Correlation IDs:** producers attach `correlation_id` (e.g. telemetry events carry the MQTT `event_id`) and `vehicle_id`/`document_id` so one operation can be traced across stages.
- **Error events:** failures emit `…_ERROR / error` stages (validation, persistence, parse, ingestion, agent, simulation, subscriber).
- **Reconnect behaviour:** EventSource closes on failure; the hook re-opens with backoff and re-fetches `recent` to backfill the gap.

## 12.3 Safety: event sanitization

`sanitize_metadata()` (2048-byte cap) **redacts** any metadata key containing `password`, `api_key`, `token`, `secret`, `credential`, `authorization`, `access_token`, `refresh_token`, `database_url`, `db_password`, `mqtt_password`, `llm_api_key`, `openai_key`, `provider_key`, **`chain_of_thought`, `reasoning`, `thought`** (case-insensitive) → `[REDACTED]`; truncates strings > 1000 chars; oversized payloads become `{"_truncated": …}`. No secrets, no chain-of-thought, no large payloads can enter the stream.

---

# 13 — RAG Query Workflow

As observable in the Workflow Monitor, one user question produces:

```
QUERY_RECEIVED / started
  → QUERY_EMBEDDING_STARTED / running
  → QUERY_EMBEDDING_COMPLETED / success
  → VECTOR_SEARCH_STARTED / running        (candidate_k=30, alpha=0.6)
  → VECTOR_SEARCH_COMPLETED / success
  → CANDIDATES_RETRIEVED / success
  → RERANKING_STARTED / running            (top 30 cross-encoder scores)
  → RERANKING_COMPLETED / success          (threshold 0.2 → top 5)
  → CONTEXT_ASSEMBLED / success
  → ANSWER_GENERATION_STARTED / success    (verbatim guidance assembled)
  → ANSWER_GENERATED / success
  → SOURCES_ATTACHED / success             (citations with provenance)
  → RAG_QUERY_COMPLETED / success          (metrics: query_chars, vin_detected,
                                            lexical_variants, rerank_used, alpha,
                                            candidates, scope_filtered, models)
error path → RAG_QUERY_ERROR / error
```

**How a faculty member observes this:** open **Workflow Monitor → RAG Query tab** (or filter `workflow=rag_query`), ask a question on the Manufacturer Guidance page, and watch the stages appear live with durations; the pipeline panel highlights each node as events arrive, and the event timeline shows the exact candidate/rerank metrics.

When the *agent* asks the RAG question, the same stages are emitted with `workflow=rag_query` and are correlated to the `agent` workflow events of the same run.

---

# 14 — LangGraph Agent

**What:** a LangGraph state graph that answers vehicle questions with a structured, grounded diagnosis.
**Where:** `backend/app/agent/`.

## 14.1 Graph structure (actual)

```
START → supervisor ──(conditional)──┬─ rag ──(conditional)──┬─ reason → validate → persist → END
                                    ├─ reason ──────────────┤
                                    └─ validate (short-circuit) ┘
```

| Node | Role (high level) |
|---|---|
| `supervisor` | Loads the **Vehicle Health Context** through `VehicleContextTool` (the only way vehicle data reaches the LLM), decides `needs_rag` (deterministic gate: tool present + non-blank query) and `needs_llm` (context available), publishes `SUPERVISOR_STARTED` etc. |
| `rag` | Calls the read-only `ManufacturerGuidanceTool` (`get_guidance(vehicle_id, query)`); RAG evidence upgrades `needs_llm` so the graph reasons even without telemetry context. Degrades gracefully (`rag-disabled`, `no-evidence`, `retrieval-error` — never raises). |
| `reason` | Builds prompt messages (context JSON + guidance + numbered sources) and calls `LLMService.invoke_structured()`; captures execution metadata (latency, provider, model, fallback, tokens, attempts, RAG metrics). |
| `validate` | Parses/validates `DiagnosisContent`, **grounds every evidence item** against real rule findings/metric statistics (fabricated items dropped), verifies citations against actual retrieved evidence, clamps `assessed_severity ≤ rule_severity` and `assessed_confidence` within ±0.2 of the deterministic confidence. No context → canned, fully grounded non-LLM reasoning. |
| `persist` | Writes an `AgentDiagnosis` row (diagnosis JSONB + provider/model/fallback/latency/tokens + RAG provenance), commits, returns the final `DiagnosisResponse`. |

Runtime dependencies (tool, LLM service, repository, session) are injected per invocation through the graph `context_schema` (`AgentGraphContext`); compiled graphs are cached in a bounded LRU (16 entries) keyed on configuration.

**Trigger types:** `USER_QUERY`, `CRITICAL_TELEMETRY_EVENT`, `DASHBOARD_LOAD`.

**Degradation & dedup:** `AgentService.run_critical_event` returns a recent completed critical diagnosis when the same critical rules recur within `AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS` (300 s) — `execution.deduplicated = true`, **no LLM call**. `get_dashboard_context` never calls the LLM.

**Note on reasoning:** this document intentionally describes only node roles and validation behaviour. The system prompt (`app/agent/prompts.py`) constrains the model to output a single JSON object grounded in the provided context and never to invent metrics, thresholds or source numbers. **Chain-of-thought is neither stored, emitted, nor exposed** anywhere (workflow metadata sanitization even redacts `reasoning`/`chain_of_thought` keys).

## 14.2 Tools

| Tool | Purpose |
|---|---|
| `VehicleContextTool` | Reads the latest health snapshot → bounded, serialized `HealthContext` (≤ `LLM_CONTEXT_MAX_CHARS`, min 1024) + data-quality note + deterministic severity/confidence. The LLM never issues SQL. |
| `ManufacturerGuidanceTool` | Thin read-only adapter over `RAGService` with vehicle scope; returns indexed evidence + citations; `available=False` with a reason is normal degradation, not an error. |

## 14.3 Response contract (what the user sees)

`DiagnosisResponse` = `id, vehicle_id, trigger_type, user_query, diagnosis, severity, confidence, context_timestamp, generated_at, execution`. `diagnosis` contains `summary`, `possible_causes[]` (likelihood `high|medium|low`), `recommended_actions[]` (priority `immediate|high|medium|low`, category `mechanical|inspection|logistics|operator|other`), `evidence[]` (traced to real findings), `severity_analysis`, `confidence_analysis` (+ `validation_warnings`), `manufacturer_guidance`, `citations[]`, `cited_sources[]`.

---

# 15 — LLM Providers

## 15.1 Architecture

- **Selection:** `build_llm_provider(name, settings)` — exactly three supported names: **`openrouter`**, **`groq`**, **`mock`** (anything else → `AgentConfigurationError`).
- **Primary/fallback:** `LLM_PRIMARY_PROVIDER` (default `openrouter`) and `LLM_FALLBACK_PROVIDER` (default `groq`). On failure the `LLMService` classifies the error:
  - **Fallback-eligible:** timeout, rate-limit, connection, server, unknown, **auth** (misconfigured key counts as configuration error → fallback).
  - **Never retried/re-routed:** `bad_request` (400) — a malformed request will fail again.
  - **Retries before fallback:** up to `LLM_MAX_RETRIES + 1` attempts with exponential backoff `0.2 s × 2ⁿ` capped at `2.0 s`, each bounded by `LLM_REQUEST_TIMEOUT_SECONDS`.
- **Structured output:** every real provider forces `chat_model.with_structured_output(DiagnosisContent, method="function_calling")`; parse failures become `StructuredOutputError` (HTTP 502). Provider errors are classified into a taxonomy (`AUTH/TIMEOUT/RATE_LIMIT/CONNECTION/SERVER/BAD_REQUEST/UNKNOWN`) and mapped to HTTP in `main.py` (504 timeout, 503 rate-limit, 502 auth/provider/bad-request).
- **Mock provider:** deterministic, in-process, **no network** — builds a realistic diagnosis from the embedded health context (severity/confidence via the deterministic helpers) and echoes any `Sources:` list into `cited_sources`. Used for tests and offline development.

## 15.2 Configuration (exact env vars; no secrets included)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PRIMARY_PROVIDER` | `openrouter` | primary provider name |
| `LLM_FALLBACK_PROVIDER` | `groq` | single fallback (empty disables) |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | unset / `""` (example: `openai/gpt-4o-mini`) | OpenRouter (base URL `https://openrouter.ai/api/v1`) |
| `GROQ_API_KEY` / `GROQ_MODEL` | unset / `""` (example: `llama-3.3-70b-versatile`) | Groq (base URL `https://api.groq.com/openai/v1`) |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | per-attempt timeout |
| `LLM_MAX_RETRIES` | `2` | retries on primary before fallback |
| `LLM_TEMPERATURE` | `0.1` (validated 0–1) | sampling temperature |
| `LLM_MAX_TOKENS` | `1500` | max completion tokens |
| `LLM_CONTEXT_MAX_CHARS` | `24000` | serialized context cap |
| `AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS` | `300` | critical-event dedup window |
| `RUN_LLM_SMOKE_TEST` | `false` | gate for `scripts/smoke_agent_llm.py` |

**Development mode:** with no keys configured, providers raise `AgentConfigurationError` at build time and the API returns 500 `agent_configuration_error`; tests and offline demos use `mock`. **Production:** set primary + fallback keys and a `JWT_SECRET` (see §30). Missing keys never leak — error text is scrubbed by `providers/base.py` (`***` redaction, 300-char cap).

---

# 16 — Authentication

## 16.1 Flows

- **Registration** — `POST /auth/register` (rate-limited, scope `auth:register`): email normalized (trim + lowercase), password hashed with **bcrypt** (8–72 chars, hard 72-byte cap enforced by validator), role always `user` (never caller-supplied). Duplicate email → 409.
- **Login** — `POST /auth/login` (scope `auth:login`): unknown email and bad password both return **401** (no account probing). Response: `TokenResponse{access_token, refresh_token, expires_in, user}`.
- **JWT (access token)** — HS256 (`JWT_ALGORITHM`), claims `sub` (user id), `type = "access"`, `iat`, `exp`; default lifetime **20 min** (`AUTH_ACCESS_TOKEN_MINUTES`). Verified per request by `get_current_user`, which re-reads the user from the DB (role/active never stale).
- **Refresh tokens** — value `secrets.token_urlsafe(48)`; **only the SHA-256 hash is stored** (`refresh_tokens.token_hash`, unique). Default lifetime 30 days (`AUTH_REFRESH_TOKEN_DAYS`).
- **Refresh rotation** — `POST /auth/refresh`: validates hash (missing/revoked/expired → 401), **revokes the presented token and issues a fresh pair**. **Reuse of an already-revoked token revokes ALL refresh tokens of that user** (token-theft detection).
- **Logout** — `POST /auth/logout`: revokes the presented refresh token; **idempotent, always 204**.
- **Password change** — `PATCH /auth/password`: current password must verify (401 otherwise); new hash stored; **all refresh tokens revoked** (other sessions signed out; existing access tokens survive to natural expiry).

## 16.2 Ownership & authorization

- `ensure_vehicle_access(repository, vehicle_id, user)` — executed below the router so no endpoint can bypass it. Admins may access any vehicle; everyone else gets **404** for vehicles they don't own (no existence leak).
- `require_admin` — 403 unless `role == "admin"` (guards `/rag/health` and all `/admin/rag/*` uploads).
- Cross-user reads of telemetry/health/agent/simulation resources are denied by the same gate (covered by `tests/api/test_authorization.py`).

## 16.3 Frontend session model

Next.js route handlers hold `dt_at` (access, httpOnly, 12 h) and `dt_rt` (refresh, httpOnly, **path `/api/session`**, 30 d) cookies. `api-client.ts` keeps the access token **in memory only**, renews proactively/expired once (single-flight), and the two SSE proxies attach the bearer server-side. The refresh cookie never reaches browser JavaScript.

---

# 17 — Frontend

**Architecture:** Next.js 16 App Router, React 19, strict TypeScript, Tailwind v4 CSS-first theme (`globals.css @theme`, no `tailwind.config`), hand-written shadcn-style primitives on Radix, TanStack Query for all server data (central keys in `lib/query-keys.ts`), Zustand only for session + selected vehicle, SSE via `EventSource` through Next route handlers.

**Error/loading handling:** shared `states/feedback.tsx` primitives — `EmptyState`, `ErrorState` (status presets: 0 offline, 401 expired, 403 forbidden, 404, 502 AI provider unavailable, 503 dependency down, 504 timeout, shows `error.code`, optional retry), `InlineAlert`. Skeletons (`ui/skeleton.tsx`) for every load shape. `useAuthGuard` gates pages without flashing.

## 17.1 Every major screen

| Screen (route) | Purpose | API endpoints | Key components / user actions |
|---|---|---|---|
| **Login** (`/login`), **Register** (`/register`) | Authentication | `POST /api/session/login`, `POST /api/session/register` | `LoginForm`, `RegisterForm` — per-field FastAPI validation errors; success seeds the session store |
| **Dashboard** (`/dashboard`) | Fleet overview | `GET /vehicles`, `GET …/agent/dashboard`, health/telemetry per vehicle | `DashboardView` — health score ring, findings, critical alerts, live feed card |
| **My Vehicles** (`/vehicles`) | Vehicle CRUD | `GET/POST/PATCH/DELETE /vehicles` | `VehiclesView` + `VehicleFormDialog` (VIN validation, 409 conflict handling), empty/error states |
| **Vehicle workspace** (`/vehicles/[id]` + tabs) | Per-vehicle detail | see sub-rows | `VehicleWorkspace` with link tabs: Overview / Health / Telemetry / Diagnosis / History |
| → Overview | Summary | health latest, diagnosis latest, telemetry | `VehicleOverview` — cards + quick actions |
| → Health | Health verdict | `GET …/health` (404 → prompt), `POST …/health/analyze`, `GET …/health/history` | `HealthSummaryPanel`, `FindingsList` (observed vs threshold), analyze button, history pagination |
| → Telemetry | Measurement explorer | `GET …/telemetry`, SSE `…/telemetry/stream` | `TelemetryExplorer` (range control 15 m–7 d, metric chips, recharts `TelemetryChart`, table with pagination), `LiveTelemetryFeed` (SSE status chip, stale after 10 s, **5 s polling fallback** while the stream is down) |
| → Diagnosis | Agent answers | `POST …/agent/query`, `GET …/agent/diagnoses(/latest)`, `POST …/agent/events/critical` | `DiagnosisPanel` (question form) + `DiagnosisCard` (severity/confidence, provider/model, fallback alert, causes, actions, evidence, manufacturer guidance, citations) |
| → History | Snapshot trend | `GET …/health/history` | history table/trend of immutable snapshots |
| **Simulation Control** (`/simulations`) | Start/stop/restart simulators | `GET /simulations`, `POST/GET/DELETE /vehicles/{id}/simulation`, `POST …/restart` | `SimulationsView` — per-vehicle status chips (incl. **degraded**), start form (scenario, interval 0.1–60 s, seed), optimistic updates, polling while active, 409/502 error handling |
| **Manufacturer Guidance** (`/rag`) | Evidence search | `GET /rag/search` | `RagSearchView` — query + make/model/year filters, scored chunks with provenance |
| **Admin RAG** (`/admin/rag`) | Corpus management (admin) | `GET /rag/health`, `GET/POST/DELETE /admin/rag/documents` | `AdminRagView` tabs: health (corpus counts, degraded alerts), upload dialog (17 accepted extensions, metadata form), documents list with version history + delete |
| **Workflow Monitor** (`/workflow`) | Live observability | `GET /workflow/status`, `GET /workflow/events/recent`, SSE `/api/workflow/events/stream` | `WorkflowView` — status cards (`overview.tsx`), filters, live `EventTimeline`, pipeline panels: telemetry, RAG ingestion, RAG query, health, agent (see §19) |
| **Profile** (`/profile`) | Account | `GET /auth/me`, `PATCH /users/me`, `DELETE /api/session/login` | name edit, session/cookie explanation, logout-all |

## 17.2 Query/cache & realtime strategy

- Central keys (`lib/query-keys.ts`); mutations invalidate on success; `useSimulations` polls only while something is running; telemetry windows are anchored at `Date.now()` on range change so paging never shifts.
- SSE: two proxies (`/api/vehicles/{id}/telemetry/stream`, `/api/workflow/events/stream`) pipe backend streams with a cookie-derived bearer (one silent refresh + retry on 401 for telemetry).
- No simulated data anywhere: charts/tables render only stored backend values; missing metrics render `—`.

---

# 18 — Simulation Control

**Backend contract** (`app/api/routes/simulation.py` + `services/simulation_manager.py`):

| Operation | Endpoint | Behaviour |
|---|---|---|
| **Start** | `POST /api/v1/vehicles/{id}/simulation` | 201 + `SimulationStatusResponse`; **409** if already active; **422** invalid scenario/interval/seed; **502** if the process can't spawn; publishes `SIMULATION_START_REQUESTED/STARTED` |
| **Status** | `GET /api/v1/vehicles/{id}/simulation` | No simulator → `stopped` (no special empty case); includes `last_telemetry_at` |
| **Stop** | `DELETE /api/v1/vehicles/{id}/simulation` | Idempotent graceful stop (terminate → 5 s → kill) |
| **Restart** | `POST /api/v1/vehicles/{id}/simulation/restart` | Stop + fresh spawn with new config (e.g. switch scenario) |
| **List** | `GET /api/v1/simulations` | All vehicles the caller can access, paged |

**States:** `stopped | starting | running | stopping | degraded | error`.

**Degraded derivation (server-side, consumed as-is by the frontend):**
- Subscriber not running → **immediate `degraded`** with the message *"Telemetry ingestion is offline: the backend subscriber is not running…"*.
- Fresh spawn gets a **25 s warm-up** (`_STARTUP_BUFFER_SECONDS`) before missing telemetry is a fault.
- After warm-up, a `running` process whose newest DB telemetry is **older than 30 s** (`_STALE_AFTER_SECONDS`) → `degraded` with a message pointing at the MQTT broker and subscriber (or "no telemetry reached the database yet").

**Polling & optimistic updates:** `useSimulations` polls `GET /simulations` at a refetch interval **while any simulation is active** (idle otherwise); start/stop/restart mutations apply optimistic status chips and reconcile on settle; errors surface via `ErrorState` (409 → "already running", 502 → spawn failure).

**Scenario selection & interval:** the start form maps to `SimulationStartRequest{scenario (normal|high_temperature|low_battery|high_engine_load), interval_seconds (0.1–60, default 1.0), seed (≥0, default 42)}` with `extra="forbid"`.

**Process supervision:** entirely backend-side (§8.3) — PID markers, orphan cleanup at startup, log-tailed crash reasons, Windows single-process spawn fix. The browser never handles PIDs.

---

# 19 — Workflow Monitor / Live Observability

## 19.1 Why it exists

The platform's value proposition is *observable* AI + IoT pipelines. The Workflow Monitor exposes **real execution** of the real pipelines (telemetry, RAG ingestion, RAG query, health, agent, simulation) in real time — no fake animations, no persisted event table, PostgreSQL remains the sole source of truth.

## 19.2 Architecture

```
instrumented pipeline code  ──publish_workflow_event()──►  WorkflowEventBus
   (fire-and-forget, never raises)                          │ ring buffer (500)
                                                            ├─► get_recent()  →  GET /workflow/events/recent
                                                            └─► subscribers   →  GET /workflow/events/stream (SSE)
                                                                                    ▲
                                              Next.js proxy /api/workflow/events/stream
                                                                                    ▲
                                                          use-workflow.ts (EventSource + backfill + reconnect)
                                                                                    ▲
                                                     Workflow Monitor page (tabs, filters, timeline)
```

- **Backend:** `workflow_event_bus.py` (bounded, async-safe, non-blocking), `app/schemas/workflow.py` (event model + sanitization), `app/api/routes/workflow.py` (3 endpoints), settings `WORKFLOW_EVENT_BUFFER_SIZE=500`, `WORKFLOW_MAX_SUBSCRIBERS=50`, `WORKFLOW_SSE_HEARTBEAT_SECONDS=15`.
- **Instrumentation points (real boundaries):** simulator start + telemetry generation/publish (simulation manager, publisher), MQTT receive/parse/persist (subscriber), health analysis stages (health monitor), RAG ingestion stages, RAG query stages, agent nodes, subscriber lifecycle (`system`), simulation control API.
- **Frontend:** `types/api.ts` (workflow types), `services/workflow.ts`, `hooks/use-workflow.ts`, SSE proxy route, `components/workflow/*` (9 components: `workflow-view`, `overview`, `filters`, `event-timeline`, `pipeline-telemetry`, `pipeline-rag-ingestion`, `pipeline-rag-query`, `pipeline-health`, `pipeline-agent`), navigation entry "Workflow Monitor".

## 19.3 Tabs & what each shows

| Tab | Pipeline | Stages visualized |
|---|---|---|
| Overview | all | status cards (pipeline activity, subscriber, active simulations, buffer), architecture map |
| Telemetry | `telemetry` | simulator → MQTT publish → broker → receive → parse → persist (with durations, validation-error states) |
| RAG Ingestion | `rag_ingestion` | upload → parse → extract → sections → chunk → embed → store → index → ready |
| RAG Query | `rag_query` | query → embed → vector search → candidates → rerank → context → answer → sources |
| Health | `health` | analysis start → window → sufficiency → baseline → rules → score → confidence → provisional → snapshot |
| Agent | `agent` | request → supervisor → vehicle context → RAG context → reasoning → response → completed (fallback indicators) |
| (+ Simulation) | `simulation` | start/restart/stop requests, process exit |

Filters (workflow type, status, vehicle, document, time) apply to both the live stream and the recent list; the event timeline expands per-event metadata (sanitized).

## 19.4 Faculty demonstration workflow

1. Open **Workflow Monitor** → Overview shows `subscriber_running`, buffer stats.
2. Start a simulation (Simulation Control) → watch `simulation` + `telemetry` events stream: `simulation_start_requested → simulator_started → telemetry_generated → mqtt_published → mqtt_received → telemetry_parsed → telemetry_persisted` with `correlation_id` linking a sample end-to-end.
3. Stop the subscriber (or observe a stale feed) → status flips to `degraded` and `system/subscriber_error` events appear.
4. Upload a document (Admin RAG) → the full ingestion stage chain plays out with durations; re-upload the same file → `ingestion_completed (unchanged)`.
5. Ask a guidance question → `rag_query` chain with candidate/rerank metrics; ask the agent → `agent` chain referencing the same RAG evidence.
6. Let health analysis run → `health` chain including provisional/sufficiency events.
7. Use filters/correlation to prove every event came from a real operation, and note the buffer's bounded, non-persistent design.

---

# 20 — API Reference

**Source of truth:** the live OpenAPI document generated from the current code (`app.openapi()`), verified on 2026-10-08: **31 paths / 40 operations**, all under `/api/v1`.
⚠️ The checked-in snapshot `backend/openapi.json` is **stale** (23 paths / 30 operations — it predates the workflow routes and later additions). Regenerate it or use the live `/docs` UI.

All routes except `GET /health`, `GET /health/db`, `POST /auth/{register,login,refresh,logout}`, `GET /` require a **Bearer access token**. `*admin*` rows additionally require `role=admin`.

## 20.1 Authentication

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| POST | `/auth/register` | Create account (role always `user`); rate-limited | none (rate limit) | `RegisterRequest` → user dict, 201 |
| POST | `/auth/login` | Credentials → token pair; 401 for bad email/password alike | none (rate limit) | `LoginRequest` → `TokenResponse` |
| POST | `/auth/refresh` | Rotate refresh token → new pair; reuse ⇒ revoke-all | none (rate limit) | `RefreshRequest` → `TokenResponse` |
| POST | `/auth/logout` | Revoke refresh token (idempotent) | none | `LogoutRequest` → 204 |
| GET | `/auth/me` | Current profile | required | — → `UserResponse` |
| PATCH | `/auth/password` | Change password; revokes all refresh tokens | required | `ChangePasswordRequest` → 204 |

## 20.2 Users

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| GET | `/users/me` | Profile (self-service) | required | — → `UserResponse` |
| PATCH | `/users/me` | Update `full_name` only | required | `UserProfileUpdate` → `UserResponse` |

## 20.3 Vehicles

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| GET | `/vehicles` | List caller's vehicles (`page`, `page_size≤100`) | required | — → `PaginatedResponse[VehicleResponse]` |
| POST | `/vehicles` | Create (unique VIN → 409) | required | `VehicleCreate` → 201 `VehicleResponse` |
| GET | `/vehicles/{vehicle_id}` | Read one (404 if not owner) | required | — → `VehicleResponse` |
| PATCH | `/vehicles/{vehicle_id}` | Update metadata (VIN immutable) | required | `VehicleUpdate` → `VehicleResponse` |
| DELETE | `/vehicles/{vehicle_id}` | Delete (cascades telemetry) | required | — → 204 |

## 20.4 Telemetry

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| POST | `/vehicles/{id}/telemetry` | Store sample (idempotent by `source_event_id`) | required | `TelemetryCreate` → 201 `TelemetryResponse` |
| GET | `/vehicles/{id}/telemetry` | Paged history, newest first, `start_time`/`end_time` (`page_size≤500`) | required | — → `PaginatedResponse[TelemetryResponse]` |
| GET | `/vehicles/{id}/telemetry/stream` | **SSE** live samples (heartbeat `: ping`, `interval_seconds` 0–60 s, default 1.0) | required | — → `text/event-stream` |

## 20.5 Vehicle health

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| POST | `/vehicles/{id}/health/analyze` | Run analysis (`window_minutes` 1–1440), persist snapshot | required | — → `HealthContextResponse` |
| GET | `/vehicles/{id}/health` | Latest context (404 if none) | required | — → `HealthContextResponse` |
| GET | `/vehicles/{id}/health/history` | Snapshot history (paged, time-filtered) | required | — → `PaginatedResponse[HealthSnapshotItem]` |

## 20.6 Agent

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| POST | `/vehicles/{id}/agent/query` | Natural-language question → structured diagnosis (LLM) | required | `AgentQueryRequest` → `DiagnosisResponse` |
| POST | `/vehicles/{id}/agent/events/critical` | Critical-event diagnosis (5 min dedup, may skip LLM) | required | `CriticalEventRequest` → `DiagnosisResponse` |
| GET | `/vehicles/{id}/agent/dashboard` | Health + latest diagnosis + age (**no LLM**) | required | — → `DashboardResponse` |
| GET | `/vehicles/{id}/agent/diagnoses` | Paged history | required | — → `PaginatedResponse[AgentDiagnosisItem]` |
| GET | `/vehicles/{id}/agent/diagnoses/latest` | Most recent (404 if none) | required | — → `DiagnosisResponse` |

## 20.7 Simulation

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| POST | `/vehicles/{id}/simulation` | Start simulator (409 active, 422 invalid, 502 spawn) | required | `SimulationStartRequest` → 201 `SimulationStatusResponse` |
| GET | `/vehicles/{id}/simulation` | Status incl. `degraded` derivation | required | — → `SimulationStatusResponse` |
| DELETE | `/vehicles/{id}/simulation` | Stop (idempotent) | required | — → `SimulationStatusResponse` |
| POST | `/vehicles/{id}/simulation/restart` | Restart with new config | required | `SimulationStartRequest` → `SimulationStatusResponse` |
| GET | `/simulations` | All accessible vehicles' statuses | required | — → `PaginatedResponse[SimulationStatusResponse]` |

## 20.8 RAG & corpus administration

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| GET | `/rag/health` | Diagnostics (enabled, pgvector, adapters, corpus counts) | **admin** | — → `RAGHealthResponse` |
| GET | `/rag/search` | Evidence search (`q` 1–500, `make`, `model`, `year`, `top_k` 1–20) — no LLM | required | — → `RAGSearchResult` (503 if RAG disabled) |
| POST | `/admin/rag/documents` | Multipart upload → full ingestion (413 >50 MB, 400 bad ext, 422 ingest failure, 503 pgvector missing) | **admin** | file + `AdminRagDocumentUploadForm` → 201 `AdminRagUploadResponse` |
| GET | `/admin/rag/documents` | Paged corpus with filters (make/model/year/canonical/status) | **admin** | — → `PaginatedResponse[RAGDocumentSummary]` |
| GET | `/admin/rag/documents/{document_id}` | Detail + immutable version history | **admin** | — → `AdminRagDocumentDetailResponse` |
| DELETE | `/admin/rag/documents/{document_id}` | Delete document + versions + chunks | **admin** | — → 204 |

## 20.9 Workflow (observability)

| Method | Path | Purpose | Auth | Request → Response |
|---|---|---|---|---|
| GET | `/workflow/events/recent` | Paged buffer, newest first; filters `workflow, stage, status, vehicle_id, document_id, correlation_id, since, until`, `limit` 1–500 (100), `offset` | required | — → `WorkflowRecentResponse` |
| GET | `/workflow/events/stream` | **SSE** live events, 15 s heartbeats; filters `workflow, status, vehicle_id, document_id` | required | — → `text/event-stream` |
| GET | `/workflow/status` | Pipeline liveness + buffer stats | required | — → `WorkflowStatusResponse` |

## 20.10 Health (service)

| Method | Path | Purpose | Auth | Response |
|---|---|---|---|---|
| GET | `/health` | Liveness, no DB | none | `{"status":"ok","service":"digital-twin-api"}` |
| GET | `/health/db` | `SELECT 1` reachability | none | `HealthDBResponse` (503 `degraded` when down) |
| GET | `/` | Service info (hidden from schema) | none | `{"service","docs"}` |

## 20.11 Important error semantics

400 upload validation · 401 unauthenticated/expired/tampered · 403 non-admin · 404 not found **or not owned** · 409 duplicate VIN / simulation already active / duplicate email · 413 upload too large · 422 validation (FastAPI envelope) · 429 rate limit (+`Retry-After`) · 500 internal/config · 502 LLM provider, simulation spawn, RAG ingest failure · 503 DB down / RAG disabled / LLM rate-limited / pgvector missing · 504 LLM timeout.

---

# 21 — Environment Variables

> No real secrets are listed. Placeholders only. Backend reads `backend/.env` (documented in `.env.example`); frontend reads `frontend/.env.local`.

## 21.1 Backend (`backend/.env.example`)

| Variable | Purpose | Required? | Example / default | Sensitive |
|---|---|---|---|---|
| `APP_NAME` | Service name | no | `Digital Twin API` | no |
| `APP_ENV` | Environment (`development/test/production`) | no | `development` | no |
| `DEBUG` | Debug logging | no | `true` | no |
| `API_V1_PREFIX` | Route prefix | no | `/api/v1` | no |
| **`DATABASE_URL`** | Asyncpg connection string | **yes** | `postgresql+asyncpg://postgres:postgres@localhost:5432/digital_twin` (Supabase: `postgresql+asyncpg://postgres.<ref>:<password>@db.<ref>.supabase.co:5432/postgres?ssl=require`) | **yes** (contains password) |
| `CORS_ORIGINS` | JSON list of allowed origins | yes (for UI) | `["http://localhost:3000","http://localhost:8000"]` | no |
| `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` | Broker address | yes for telemetry | `localhost` / `1883` | no |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | Broker credentials (blank = anonymous) | local no / Docker yes | `` / `` | **yes** |
| `MQTT_CLIENT_ID` | Override subscriber id | no | `dtwin-sub-…` | no |
| `MQTT_QOS` / `MQTT_TOPIC_PREFIX` / `MQTT_KEEPALIVE` | Publish/subscribe tuning | no | `1` / `vehicles` / `60` | no |
| `MQTT_RECONNECT_MAX_SECONDS` / `MQTT_MESSAGE_RETRY_ATTEMPTS` | Resilience | no | `30` / `3` | no |
| `SIMULATOR_VEHICLE_ID` | Standalone simulator target | **for standalone sim** | `11111111-2222-4333-8444-555555555555` | no |
| `SIMULATOR_INTERVAL_SECONDS` / `SIMULATOR_SCENARIO` / `SIMULATOR_SEED` / `SIMULATOR_CRUISE_SPEED` | Simulator behaviour | no | `1.0` / `normal` / `42` / `60.0` | no |
| `HEALTH_ANALYSIS_WINDOW_MINUTES` | Analysis window | no | `15` | no |
| `HEALTH_MINIMUM_SAMPLES` | Sufficiency threshold | no | `10` | no |
| `HEALTH_EXPECTED_INTERVAL_SECONDS` | Expected sample rate | no | `1.0` | no |
| `HEALTH_BASELINE_WINDOW_MINUTES` / `HEALTH_BASELINE_MINIMUM_SAMPLES` | Baseline history | no | `360` / `5` | no |
| `HEALTH_MONITOR_ENABLED` / `_INTERVAL_SECONDS` / `_MIN_SECONDS` / `_MAX_VEHICLES` | Background monitor | no | `true` / `10.0` / `60.0` / `25` | no |
| `LLM_PRIMARY_PROVIDER` / `LLM_FALLBACK_PROVIDER` | Provider chain | yes for agent | `openrouter` / `groq` | no |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | Primary LLM creds | yes (for primary) | `<your-key>` / `openai/gpt-4o-mini` | **yes** |
| `GROQ_API_KEY` / `GROQ_MODEL` | Fallback LLM creds | optional | `<your-key>` / `llama-3.3-70b-versatile` | **yes** |
| `LLM_REQUEST_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` / `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` / `LLM_CONTEXT_MAX_CHARS` | LLM tuning | no | `60` / `2` / `0.1` / `1500` / `24000` | no |
| `AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS` | Critical dedup | no | `300` | no |
| `RUN_LLM_SMOKE_TEST` | Enable smoke script | no | `false` | no |
| **`JWT_SECRET`** | HS256 signing key (≥32 chars outside dev; denylist of weak values rejected) | **yes (non-dev)** | `<random-64-char-string>` | **yes** |
| `JWT_ALGORITHM` | Signing algorithm | no | `HS256` | no |
| `AUTH_ACCESS_TOKEN_MINUTES` / `AUTH_REFRESH_TOKEN_DAYS` | Token lifetimes | no | `20` / `30` | no |
| `AUTH_RATE_LIMIT_ENABLED` / `_MAX_REQUESTS` / `_WINDOW_SECONDS` | Login/register/refresh limiter | no | `true` / `10` / `60` | no |
| `RAG_ENABLED` | Master RAG switch | no | `true` | no |
| `RAG_EMBEDDING_MODEL` / `RAG_EMBEDDING_DIMENSION` | Embedder (`stub` for tests) | no | `BAAI/bge-m3` / `1024` (fixed by schema) | no |
| `RAG_EMBEDDING_DEVICE` / `_BATCH_SIZE` / `_MAX_LENGTH` / `_NORMALIZE` | Embedder tuning | no | `auto` / `16` / `1024` / `true` | no |
| `RAG_RERANKER_MODEL` / `_DEVICE` / `_MAX_LENGTH` | Reranker | no | `BAAI/bge-reranker-v2-m3` / `auto` / `512` | no |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | Chunking | no | `800` / `120` | no |
| `RAG_RETRIEVAL_TOP_K` / `RAG_RERANK_TOP_K` / `RAG_FINAL_TOP_K` | Retrieval depth | no | `25` (unused) / `30` / `5` | no |
| `RAG_HYBRID_ALPHA` / `RAG_MIN_RERANK_SCORE` / `RAG_MIN_SCORE` | Scoring | no | `0.6` / `0.2` / `0.0` | no |
| `RAG_MAX_DOCUMENT_BYTES` / `_PAGES` / `RAG_MAX_CHUNKS` | Ingestion limits | no | `52428800` / `2000` / `20000` | no |
| `RAG_DOCUMENT_ROOTS` | Allowed document roots | no | `["data/documents"]` | no |
| `RAG_QUERY_MAX_CHARS` / `RAG_EVIDENCE_MAX_CHARS` | Truncation | no | `500` / `1800` | no |
| `RAG_MAX_UPLOAD_SIZE_MB` | API upload ceiling | no | `50` | no |
| `SIMULATION_STARTUP_GRACE_SECONDS` / `SIMULATION_STOP_TIMEOUT_SECONDS` / `SIMULATION_RUNTIME_DIR` | Process control | no | `3.0` / `5.0` / `<temp>/dtwin-simulations` | no |
| `WORKFLOW_EVENT_BUFFER_SIZE` / `WORKFLOW_MAX_SUBSCRIBERS` / `WORKFLOW_SSE_HEARTBEAT_SECONDS` | Observability bus | no | `500` (50–5000) / `50` (5–200) / `15` (5–120) | no |
| `TEST_DATABASE_URL` | Test DB (tests only; refuses `supabase`/`pooler` hosts) | for tests | `postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_test` | **yes** |

## 21.2 Frontend (`frontend/.env.example`)

| Variable | Purpose | Required? | Example | Sensitive |
|---|---|---|---|---|
| `BACKEND_API_URL` | Server-side base URL for session proxy | yes | `http://localhost:8000/api/v1` | no |
| `NEXT_PUBLIC_API_URL` | Browser base URL (must be in backend `CORS_ORIGINS`) | yes | `http://localhost:8000/api/v1` | no |

**Grouped minimums:** *database* → `DATABASE_URL` (+ pgvector extension). *JWT* → `JWT_SECRET` (+ `JWT_ALGORITHM`). *MQTT* → host/port (+ credentials for Docker). *LLM* → provider pair + keys/models. *RAG* → `RAG_ENABLED` + models (defaults fine). *Frontend* → both URLs. *Development* → everything else has working defaults.

---

# 22 — Installation (Windows PowerShell)

Prerequisites: **Python 3.12+** (this machine runs 3.14), **Node.js 20+ (CI uses Node 24)**, **Git**, PostgreSQL 16+ with pgvector (or Supabase; this machine runs 17.10), Mosquitto (for live telemetry).

```powershell
git clone <repo-url> "Digital Twin"
cd "Digital Twin"
```

## 22.1 Backend venv + dependencies

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"        # core + pytest/ruff/httpx  (make install does the same)
pip install -e ".[rag]"        # optional but required for real document parsing & embeddings
# extras: docling, sentence-transformers, torch, transformers, scipy  (large download)
cd ..
```

## 22.2 Frontend dependencies

```powershell
cd frontend
npm ci            # or: npm install
cd ..
```

## 22.3 Environment files

```powershell
Copy-Item backend\.env.example backend\.env       # then edit DATABASE_URL, JWT_SECRET, keys
Copy-Item frontend\.env.example frontend\.env.local
```

> If PowerShell blocks script execution for the helper scripts: `Set-ExecutionPolicy -Scope Process RemoteSigned`.

---

# 23 — Database Setup

**Option A — local Docker Postgres:**

```powershell
cd backend
docker compose up -d postgres      # pgvector/pgvector:pg16, port 5432
```

**Option B — Supabase:** create a project and put its pooled connection string in `DATABASE_URL` (…`ssl=require`). Ensure the `vector` extension is enabled for the database (Supabase: Database → Extensions → `vector`).

**Migrations:**

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head        # or: make migrate   (head = b7d9f1e2a3c4)
```

**Verification:**

```powershell
python -m scripts.verify_pgvector   # extension, HNSW index, operators   (or: make db-verify)
python -m scripts.check_db          # independent asyncpg connectivity probe
make db-current                     # alembic current — shows b7d9f1e2a3c4 (head)
python -m scripts.seed_demo_vehicle # optional demo vehicle 11111111-2222-4333-8444-555555555555
```

**Other DB tooling:** `make db-history`, `make db-heads`, `make migration MESSAGE="…"`, `make db-reset-local` (`scripts/reset_local_db.py --yes` — **hard-refuses non-local targets**).

**Tests** create/drop their own database `digital_twin_test` (`TEST_DATABASE_URL`; the conftest raises if the host looks like Supabase/pooler — destructive fixtures must never hit hosted DBs).

---

# 24 — Mosquitto Setup

**Install (Windows):** download the Mosquitto installer from the Eclipse Foundation and install to `C:\Program Files\Mosquitto` (adds `mosquitto.exe` to PATH or the standard location the scripts probe). The repository's own configs live in `backend/infrastructure/mosquitto/`:

| File | Use |
|---|---|
| `mosquitto.local.conf` | **Local dev**: `listener 1883 127.0.0.1`, `allow_anonymous true`, persistence under `./infrastructure/mosquitto/persist/` |
| `mosquitto.conf` | **Docker**: port 1883, `allow_anonymous false`, generated password file, persistence, ACL file |
| `mosquitto.acl` | `user mqtt → topic readwrite vehicles/#` |

**Start:**

```powershell
.\scripts\dt-start.ps1                 # starts broker + api + subscriber together
# or broker only:
make mqtt-broker                       # backend/ — mosquitto -c infrastructure/mosquitto/mosquitto.local.conf
# or Docker:
docker compose up -d mosquitto          # backend/ — credentials MQTT_USERNAME/MQTT_PASSWORD (default mqtt/mqtt)
```

**How it fits:** simulator publishes `vehicles/{id}/telemetry` + `/status` → broker → backend subscriber (`vehicles/+/telemetry`, QoS 1) → PostgreSQL. The subscriber is **supervised by the backend lifespan** when the API runs (§9.3); `dt-start.ps1` also starts it explicitly as a tracked process — the supervisor detects an already-running healthy instance via its PID marker and does not double-spawn.

---

# 25 — Running the System

Normal development startup (three terminals + simulator via UI):

**Terminal 1 — Backend** (spawns/subscribes MQTT subscriber itself):

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
# equivalent: make dev
```

**Terminal 2 — Frontend:**

```powershell
cd frontend
npm run dev
```

**Terminal 3 — Mosquitto** (skip if using `dt-start.ps1` or Docker):

```powershell
make mqtt-broker      # from backend/
```

**Simulator:** *not started manually* in the normal flow — start it from the **Simulation Control** page (or `POST /api/v1/vehicles/{id}/simulation`); the backend supervises the child process. For a standalone run: `python -m simulator.main` with `SIMULATOR_VEHICLE_ID` set.

**One-shot alternative for the local stack (broker + API + subscriber):**

```powershell
.\scripts\dt-start.ps1      # hidden background processes under %TEMP%\dtwin
.\scripts\dt-status.ps1     # component status + port probes + /api/v1/health
.\scripts\dt-stop.ps1       # stop tracked components
```

**Who supervises what:**
- **Backend → MQTT subscriber:** FastAPI lifespan `ensure_running()` at startup, auto-restart with backoff, shutdown on exit.
- **Backend → simulator processes:** `SimulationManager` (start/stop/restart/status, PID markers, stale cleanup) driven by Simulation Control.
- **dt-*.ps1 → broker/api/subscriber:** PID-tracked background processes for local development (does not manage simulators).

---

# 26 — How to Use the System

1. **Register/login.** Open `http://localhost:3000` → **Register** (email + password ≥ 8 chars). The session is stored in httpOnly cookies; you are redirected to the dashboard.
2. **Add a vehicle.** **Vehicles → Add vehicle** (VIN 5–50 chars, make, model, year, optional engine). *Or* seed the demo vehicle: `python -m scripts.seed_demo_vehicle` (ID `11111111-2222-4333-8444-555555555555`).
3. **Start the simulation.** **Simulation Control** → choose vehicle → scenario (`normal`, `high_temperature`, `low_battery`, `high_engine_load`) → interval (e.g. 1 s) → **Start**. Status shows `starting → running` (or `degraded` if the pipeline is down).
4. **Observe telemetry.** Vehicle → **Telemetry** tab: live feed card (SSE, stale indicator after 10 s, 5 s polling fallback) + explorer with time ranges (15 m–7 d), metric chips and the raw-sample table.
5. **Open the health dashboard.** Vehicle → **Health** → **Analyze** (15-min window default). You get score, status (`healthy/attention/critical/limited_data/no_data`), confidence, findings with observed-vs-threshold, trends/baselines, and a history of immutable snapshots.
6. **View the health snapshot.** **History** tab lists every snapshot (score/status/time); each is a frozen record of one analysis.
7. **Open Manufacturer Guidance.** **Guidance** page → query with optional make/model/year filters → evidence chunks with dense/lexical/hybrid/rerank scores and source provenance (filename, section, pages).
8. **Ask a question.** Vehicle → **Diagnosis** → type a question (≥ 3 chars) → the agent returns summary, possible causes with likelihood, prioritized actions, evidence, severity/confidence rationale, and manufacturer guidance with numbered citations. The provider/model/fallback banner shows which LLM answered.
9. **Inspect source documents.** (Admin account) **Admin RAG**: health tab (corpus counts, pgvector status), upload (drag & drop, 17 formats), documents list with per-version history (content hash, parser, chunk count, status) and delete.
10. **Open Workflow Monitor.** **Workflow Monitor** page → Overview shows pipeline liveness + buffer stats.
11. **Observe the telemetry workflow.** With a simulation running, the **Telemetry** tab streams `simulator_started → mqtt_published → mqtt_received → telemetry_parsed → telemetry_persisted` live, with durations and correlation ids.
12. **Observe the RAG workflow.** Upload a document → **RAG Ingestion** tab plays the stage chain; ask a question → **RAG Query** tab shows embed → search → rerank → answer → sources with real metrics.

---

# 27 — Faculty Demonstration Script

> **Setup before the demo (5 min):** `.\scripts\dt-status.ps1` (or start terminals per §25) → confirm `/api/v1/health` ok, `dt-status` shows mosquitto/api/subscriber `running`, browser logged in, demo vehicle present. Have two browser tabs: app + Workflow Monitor.

### DEMO 1 — Architecture (90 s)
Show the §2.1 diagram (or Workflow Monitor → Overview architecture card). Say: *"Next.js frontend, FastAPI backend, PostgreSQL+pgvector, Mosquitto broker; the simulator publishes real MQTT messages; the backend supervises the subscriber and simulator processes; observability events are in-memory only."*

### DEMO 2 — Document ingestion (90 s)
**Admin RAG → Upload** → pick a manual PDF → metadata (canonical, make/model/year) → Upload. Watch `INGESTED` with chunk count. Explain: *parse → hash → version → structure-aware chunking (800/120) → BGE-M3 1024-dim → pgvector HNSW*. **Re-upload the same file** → `unchanged` (idempotent by content hash).

### DEMO 3 — Ask a manufacturer question (90 s)
**Guidance** → query e.g. *"What are the coolant temperature limits?"* + make/model/year → show top-5 scored chunks with page/section provenance. Point out: *"no LLM in search — this is pure hybrid retrieval + rerank."*

### DEMO 4 — Start one vehicle (60 s)
**Simulation Control** → vehicle → scenario `high_temperature`, interval 1 s → **Start** → status `running`. Show 409 behavior by starting twice (second start rejected).

### DEMO 5 — Show telemetry generation (60 s)
Vehicle → **Telemetry** → live feed updates every second; range = 15 min; open **Workflow Monitor → Telemetry** to see `telemetry_generated → mqtt_published` per sample with `duration_ms`.

### DEMO 6 — Show MQTT flow (60 s)
Explain the path while events stream: *simulator → `vehicles/{id}/telemetry` QoS 1 → Mosquitto → subscriber (`vehicles/+/telemetry`) → parse/validate → persist*. In Workflow Monitor point at `mqtt_received` and `telemetry_parsed` stages; mention retry (3×) and validation-error events.

### DEMO 7 — Show database persistence (60 s)
Run `python -m scripts.check_db` in a terminal (or query `telemetry_records` count) → rows increase each second. Note the idempotency column `source_event_id` and the partial unique index.

### DEMO 8 — Show health calculation (90 s)
Vehicle → **Health → Analyze**. Walk the result: window (15 min), sample count (show **limited_data → provisional** first if the sim just started), rules fired (e.g. `COOLANT_TEMP_HIGH` in `high_temperature` scenario), score = 100 − penalties, status thresholds 80/60, confidence formula. Show **Workflow Monitor → Health** stages (`data_sufficiency_evaluated → rules_evaluated → health_score_calculated`).

### DEMO 9 — Show health snapshot (60 s)
**History** tab: each row is an immutable snapshot; re-run Analyze → a *new* row appears, old rows untouched. Explain why (auditability, JSONB context).

### DEMO 10 — Agent workflow (90 s)
Vehicle → **Diagnosis** → ask *"Why is my engine temperature high and what should I check?"* Show structured answer: causes + likelihood, prioritized actions, evidence traced to real rule findings, severity clamped to rule severity, citations with sources, provider/model (or `mock` offline), latency/tokens. Trigger a **critical** analysis to show the automatic critical-event escalation (5-min cooldown dedup on repeat).

### DEMO 11 — Workflow Monitor (2 min)
Overview → status cards; then tab-walk: Telemetry (live chain), RAG Ingestion (from Demo 2), RAG Query (from Demo 3/10), Health (from Demo 8), Agent (from Demo 10). Apply a **filter** (`workflow=rag_query`) and a **correlation id** to trace one operation. Close with the design notes: ring buffer 500, non-blocking publish, SSE + recent endpoints, **sanitized metadata** (no secrets/chain-of-thought), no persistent event table.

**Total ≈ 12 minutes.**

---

# 28 — Testing

## 28.1 Test suite inventory

**Backend — 51 test files under `backend/tests/`** (grouped: `api` 9, `services` 7, `rag` 8, `mqtt` 8, `agent` 6, `intelligence` 6, `repositories` 1, `core` 4, `simulator` 2 + `conftest.py`):

| Area | Files (representative) | Covers |
|---|---|---|
| API | `test_auth`, `test_auth_rate_limit`, `test_authorization`, `test_vehicles`, `test_telemetry`, `test_telemetry_stream`, `test_vehicle_health`, `test_simulation`, `test_health` | HTTP contracts, ownership matrix, SSE, degraded-state derivation (25 tests in simulation alone) |
| Services | `test_telemetry_service`, `test_vehicle_service`, `test_vehicle_health_service`, `test_health_monitor_service`, `test_simulation_manager`, `test_subscriber_manager`, `test_workflow_event_bus` | idempotent ingest, snapshot semantics, monitor escalation, process supervision, **event bus (ring buffer/subscribers/SSE/clear/close)** |
| RAG | `test_rag_unit`, `test_admin_api`, `test_admin_documents_api(+_integration)`, `test_rag_service_integration`, `test_rag_repository_integration`, `test_agent_rag_units`, `test_agent_rag_integration` | chunking, query planning, scope tiers, upload API, hybrid round-trips (pgvector-gated), agent↔RAG glue |
| MQTT | `test_topics`, `test_mqtt_schemas`, `test_parser`, `test_publisher`, `test_subscriber`, `test_client_id`, `test_mqtt_e2e`, `test_simulation_mqtt_e2e` | topics, envelope validation, parsing, persistence retries; E2E tests are marker-gated `mqtt_e2e` |
| Agent | `test_agent_settings`, `test_providers`, `test_determinism`, `test_llm_service`, `test_api`, `test_graph_cache` | settings bounds, provider taxonomy, grounding/clamping, retry/fallback routing, HTTP contract, graph LRU |
| Intelligence | `test_statistics`, `test_trends`, `test_baselines`, `test_rules`, `test_scoring`, `test_engine` | statistics, OLS trends, MAD baselines, all rules, penalties/statuses, sufficiency branches |
| Core/config | `test_config`, `test_rate_limit`, `test_security`, `test_security_settings` | settings defaults/bounds, sliding-window limiter, bcrypt contract, JWT-secret policy |
| Simulator | `test_simulator_config`, `test_telemetry_generator` | settings mapping, determinism by seed, state machine, physical invariants, fault scenarios |

**Test infrastructure (`tests/conftest.py`):** real FastAPI app through `httpx.ASGITransport` (no live server), **real PostgreSQL test database** (`TEST_DATABASE_URL`, default `…127.0.0.1:5432/digital_twin_test`; refuses hosts containing `supabase`/`pooler`), forced env before app import (`RAG_ENABLED=false`, monitor off, rate limit off, fixed test JWT secret), `clean_db` truncation around each test, pgvector-capability probe (`supports_pgvector()` gates RAG integration tests), fixtures `auth_user/auth_client/admin_user/admin_client/other_user/sample_vehicle`.

**Frontend — 12 test files / 92 tests:** `lib/api-client`, `lib/api-error`, `hooks/use-auth-guard`, `hooks/use-telemetry-stream`, `hooks/use-vehicle-data`, `components/auth/login-form`, `components/vehicles/vehicle-form-dialog`, `components/vehicles/vehicle-diagnosis-view`, `components/simulations/simulations-view`, `components/telemetry/live-telemetry-feed`, `components/rag/rag-search-view`, `components/admin/admin-rag-view`. Harness: Vitest + jsdom + Testing Library + `renderWithProviders`.

**Integration/E2E:** `tests/mqtt/test_mqtt_e2e.py` (real broker → subscriber → PostgreSQL; two-subscriber session-takeover check) and `test_simulation_mqtt_e2e.py` (SimulationManager spawns a real simulator streaming into PostgreSQL) — both marked `mqtt_e2e` and **deselected by default**.

## 28.2 Commands (project-exact)

```powershell
# backend (from backend/, venv active)
pytest                       # addopts: -q -m "not mqtt_e2e"
pytest -m mqtt_e2e           # requires running broker — or: make mqtt-test
ruff check .                 # make lint
ruff format --check .        # CI formatting gate
alembic upgrade head         # make migrate
python -m scripts.verify_pgvector

# frontend (from frontend/)
npm run typecheck
npm run lint
npm test                     # vitest run
npm run test:watch
```

## 28.3 Verified results (run 2026-10-08)

| Suite | Command | Result |
|---|---|---|
| Backend | `python -m pytest --tb=no` | **1 failed, 541 passed, 10 skipped, 4 deselected** (5 m 45 s) |
| Backend lint | `python -m ruff check .` | **All checks passed!** |
| Frontend | `npm test` | **92 passed (12 files)**, 5.5 s |
| Frontend | `npm run typecheck` | **clean (exit 0, no errors)** |
| Frontend | `npm run lint` | **clean (exit 0, no errors)** |

**The single failing test (pre-existing, unrelated to Workflow Monitor):**
`tests/core/test_config.py::test_health_monitor_defaults` asserts `Settings().health_monitor_interval_seconds == 30.0`, but the implemented default in `app/core/config.py` is **`10.0`**. The test expectation is stale (the code and `.env.example` agree on `10.0`). Documented here as an open, honest discrepancy — fixing it would be a one-line test change and is out of scope for this documentation task.

**Skipped/deselected:** `10 skipped` = environment-gated (pgvector/RAG unavailable in this run); `4 deselected` = `mqtt_e2e` marker (opt-in with `pytest -m mqtt_e2e`).

**CI parity:** `.github/workflows/ci.yml` runs the same gates (ruff, format check, migrations, pgvector verify, pytest against a fresh pgvector service; frontend typecheck + lint + vitest on Node 24).

---

# 29 — Troubleshooting

## 29.1 Common issues

| # | Symptom | Supported fix (from the implementation) |
|---|---|---|
| 1 | **Port 8000 already in use** | `.\scripts\dt-status.ps1` probes the API port; stop the old instance (`dt-stop.ps1` / Task Manager) or start with another port (`dt-start.ps1 -ApiPort 8001`, remember to update `NEXT_PUBLIC_API_URL`) |
| 2 | **Mosquitto not running** | `dt-start.ps1` warns if the binary/config is missing (`$env:DT_MOSQUITTO_EXE` override, `%ProgramFiles%\mosquitto\mosquitto.exe`, or PATH); `make mqtt-broker`; or `docker compose up mosquitto`. Subscriber reconnects with backoff up to 30 s |
| 3 | **MQTT subscriber not running** | The backend **auto-starts it at API startup** (`ensure_running`) and auto-restarts with 1→16 s backoff; check `subscriber.log` and `subscriber.pid` under the runtime dir; `GET /workflow/status` → `subscriber_running`; Simulation Control reports `degraded` with an explicit message |
| 4 | **No fresh telemetry** | `degraded` reason tells you: *"Simulator is running but no telemetry has reached the database yet. Check the MQTT broker and the backend subscriber."* Verify broker (§24), subscriber (item 3), vehicle UUID matches `SIMULATOR_VEHICLE_ID`, and clock/timezone (envelope requires tz-aware timestamps) |
| 5 | **Stale simulation status** | 25 s warm-up after start; after that, newest telemetry older than 30 s → `degraded`. Check logs `{runtime}/{vehicle_id}.log`; restart via **Simulation Control → Restart** |
| 6 | **Duplicate simulator process** | Prevented by per-vehicle conflict (409), PID markers, and `cleanup_stale()` orphan kill at API startup; if a PID file survives a crash, restarting the API reclaims it (it never kills PIDs owned by a *live* different backend) |
| 7 | **PostgreSQL/Supabase connection failure** | `GET /api/v1/health/db` returns 503 when unreachable; startup logs a warning but keeps serving; verify `DATABASE_URL` (dt-start prints the classified target LOCAL/SUPABASE/REMOTE without credentials); `python -m scripts.check_db` |
| 8 | **pgvector extension problem** | `alembic upgrade head` prints actionable errors if `CREATE EXTENSION vector` fails; `python -m scripts.verify_pgvector` probes extension/HNSW; runtime calls raise `RAGVectorUnavailableError` → RAG endpoints 503; migration `b7d9f1e2a3c4` re-creates the HNSW index and verifies the `hnsw` access method |
| 9 | **RAG dependency issues** | RAG deps are an optional extra (`pip install -e ".[rag]"`); without them or with `RAG_ENABLED=false`, the system runs and RAG degrades gracefully (health shows disabled; search 503; agent skips RAG). Tests use `stub` adapters so the suite runs without torch |
| 10 | **LLM provider unavailable** | Fallback: primary → retries/backoff → `LLM_FALLBACK_PROVIDER` (default groq) for timeout/rate-limit/connection/server/unknown/auth; mock provider for offline. HTTP mapping: 504 timeout, 503 rate-limit, 502 other provider errors, 500 config (`agent_configuration_error`). Set both key pairs in `.env` |
| 11 | **Frontend cannot reach backend** | Check `NEXT_PUBLIC_API_URL` (frontend) matches the running API and is listed in backend `CORS_ORIGINS`; session proxy uses server-side `BACKEND_API_URL` |
| 12 | **CORS problems** | Only middleware is CORS with `allow_origins=settings.cors_origins` (JSON list, e.g. `["http://localhost:3000","http://localhost:8000"]`), credentials allowed; mismatched origin → browser blocks (network error with status 0 → `ErrorState` offline preset) |
| 13 | **Alembic migration problems** | URL comes from app settings, not `alembic.ini` — fix `DATABASE_URL`; `%` in passwords is escaped automatically; `alembic current` should show `b7d9f1e2a3c4 (head)`; `make db-history` to inspect |
| 14 | **Windows venv activation / spawn issues** | `.\.venv\Scripts\Activate.ps1` (execution policy: `Set-ExecutionPolicy -Scope Process RemoteSigned`). The historic **venv launcher double-spawn** is fixed: `SimulationManager`/`SubscriberSupervisor` execute the base interpreter with `__PYVENV_LAUNCHER__` set, so exactly one real process starts (see `P0_SIMULATION_CONTROL_FINAL_REPORT.md`) |

## 29.2 Workflow Monitor-specific

- **No events?** The buffer only fills when real operations run — start a simulation, upload a document, ask a question. Also check `GET /workflow/status`.
- **Stream disconnects:** SSE heartbeat is 15 s; the hook reconnects with backoff and backfills via `/workflow/events/recent`. Browser proxies: use the Next.js `/api/workflow/events/stream` URL, never the backend URL directly (cookie auth).
- **Events "disappearing":** by design — the ring buffer keeps only the newest `WORKFLOW_EVENT_BUFFER_SIZE` (500) events and is cleared on restart; `clear()` only clears the view.

## 29.3 HTTP error mapping (evidence from `app/main.py`)

| Exception | Status | Body |
|---|---|---|
| `NotFoundError` | 404 | `{"detail":"<Resource> not found"}` |
| `ConflictError` | 409 | `{"detail": …}` |
| `AuthenticationError` | 401 | `{"detail": …}` |
| `AuthorizationError` | 403 | `{"detail": …}` |
| `RateLimitError` | 429 | `{"detail": …}` + `Retry-After` |
| `SimulationError` | 502 | `{"detail": …}` |
| `RAGUploadValidationError` / `RAGUploadTooLargeError` / `RAGIngestionFailureError` / `RAGDocumentUnavailableError` | 400 / 413 / 422 / 503 | `{"detail": …}` |
| `LLMTimeoutError` / `LLMRateLimitError` / other `LLMProvider*` / `StructuredOutputError` | 504 / 503 / 502 | `{"detail": …, "error_code": …}` |
| `AgentConfigurationError` / `GraphExecutionError` / `DatabaseError` / `AppError` / catch-all | 500 | sanitized `{"detail": …}` |
| `RequestValidationError` | 422 | sanitized list (non-JSON `ctx`/`input` stripped) |

---

# 30 — Security

## 30.1 Authentication & session security

| Control | Implementation (evidence) |
|---|---|
| Password storage | **bcrypt** (`app/core/security.py`), 72-byte hard cap enforced by schema validator; `verify_password` never raises on malformed hashes |
| Password policy | 8–72 chars (`auth_password_min_length`/`auth_password_max_length`); rejected over-length input returns 422 with the byte-limit message |
| JWT | **HS256** (`JWT_ALGORITHM`), claims `sub/type/iat/exp`; access lifetime 20 min default |
| JWT secret policy | Outside `development`/`local`, `Settings` validator requires ≥ 32 chars and rejects a denylist (`change-me`, `insecure-dev-secret`, `dev-secret`, `jwt-secret`, `secret`, empty). Enforced at startup → fail-fast on weak production config. Verified by `tests/core/test_security_settings.py` |
| Refresh tokens | `secrets.token_urlsafe(48)`; **only SHA-256 hashes stored** (`refresh_tokens.token_hash`, unique index); 30-day expiry |
| Rotation + reuse detection | `AuthService.rotate()` revokes the presented token and issues a fresh pair; **reuse of a revoked token revokes all of the user's tokens** (theft detection). Verified by `tests/api/test_auth.py` |
| Logout / password change | Logout idempotently revokes the refresh token; password change revokes **all** refresh tokens |
| No account probing | Login returns 401 identically for unknown email, bad password, and inactive account |
| Rate limiting | In-process sliding window on `auth:login`, `auth:register`, `auth:refresh` — default **10 requests / 60 s per client** (leftmost `X-Forwarded-For`), `Retry-After` header on 429 |
| Cookie model (frontend) | `dt_at` (access) and `dt_rt` (refresh) are **httpOnly**; `dt_rt` scoped to `path=/api/session`; `sameSite=lax`; `secure` in production. The refresh cookie **never reaches browser JavaScript** — access token lives in memory only (`session-store.ts`) |

## 30.2 Authorization

- **Ownership gate below the router:** `ensure_vehicle_access` (`app/services/vehicle_access.py`) is invoked in every vehicle-scoped service path so a mis-wired endpoint cannot bypass it. Non-owners receive **404, not 403** — no resource-existence leak.
- **Role gate:** `require_admin` (403) protects `/rag/health` and all `/admin/rag/*` routes; roles are constrained by a DB check constraint (`user|admin`) and re-read from the database on **every** request (`get_current_user`), so privilege changes take effect immediately.
- **Verification:** `tests/api/test_authorization.py` walks the full matrix (401 on all protected routes, owner cross-vehicle, admin any-vehicle, RAG admin-only, `users/me` constraints).

## 30.3 Data-handling security

| Area | Control |
|---|---|
| SQL | All queries go through SQLAlchemy constructs or bound-parameter raw SQL (`app/rag/repository.py` uses `sa.text` with `:params`); no string-built SQL |
| Secrets in logs/errors | Provider error text scrubbed by `_KEY_LIKE_RE` (keys → `***`, 300-char cap); `AppError` messages never contain connection strings; `describe_database_url` redacts credentials; dt-start prints DB **target class** but never credentials |
| Workflow events | `sanitize_metadata()` redacts keys containing `password/api_key/token/secret/credential/authorization/access_token/refresh_token/database_url/db_password/mqtt_password/llm_api_key/openai_key/provider_key/chain_of_thought/reasoning/thought`; truncates strings > 1000 chars; 2048-byte total cap |
| Chain-of-thought | Never stored, emitted, or exposed anywhere in the system (see §14.1) |
| Upload safety | Filename sanitization (no path separators, no `..`, no NUL), extension allow-list (17 extensions), streaming size ceiling 50 MB, temp dirs always removed, UTF-8 validation of text uploads, unknown multipart fields rejected (422) |
| Test isolation | `tests/conftest.py` **raises** if `TEST_DATABASE_URL` host contains `supabase` or `pooler` — destructive fixtures can never touch hosted databases |
| Destructive-script guard | `scripts/reset_local_db.py` / `require_local_database()` hard-refuse non-local targets |
| Transport | Supabase connections use `ssl=require`; Docker Mosquitto uses `allow_anonymous false` + ACL; local Mosquitto binds `127.0.0.1` only |
| CORS | Single explicit origin list from config, credentials enabled; no wildcard + credentials combination |

## 30.4 Dependency posture

Backend runtime deps are pinned by lower bounds in `pyproject.toml`; dev toolchain is pinned exactly in CI (`pytest==9.1.1`, `pytest-asyncio==1.4.0`, `httpx==0.28.1`, `ruff==0.16.8`) so CI verdicts match local ones. Frontend locks via `package-lock.json` and CI `npm ci`. No workflow/persistence layer introduces new third-party services (SSE, ring buffer — stdlib only).

---

# 31 — Limitations

Honest statement of what the current implementation does **not** do.

## 31.1 Architectural / design limitations (by design)

1. **Workflow events are volatile.** The ring buffer (500 events) lives in backend process memory: events are lost on restart, never queryable historically, and capped at the configured size. There is no `workflow_events` table — intentional (live observability only, PostgreSQL stays the sole source of truth).
2. **Single-process assumption.** The event bus, simulation manager, and subscriber supervisor assume **one** backend process. Running uvicorn with multiple workers would give each worker its own buffer and conflicting supervisors (the PID-marker owner check protects against cross-backend kills but not split-brain state).
3. **SSE is not pub/sub across processes.** Subscribers are in-process `asyncio.Queue`s; scale-out would need Redis/Kafka or DB-backed fan-out (not present).
4. **Deterministic health rules, not ML.** Health scoring is a transparent rules + penalties engine (§10). It detects threshold and pattern violations; it does not *predict* failures or learn per-vehicle baselines beyond median/MAD deviation.
5. **Simulator is synthetic.** Six-state driving machine with seeded RNG — physically plausible, not CAN-bus/OBD faithful; no real vehicle integration (`source_type` column anticipates `real`, but no real ingest path exists).
6. **Single LLM fallback hop.** Exactly one fallback provider is configured (`primary → fallback`); no multi-provider cascade or weighted routing.
7. **RAG scope is per-chunk metadata.** Vehicle make/model/year filtering relies on metadata set at upload time; no semantic vehicle-resolution (e.g. VIN → model lookup) in the query path (VINs are stripped, not decoded).
8. **Hybrid search α is global.** `RAG_HYBRID_ALPHA=0.6` applies to every query; no per-query retrieval-weight tuning.
9. **No multi-tenant isolation beyond ownership.** Two-tier roles (`user`/`admin`); no organizations/fleets/teams.
10. **Docling page spans are approximate for plain text** (4400 chars/page heuristic); exact pages only when the parser provides them.

## 31.2 Environmental / operational limitations

11. **Test suite needs local PostgreSQL** (creates `digital_twin_test`). Cannot run green against SQLite or a remote Supabase (deliberately refused). In this documentation run: **1 pre-existing failure** (§28.3), 10 env-gated skips, 4 broker-gated deselections.
12. **Full RAG stack requires heavy optional deps** (`pip install -e ".[rag]"` → torch/docling/sentence-transformers, multi-GB first download) and first-use model loading; tests avoid this via `stub` adapters, so **live embedding/reranking quality is only verified when the extra is installed**.
13. **Real LLM calls require paid API keys**; without them the agent returns 500 `agent_configuration_error` (or use the `mock` provider). Live OpenRouter/Groq behavior is therefore configuration-dependent and not exercised by CI.
14. **Windows-specific process handling** (venv launcher fix, `CREATE_NEW_PROCESS_GROUP`, `ctypes` PID liveness) is code-path-tested but the platform's process semantics differ from POSIX (e.g. `terminate()` = hard kill).
15. **Mosquitto is a manual prerequisite** on Windows (installer or Docker); the backend cannot start the broker itself (dt-start only warns if missing).
16. **Stale `backend/openapi.json` snapshot** — 23 paths vs live 31; the snapshot must be regenerated manually or ignored in favor of the live `/docs`.
17. **Stale docs/tasks:** `tasks/todo.md` still marks frontend Workflow phases `[ ]` although the files are implemented and typecheck/lint/test green; `backend/docs/DIGITAL_TWIN_COMPLETE_SYSTEM_GUIDE.md` and `backend/README.md` predate the frontend and contain superseded details (§33 lists discrepancies).
18. **No automated end-to-end browser tests** (Playwright/Cypress absent); E2E coverage is limited to backend MQTT-marker tests.
19. **Rate limiting is in-process** — resets on restart and does not coordinate across workers.
20. **Observability ≠ monitoring:** no metrics endpoint (Prometheus), no distributed tracing, log correlation is manual (`correlation_id` in events helps but is not propagated into structured app logs).

---

# 32 — Future Enhancements

Prioritized, and explicitly **not implemented today** (each is future work):

## 32.1 Near-term (in-repo trajectories already visible)

1. **Persist workflow events optionally** — an opt-in `workflow_events` table (TTL-partitioned) for post-hoc audit, keeping the live path in-memory.
2. **Commit + review the Workflow Monitor feature** — the working tree holds the complete feature (backend routes/bus/instrumentation, frontend page, event-bus tests) but it is **not yet committed**; remaining items: demo-mode controls, `backend/tests/api/test_workflow.py` (HTTP-level tests for the three endpoints), live acceptance run.
3. **Fix the stale test expectation** `test_health_monitor_defaults` (expects 30.0 vs implemented 10.0) so the backend suite is fully green.
4. **Regenerate `backend/openapi.json`** in CI so the snapshot matches the live 31 paths / 40 operations.
5. **Multi-vehicle simulation dashboard** — the manager already supports per-vehicle instances; the UI could orchestrate scenario fleets (e.g. fleet of 5 vehicles, mixed scenarios).

## 32.2 Mid-term

6. **Horizontal scale:** move the event bus to Redis Streams / NATS and the supervisors to a single-leader election; add Prometheus metrics (`/metrics`) and OpenTelemetry spans across simulator → MQTT → API → agent.
7. **Real-vehicle ingest path:** OBD-II/CAN adapter publishing the same `TelemetryMessage` envelope (`source_type='real'` is already modeled), plus VIN decoding to auto-populate make/model/year.
8. **Smarter health:** per-vehicle learned baselines, seasonality, remaining-useful-life indicators, anomaly detection (isolation forest / forecasting) feeding the same `Finding` contract so the UI needs no change.
9. **RAG upgrades:** cross-encoder query routing, per-query α tuning, hybrid BM25+dense fusion ablations, citation-faithfulness evaluation harness, chunk-level feedback loop.
10. **Agent upgrades:** streaming token responses, tool-calling for live telemetry ("show me last hour"), multi-provider cascade with budget-aware routing, evaluation suite (grounding rate, citation precision, clamp interventions).
11. **Collaboration features:** shared annotations on snapshots/diagnoses, exportable PDF/CSV reports, alert rules (email/webhook) when status flips to `critical`.

## 32.3 Long-term / research

12. **Digital-twin fidelity:** calibrate the simulator against real drive cycles; inject faults (sensor drift, CAN errors) as first-class scenarios for reproducible failure demos.
13. **Fleet-level twin:** aggregate health across vehicles, parts commonality, recall detection.
14. **Edge deployment:** lightweight model distillation of BGE-M3 for on-vehicle inference with cloud sync.
15. **Formal verification & safety:** hazard analysis (FMEA) integration so rule thresholds trace to documented failure modes — valuable for faculty research collaboration.

---

# 33 — Final Validation Report

*This section records how the document itself was verified. Evidence gathered 2026-10-08 on the actual repository.*

## 33.1 Verification methods used

| Method | What it validated |
|---|---|
| **Live test execution** | Backend `pytest` full run, `ruff check`, frontend `typecheck`/`lint`/`vitest` — §28.3 numbers are measured, not copied |
| **Live OpenAPI generation** | `app.openapi()` from the real app object → **31 paths / 40 operations** — every endpoint in §20 exists in code |
| **Filesystem audit** | `git status --short`, directory listings, recursive file counts (129 backend `.py`, 117 frontend `.ts/.tsx`, 51 backend test files, 12 frontend test files) |
| **Source inspection** | Every constant, threshold, enum, env var, and topic string in this document was read from the source files listed beside it |
| **Cross-reference** | Migration chain head (`b7d9f1e2a3c4`), Makefile targets, CI workflow steps, script behavior |

## 33.2 Claims classification

| Status | Items |
|---|---|
| ✅ **Implemented & verified** | Telemetry pipeline (end-to-end), MQTT layer, simulator + scenarios, supervision (subscriber + simulation manager), health intelligence (all branches incl. provisional/no-data), snapshot immutability, RAG ingestion + query pipelines, pgvector HNSW + GIN, LangGraph agent graph + validation/clamping, provider fallback logic, auth (register/login/refresh rotation/reuse detection/logout/password change), ownership/role authorization, rate limiting, simulation control incl. `degraded` derivation, **Workflow Monitor (backend bus + 3 endpoints + instrumentation + frontend page/components/SSE proxy + event-bus tests)**, all 40 API operations, Alembic chain (8 migrations), CI, dt-* scripts, test suites (numbers in §28.3) |
| ⚠️ **Partially verified** | `mqtt_e2e` integration tests (present, deselected — need a live broker to run); live LLM calls (need API keys — code paths unit-tested with `mock`); live embedding/reranking (needs `[rag]` extra — stubbed in default suite); Supabase-specific pooling/TLS behavior (documented, exercised historically per P0 report, not re-run in this audit) |
| ❌ **Known stale artifacts (documented, not fixed — out of scope)** | `backend/openapi.json` snapshot (23 vs live 31 paths); `test_health_monitor_defaults` (1 failing assertion: 30.0 expected vs 10.0 implemented); `tasks/todo.md` frontend checkboxes; `backend/docs/…GUIDE.md` + `backend/README.md` (pre-frontend) |
| 🔮 **Future work** | Everything in §32 — explicitly not present in the codebase |

## 33.3 Repository inventory (measured)

| Metric | Value |
|---|---|
| Backend source files (`app/` + `simulator/`, excl. `__pycache__`) | 129 |
| Backend test files | 51 (grouped in 9 directories) |
| Frontend source files (`src/**/*.ts,tsx`) | 117 |
| Frontend test files / tests | 12 / 92 |
| ORM tables | 9 |
| Alembic migrations | 8 (head `b7d9f1e2a3c4`) |
| API paths / operations (live) | 31 / 40 |
| Frontend routes | login, register, dashboard, vehicles, vehicle workspace (+ health/telemetry/diagnosis/history), simulations, workflow, rag, admin/rag, profile |
| Workflow component files | 10 (view, overview, filters, timeline, 5 pipeline panels, + page) |
| Compose services | 5 (postgres, backend, mosquitto, mqtt-subscriber, simulator) |
| Makefile targets | 25 phony (+ `.venv`) |
| PowerShell scripts | 4 — `scripts/dt-start.ps1`, `dt-stop.ps1`, `dt-status.ps1` (runtime control) + `setup-opencode-digital-twin.ps1` (dev-tooling bootstrap) |
| MQTT topics | `vehicles/{id}/telemetry`, `vehicles/{id}/status` (pattern `vehicles/+/telemetry`) |
| Scenario types | 4 (normal, high_temperature, low_battery, high_engine_load) |

## 33.4 Environment & test-run disclosure

- **Machine:** Windows 11 Home (PowerShell), Python **3.14.7** venv at `backend\.venv` (project requires ≥3.12), Node **24.19.0** / npm, local PostgreSQL **17.10** with pgvector, local Mosquitto config present.
- **Backend suite:** ran to completion (5 m 45 s): **1 failed, 541 passed, 10 skipped, 4 deselected**. The failure is the stale expectation documented in §28.3; skips are pgvector/env-gated; deselections are the `mqtt_e2e` marker (requires a live broker — could not be exercised in this audit without starting the broker, and doing so was not necessary to validate documentation claims).
- **Frontend suites:** all green (92/92 tests, typecheck, lint).
- **No code, schema, or configuration was modified** during this documentation task; `git status` after the audit is unchanged except for this new document.

## 33.5 Document map to faculty review needs

| Review purpose | Sections |
|---|---|
| **Viva — "how does it work?"** | §2 (8 diagrams), §7 (15-step lifecycle), §10–§16 (each subsystem with exact values) |
| **Viva — "what's actually yours vs generated?"** | §1 (git audit), §33.2 (claims classification), §31 (limitations — no overclaiming) |
| **Report reference** | §6 (DB schema), §20 (40 endpoints), §21 (env vars), §11 (RAG constants), §28 (test numbers) |
| **Onboarding** | §22 install → §23 DB → §24 broker → §25 run → §26 use → §29 troubleshooting |
| **Live demo** | §19.4 + §27 (11 demos, ~12 min) |

---

*End of document. Generated as a documentation-only artifact: no application code, schema, or behavior was altered. All measured values reflect the repository state at HEAD `3c630c2` plus the uncommitted Workflow Monitor feature present in the working tree.*
