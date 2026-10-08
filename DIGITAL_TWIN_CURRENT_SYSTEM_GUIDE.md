# Digital Twin - Current System Guide

> **Scope.** This document describes the implementation actually present in the repository at the time of inspection. Planned functionality must not be described as implemented.
>
> Every statement below was verified against source code, Alembic migrations, `backend/openapi.json`, configuration files, the test suites, and a live run of both applications. Where something is *not* implemented it is stated as such, and where a piece of code contradicts its own documentation the contradiction is recorded rather than smoothed over.
>
> **Supersedes.** `backend/docs/DIGITAL_TWIN_COMPLETE_SYSTEM_GUIDE.md` (1,077 lines) for backend-only subjects. That document remains correct on almost all backend internals but predates the entire frontend and contains several stale counts and missing modules. Section 33 lists every discrepancy found.

---

## Table of contents

1. [Document status and verification basis](#1-document-status-and-verification-basis)
2. [System overview](#2-system-overview)
3. [Feature inventory](#3-feature-inventory)
4. [Architecture](#4-architecture)
5. [Technology stack](#5-technology-stack)
6. [Repository folder tree](#6-repository-folder-tree)
7. [File responsibilities](#7-file-responsibilities)
8. [Backend](#8-backend)
9. [Complete API reference](#9-complete-api-reference)
10. [Authentication and authorization](#10-authentication-and-authorization)
11. [Database schema and migrations](#11-database-schema-and-migrations)
12. [Telemetry ingestion](#12-telemetry-ingestion)
13. [Vehicle health intelligence](#13-vehicle-health-intelligence)
14. [Agentic reasoning](#14-agentic-reasoning)
15. [Manufacturer documentation RAG](#15-manufacturer-documentation-rag)
16. [Frontend](#16-frontend)
17. [Frontend routes](#17-frontend-routes)
18. [Frontend components](#18-frontend-components)
19. [Frontend data flows](#19-frontend-data-flows)
20. [User flows](#20-user-flows)
21. [Admin flows](#21-admin-flows)
22. [Configuration reference](#22-configuration-reference)
23. [Setup](#23-setup)
24. [Run](#24-run)
25. [Testing](#25-testing)
26. [Verification evidence](#26-verification-evidence)
27. [Known limitations](#27-known-limitations)
28. [Security posture](#28-security-posture)
29. [Performance and scaling](#29-performance-and-scaling)
30. [Observability and error handling](#30-observability-and-error-handling)
31. [Troubleshooting](#31-troubleshooting)
32. [Architectural decisions](#32-architectural-decisions)
33. [Comparison with the historical guide](#33-comparison-with-the-historical-guide)
34. [Phase status](#34-phase-status)
35. [Final checklist](#35-final-checklist)

---

## 1. Document status and verification basis

**Reference revision.** Git `HEAD` = `3d1aca2` ("Removed clutter files"), working tree
clean. Alembic head = `b7d9f1e2a3c4`.

**Inventory at inspection time.**

Line counts are physical lines (blank lines included), summed per file, excluding
`.venv/`, `__pycache__/`, and `node_modules/`.

| Subject | Count |
| --- | --- |
| Backend Python files (`app/`, `simulator/`, `scripts/`, `tests/`, `alembic/`) | 179 files / 20,367 lines |
| Backend application code (`app/` only) | 113 files / 11,467 lines |
| Backend test files | 40 |
| ORM tables | 9 |
| Alembic migrations | 7 |
| OpenAPI paths | 23 |
| OpenAPI operations | 30 |
| Frontend source files (`src/`) | 94 (71 `.tsx`, 22 `.ts`, 1 `.css`) |
| Frontend source lines | 11,921 (`.ts`/`.tsx`); 12,194 including `globals.css` |
| Frontend files opening with `"use client"` | 49 |
| Frontend test files / tests | 9 / 69 |
| Frontend build routes | 18 |
| Docker Compose services | 5 |
| Makefile targets | 24 |
| CLI/verification scripts | 7 |

**How each claim was verified.**

| Claim type | Method |
| --- | --- |
| API surface | `backend/openapi.json` cross-checked against `app.openapi()` generated live from `app.main:app`. Both produce 23 paths / 30 operations. |
| Schema | `backend/alembic/versions/*.py` read directly; chain reconstructed from `revision` / `down_revision`. |
| Deterministic behaviour | `app/intelligence/` source read and cross-checked against `tests/intelligence/`. |
| Agent / RAG behaviour | Source read and cross-checked against `tests/agent/`, `tests/rag/`, and the live HTTP surface. |
| Frontend | All 94 source files enumerated; behaviour read from source; `tsc`, `eslint`, `vitest`, `next build` executed. |
| Counts | Re-measured during this inspection rather than copied from any prior document. |

**Not verified.** No browser automation is available in this environment, so visual
layout, responsive breakpoints, and rendered pixel behaviour are described from source
only. No LLM provider credentials are configured, so no live provider-backed diagnosis
was observed; provider behaviour is described from the provider implementations and the
mock-provider test suite.

---

## 2. System overview

The platform ingests vehicle telemetry, stores it in PostgreSQL, computes a
deterministic health assessment, optionally reasons about it with an LLM grounded in
retrieved manufacturer documentation, and presents all of it through a Next.js web
application.

Three pipelines run side by side:

```mermaid
flowchart LR
    subgraph ingest["Ingestion (continuous)"]
        SIM["Simulator<br/>simulator.main"] -->|MQTT QoS1| BRK["Mosquitto"]
        BRK --> SUB["app.mqtt.subscriber<br/>reconnect + backoff"]
        SUB --> PARSE["TelemetryMessageParser<br/>decode + validate"]
        PARSE --> TS[("telemetry_records")]
    end

    subgraph assess["Assessment (on request)"]
        API["FastAPI"] --> VHS["VehicleHealthService"]
        TS --> VHS
        VHS --> ENG["intelligence.engine<br/>stats - trends - baselines - rules - scoring"]
        ENG --> HS[("vehicle_health_snapshots")]
    end

    subgraph reason["Reasoning (on request)"]
        API --> AS["AgentService / LangGraph"]
        HS --> AS
        AS -.->|"when enabled"| RAG["RAGService<br/>hybrid retrieval + rerank"]
        RAG --> AD[("agent_diagnoses")]
        AS --> AD
    end

    subgraph present["Presentation"]
        FE["Next.js App Router"] -->|bearer| API
        FE -.->|"session lifecycle only"| PROXY["Next.js session proxy<br/>/api/session/*"]
        PROXY --> API
    end
```

Two properties are load-bearing and easy to misread:

- **There is no scheduler.** Health analysis and agent diagnosis run only when a
  client calls the API. The frontend's telemetry view polls; nothing on the server
  analyses on a timer.
- **Health analysis is not LLM work.** `app/intelligence/` is a pure package with no
  database, no network, and no model. The LLM is used only to phrase and contextualise
  an assessment that has already been computed deterministically.

---

## 3. Feature inventory

### Implemented and verified

| Capability | Where | Notes |
| --- | --- | --- |
| JWT identity with rotating refresh tokens | `app/core/security.py`, `app/api/routes/auth.py` | bcrypt, SHA-256-hashed refresh tokens, theft detection |
| Two roles: `user`, `admin` | `app/models/user.py` | `admin` is DB-level promotion only |
| Single-owner vehicle registry | `app/services/vehicle_service.py` | non-owners get 404, never 403 |
| Telemetry over REST | `POST /vehicles/{id}/telemetry` | idempotent via `source_event_id` |
| Telemetry over MQTT | `app/mqtt/` | QoS 1, reconnect, dedup, malformed-skip |
| Deterministic vehicle simulator | `simulator/` | 4 scenarios, seeded, physically consistent |
| Deterministic health engine | `app/intelligence/` | statistics, trends, baselines, rules, scoring, confidence |
| Immutable health snapshots | `vehicle_health_snapshots` | re-analysis inserts, never updates |
| LangGraph agent workflow | `app/agent/` | supervisor -> rag? -> reason -> validate -> persist |
| Provider fallback | `app/agent/providers/` | OpenRouter primary, Groq fallback, mock for tests |
| Deterministic severity/confidence clamping | `app/agent/determinism.py` | the LLM cannot escalate severity |
| Evidence grounding and citation integrity | `app/agent/grounding.py`, `citations.py` | fabricated citations are dropped |
| Hybrid RAG retrieval | `app/rag/` | dense + lexical, scope tiers, cross-encoder rerank |
| Immutable document versioning | `rag_document_versions` | identical content is `unchanged`, never duplicated |
| Admin document management API | `app/api/routes/admin_rag.py` | upload, list, detail, delete; admin-only |
| Next.js web application | `frontend/` | 18 routes, 94 files, dark/light themes |
| httpOnly-cookie session proxy | `frontend/src/app/api/session/*` | refresh token never reaches JavaScript |
| Silent session renewal + single retry | `frontend/src/lib/api-client.ts` | single-flight, replays the request once |
| Manufacturer-documentation search UI | `frontend/src/components/rag/` | distinguishes empty result from outage |
| Admin corpus console | `frontend/src/components/admin/` | health, upload, document table, delete |

### Explicitly not implemented

| Capability | Status |
| --- | --- |
| PDF report generation | Not implemented |
| ML prediction / anomaly detection / time-series forecasting | Not implemented; the health engine is threshold-based statistics only |
| Scheduled or background health analysis | Not implemented; request-driven only |
| Persistence of MQTT `status` messages | Not implemented; `online`/`offline` are logged and discarded |
| PostgreSQL row-level security | Not enabled (documented posture, see section 28) |
| Per-vehicle multi-user sharing | Not implemented; `owner_user_id` is single-valued |
| Soft delete for vehicles | Not implemented; delete is a hard cascade |
| Password reset, MFA, email verification | Not implemented |
| REST rate limiting | Not implemented |
| Structured JSON logging | Not implemented; plain formatted lines |
| Online RAG evaluation module | Not implemented; `app/rag/evaluation.py` and `app/rag/diagnostics.py` do not exist |
| Time-series hypertables / continuous aggregates | Not implemented |

---

## 4. Architecture

### Layering (backend)

```
HTTP route  ->  service  ->  repository  ->  SQLAlchemy  ->  PostgreSQL
                 |
                 +-> pure domain packages (no I/O): intelligence, rag chunking/scope,
                     rag query building, agent grounding/determinism
```

Rules the code actually follows:

- **Routes are thin.** They parse input via Pydantic, resolve a dependency, delegate,
  and translate domain exceptions into HTTP.
- **Services own transactions.** `VehicleService` and `TelemetryService` commit at the
  operation boundary and roll back on failure.
- **Repositories own persistence.** They surface `NotFoundError` / `ConflictError` and
  contain no business rules.
- **Ownership is enforced in the service layer**, not only in the router. Every
  user-facing service exposes a `*_for_user` variant that calls
  `app/services/vehicle_access.ensure_vehicle_access()`.
- **Domain packages are import-light.** `app/intelligence/`, `app/rag/chunking.py`,
  `app/rag/scope.py`, `app/agent/grounding.py` and `app/agent/determinism.py` never
  import the database, the network, or model weights, which is what makes them
  exhaustively unit-testable.

### Frontend architecture

The frontend is a Next.js App Router application that talks to the backend in two
distinct ways, and the split is deliberate:

```mermaid
flowchart TB
    subgraph browser["Browser (client components)"]
        COMP["Pages + components"]
        AC["lib/api-client.ts"]
        SS["lib/session-store.ts<br/>Zustand, in-memory token"]
        COMP --> AC
        AC -->|reads token| SS
    end

    subgraph server["Next.js server (route handlers)"]
        SESS["/api/session<br/>/api/session/login<br/>/api/session/register"]
        SF["lib/session-server.ts<br/>dt_at + dt_rt cookies"]
        SESS --> SF
    end

    AC -->|"data requests<br/>Authorization: Bearer"| API["FastAPI /api/v1/*"]
    AC -->|"session lifecycle only"| SESS
    SESS -->|"server-to-server<br/>BACKEND_API_URL"| API
```

The invariant: **the refresh token exists only inside an httpOnly cookie managed by
the Next.js server.** It is never placed in `localStorage`, never returned to the
browser, and never read by application JavaScript.

---

## 5. Technology stack

### Backend

| Area | Choice |
| --- | --- |
| Language | Python `>=3.12` (`backend/pyproject.toml`) |
| Web framework | FastAPI + Uvicorn |
| Validation / settings | Pydantic v2, `pydantic-settings` |
| ORM | SQLAlchemy 2.x async, `asyncpg` driver |
| Migrations | Alembic (sole owner of schema) |
| Agent orchestration | LangGraph `StateGraph` |
| LLM SDK | `langchain-openai` over OpenAI-compatible Chat Completions |
| LLM providers | OpenRouter (primary), Groq (fallback), deterministic mock (tests) |
| Vector store | pgvector, `vector(1024)`, HNSW cosine index |
| Embeddings | `BAAI/bge-m3` via `sentence-transformers` |
| Reranker | `BAAI/bge-reranker-v2-m3` |
| Document parsing | Docling (lazy), plus a plain-text/markdown parser |
| MQTT | `aiomqtt` |
| Broker | Eclipse Mosquitto 2 |
| Database | PostgreSQL 16 |
| Tests | pytest, pytest-asyncio, httpx ASGI transport |
| Lint / format | Ruff (`ruff check`, `ruff format`) |

### Frontend

| Area | Choice | Version |
| --- | --- | --- |
| Framework | Next.js (App Router) | `^16.3.7` |
| UI runtime | React / React DOM | `^19.3.0` |
| Language | TypeScript (strict) | `^5.9.3` |
| Server state | TanStack Query | `^5.104.0` |
| Client state | Zustand | `^5.0.8` |
| Styling | Tailwind CSS v4 (`@tailwindcss/postcss`) + `tw-animate-css` | `^4.3.3` |
| Component primitives | Radix UI (dialog, dropdown-menu, label, slot, tabs, tooltip) | various |
| Charts | Recharts | `^3.10.1` |
| Icons | `lucide-react` | `^0.545.0` |
| Class utilities | `clsx`, `tailwind-merge`, `class-variance-authority` | |
| Tests | Vitest, jsdom, Testing Library, jest-dom | `^4.0.9` |

---

## 6. Repository folder tree

```
Digital Twin/
├── DIGITAL_TWIN_CURRENT_SYSTEM_GUIDE.md   # this document
├── backend/
│   ├── app/
│   │   ├── main.py                        # app factory, lifespan, CORS, exception handlers
│   │   ├── api/
│   │   │   ├── router.py                  # mounts every route module under /api/v1
│   │   │   ├── dependencies/
│   │   │   │   ├── auth.py                # bearer resolution, get_current_user, require_admin
│   │   │   │   ├── database.py            # get_db session dependency + service factories
│   │   │   │   └── rag.py                 # RAGService / AdminRagDocumentService providers
│   │   │   └── routes/                    # health, auth, users, vehicles, telemetry,
│   │   │                                  # vehicle_health, agent, rag, admin_rag
│   │   ├── core/                          # config, database, exceptions, logging, security
│   │   ├── models/                        # 9 tables across 7 modules
│   │   ├── schemas/                       # Pydantic request/response contracts
│   │   ├── repositories/                  # 6 persistence modules
│   │   ├── services/                      # auth, vehicle, vehicle_access, telemetry, vehicle_health
│   │   ├── intelligence/                  # pure deterministic health engine (8 modules)
│   │   ├── agent/                         # LangGraph workflow, providers, tools (17 modules)
│   │   ├── mqtt/                          # topics, schemas, parser, client, publisher,
│   │   │                                  # subscriber, exceptions (7 modules)
│   │   └── rag/                           # config, errors, schemas, scope, chunking, embeddings,
│   │                                      # query_builder, retrieval, ingestion, repository,
│   │                                      # rag_service, admin_documents,
│   │                                      # parser/{base,docling,plain_text}, reranker/base
│   ├── simulator/                         # config, vehicle, telemetry_generator, publisher, main
│   ├── scripts/                           # check_db, seed_demo_vehicle, smoke_agent_llm,
│   │                                      # ingest_documents, query_rag,
│   │                                      # phase5_real_model_smoke, phase5_agent_rag_verify
│   ├── infrastructure/mosquitto/          # mosquitto.conf, mosquitto.local.conf, mosquitto.acl
│   ├── alembic/                           # env.py, script.py.mako, versions/ (7 migrations)
│   ├── tests/                             # agent, api, core, intelligence, mqtt, rag,
│   │                                      # repositories, services, simulator, conftest.py
│   ├── docs/                              # phase reports + historical guide + quickstart
│   ├── data/documents/                    # sample corpus document
│   ├── .env.example  alembic.ini  Dockerfile  docker-compose.yml
│   ├── Makefile  pyproject.toml  README.md
│   └── openapi.json                       # committed, in sync with the app (23 paths / 30 ops)
├── frontend/
│   ├── src/
│   │   ├── app/                           # App Router: (auth), (app), api/session handlers
│   │   ├── components/                    # admin, auth, dashboard, diagnosis, health, layout,
│   │   │                                  # profile, rag, states, telemetry, ui, vehicles
│   │   ├── hooks/                         # use-auth-guard, use-active-vehicle,
│   │   │                                  # use-vehicle-data, use-mutations
│   │   ├── lib/                           # api-client, api-error, session-store, session-server,
│   │   │                                  # query-keys, format, metrics, utils
│   │   ├── services/                      # auth, vehicles, rag (endpoint mappings)
│   │   ├── stores/                        # providers, query-provider, theme-provider,
│   │   │                                  # vehicle-selection
│   │   ├── test/                          # utils.tsx (render helper + fixtures)
│   │   ├── types/                         # api.ts (hand-written mirror of backend contracts)
│   │   ├── app/globals.css                # design tokens, themes, utilities
│   │   └── app/error.tsx  app/not-found.tsx
│   ├── next.config.ts  postcss.config.mjs  tsconfig.json  eslint.config.mjs
│   ├── vitest.config.mts  vitest.setup.ts  package.json  .env.example
├── data/documents/toyota_camry_2024_cooling.md   # sample corpus document
└── (no root-level build artefacts; the root contains only this guide and the 3 trees above)
```

---

## 7. File responsibilities

### Backend entry point and infrastructure

| File | Responsibility |
| --- | --- |
| `app/main.py` | Builds the FastAPI app, configures logging, installs CORS, runs the lifespan (init engine, warn-but-serve on DB failure, dispose on shutdown), registers 23 exception handlers (21 typed domain handlers, `RequestValidationError`, and a catch-all `Exception`), serves `/docs`, `/redoc`, `/openapi.json`, and a non-schema `GET /`. |
| `app/core/config.py` | `Settings` (BaseSettings) for app, DB, CORS, MQTT, health, and identity. Enforces a strong `JWT_SECRET` outside `development`/`local`. |
| `app/core/database.py` | Async engine, session factory, pool sizing, `NullPool` in tests, and the reachability probe used by `/health/db`. |
| `app/core/security.py` | Password hashing/verification, access-JWT create/decode with an algorithm whitelist and expiry bounds, refresh-token generation, SHA-256 hashing, and refresh-JWT handling. |
| `app/core/exceptions.py` | `AppError` and subclasses: `NotFoundError`, `ConflictError`, `DatabaseError`, `AuthenticationError`, `AuthorizationError`. |
| `app/core/logging.py` | One-time root logger configuration and quieting of `uvicorn.access`, `httpx`, `httpcore`. |
| `app/api/router.py` | The single place route modules are mounted; defines every URL prefix in the system. |
| `app/dependencies/auth.py` | `get_current_user` (bearer -> JWT -> live DB re-read) and `require_admin`. |
| `app/dependencies/database.py` | Per-request `AsyncSession` plus factories for `VehicleService`, `TelemetryService`, `VehicleHealthService`, `AgentService`, `RAGService`, `AdminRagDocumentService`. |

### Backend domain

| File | Responsibility |
| --- | --- |
| `app/intelligence/models.py` | Typed, versioned domain models: `TelemetryPoint`, `MetricStatistics`, `TrendInsight`, `BaselineInsight`, `Finding`, `ScoreDetails`, `DataQuality`, `AnalysisWindow`, `HealthContext`, `SUPPORTED_METRICS`, `METRIC_UNITS`. |
| `app/intelligence/statistics.py` | Robust per-metric summaries (mean, median, min, max, IQR, std-dev, CV); never emits NaN or infinity. |
| `app/intelligence/trends.py` | Least-squares slope and normalised slope -> `increasing` / `decreasing` / `stable`. |
| `app/intelligence/baselines.py` | Per-vehicle historical median and scaled MAD (`1.4826 * MAD`); deviation classification. |
| `app/intelligence/rules.py` | `RuleThresholds` and rule evaluation producing factual `Finding` objects. |
| `app/intelligence/scoring.py` | Penalty accumulation, per-category caps, score clamp, and status thresholds. |
| `app/intelligence/context.py` | Assembles the versioned `HealthContext`. |
| `app/intelligence/engine.py` | Orchestrates the pipeline; owns the confidence calculation input. |
| `app/services/vehicle_health_service.py` | Loads the analysis window and the baseline window with a bounded row estimate, runs the engine, persists the immutable snapshot. |
| `app/agent/graph.py` | Compiles the LangGraph `StateGraph`. |
| `app/agent/nodes.py` | `supervisor`, `rag`, `reason`, `validate`, `persist` and the two routing predicates. |
| `app/agent/state.py` | `AgentState` TypedDict. |
| `app/agent/determinism.py` | `derive_severity`, `derive_confidence`, clamps. |
| `app/agent/grounding.py` | Drops findings and citations not supported by the deterministic context. |
| `app/agent/citations.py` | Builds provenance citations from retrieved sources. |
| `app/agent/prompts.py` | `SYSTEM_PROMPT`: exactly one JSON object, untrusted-context rule, docs-are-data rule. |
| `app/agent/llm_service.py` | Structured-output invocation with retries and provider fallback routing. |
| `app/agent/providers/{base,factory,openrouter,groq,mock}.py` | Provider adapters and the deterministic test provider. |
| `app/agent/tools/vehicle_context.py` | Serialises the health context for the prompt, bounded by `llm_context_max_chars`. |
| `app/agent/tools/manufacturer_guidance.py` | RAG-as-tool with provenance and negative grounding. |
| `app/agent/triggers.py` | Trigger enum and critical-event cooldown deduplication. |
| `app/rag/repository.py` | Raw SQL over pgvector + FTS within the caller's connection and transaction; only reads completed versions. |
| `app/rag/retrieval.py` | Fusion, dedup, scope tiering, rerank shortlist, threshold filter, top-k cut. |
| `app/rag/ingestion.py` | Parse -> hash -> version -> chunk -> embed -> persist; idempotent and immutable. |
| `app/rag/admin_documents.py` | Upload validation, temp-file streaming with a byte ceiling, transactional commit/rollback, list/detail/delete. |
| `app/mqtt/subscriber.py` | Reconnect loop, consumption loop, bounded DB retries, skip-and-continue error handling, signal-driven shutdown. |
| `simulator/main.py` | Drive-cycle loop, status announcements, graceful shutdown. |

### Frontend

| File | Responsibility |
| --- | --- |
| `src/lib/api-client.ts` | The only place the browser performs HTTP to the backend. Bearer injection, proactive renewal, single-flight `renewSession()`, one replay after a 401, `AbortSignal` passthrough, `FormData` support. |
| `src/lib/api-error.ts` | `ApiError` plus normalisation of the backend's two error envelopes (string `detail` and 422 array `detail`) into per-field messages. |
| `src/lib/session-store.ts` | Zustand session state: `loading` / `authenticated` / `anonymous`, in-memory access token, user, expiry, expired notice. |
| `src/lib/session-server.ts` | Server-only cookie and backend-proxy helpers: `dt_at`, `dt_rt`, TTLs, `backendFetch`, JWT `exp` read. |
| `src/lib/query-keys.ts` | Centralised query keys so mutation invalidation cannot drift from reads. |
| `src/lib/metrics.ts` | Mirrors the backend `METRIC_UNITS` registry for display. |
| `src/lib/format.ts` | Number, duration, relative-time, and status formatting. |
| `src/hooks/use-auth-guard.ts` | `useSessionBootstrap` (one probe per load) and `useAuthGuard` (client-side redirect; explicitly presentation-only). |
| `src/hooks/use-active-vehicle.ts` | Resolves the vehicle every page renders, falling back to the first vehicle. |
| `src/hooks/use-vehicle-data.ts` | Queries and hooks, including 404 -> `null` normalisation for "no snapshot yet" and "no diagnosis yet". |
| `src/hooks/use-mutations.ts` | Mutations plus their invalidation graph. |
| `src/services/auth.ts` | Session calls through the proxy; `me` and profile update straight to the backend. |
| `src/services/vehicles.ts` | `vehiclesApi`, `telemetryApi`, `healthApi`, `agentApi`. |
| `src/services/rag.ts` | `ragApi` (search, health) and `adminRagApi` (list, get, multipart upload, delete). |
| `src/stores/query-provider.tsx` | TanStack Query client, retry policy, and `clearQueryCache()` used at sign-out. |
| `src/stores/theme-provider.tsx` | Dark/light theme as an external store (`useSyncExternalStore`), localStorage + `<html>` class, pre-paint inline script. |
| `src/stores/vehicle-selection.ts` | Selected vehicle id, persisted under `dt-selected-vehicle`. |
| `src/stores/providers.tsx` | Ordered provider composition: theme, query cache, tooltip. |
| `src/types/api.ts` | Hand-written TypeScript mirror of the backend response contracts. |
| `src/app/layout.tsx` | Root layout, metadata, viewport, skip link, pre-paint theme script, provider mount. |
| `src/app/(app)/layout.tsx` | Authenticated chrome via `AppShell`, wrapped in `Suspense` for search-param reads. |
| `src/app/api/session/route.ts` | `GET /api/session` probe with silent refresh. |
| `src/app/api/session/login/route.ts` | `POST` login and `DELETE` logout. |
| `src/app/api/session/register/route.ts` | `POST` register followed by a server-side login. |

---

## 8. Backend

### 8.1 Application lifecycle

`app/main.py` lifespan:

1. Configure logging once per process.
2. Initialise the async engine and probe the database.
3. If the database is unreachable, log a warning and **continue serving**. Degradation is
   reported by `/health/db`, not by refusing to boot. This is deliberate: the health
   endpoint is how an orchestrator learns the state.
4. On shutdown, dispose the engine.

### 8.2 Router mounts

`app/api/router.py` mounts nine modules under `api_v1_prefix` (`/api/v1`):

| Module | Prefix | Tag |
| --- | --- | --- |
| `health` | `/health` | Health |
| `auth` | `/auth` | Auth |
| `users` | (none) | Me |
| `vehicles` | `/vehicles` | Vehicles |
| `telemetry` | `/vehicles/{vehicle_id}/telemetry` | Telemetry |
| `vehicle_health` | `/vehicles/{vehicle_id}/health` | Vehicle Health |
| `agent` | `/vehicles/{vehicle_id}/agent` | Agent |
| `rag` | `/rag` | RAG |
| `admin_rag` | `/admin` | Admin RAG |

### 8.3 Health endpoints

| Endpoint | Behaviour |
| --- | --- |
| `GET /api/v1/health` | Liveness. Does not touch the database. Returns `{"status": ..., "service": ...}`. |
| `GET /api/v1/health/db` | Runs `SELECT 1`. Returns `{"status": "healthy", "service", "database"}`, or HTTP 503 with `status: "degraded"`. |

Both are public. There is no authentication requirement for liveness or DB reachability.

### 8.4 Services

| Service | Public surface |
| --- | --- |
| `AuthService` | register, authenticate, rotate refresh token, logout, revoke-all-on-reuse. |
| `VehicleService` | create/get/get-by-vin/list/update/delete, each with an ownership-aware `*_for_user` variant. |
| `VehicleAccess` (`vehicle_access.py`) | `ensure_vehicle_access()` - the single ownership gate reused by telemetry, health, and agent services. |
| `TelemetryService` | create (idempotent), list by vehicle with time filters. |
| `VehicleHealthService` | `analyze_vehicle`, `get_latest`, `list_history`, plus `*_for_user` variants. |

`VehicleHealthService` bounds its queries with `_window_limit(minutes, interval) =
int(minutes * 60 / interval) * 2 + 100` rows, applied to both the analysis window and
the baseline window, so a wide request cannot load an unbounded result set.

### 8.5 Repositories

`VehicleRepository`, `TelemetryRepository`, `HealthSnapshotRepository`,
`AgentDiagnosisRepository`, `UserRepository`, `RefreshTokenRepository`, plus
`app/rag/repository.py` (`RagRepository`, raw SQL over pgvector and FTS).

---

## 9. Complete API reference

23 paths, 30 operations. `backend/openapi.json` is committed and matches the running
application exactly. Interactive docs: `/docs` (Swagger), `/redoc`, `/openapi.json`.

**Auth column.** `public` = no credentials. `user` = any authenticated, active user.
`owner` = authenticated user who owns the vehicle, or an admin. `admin` = admin role.
Note that "not found" (404) is returned instead of "forbidden" (403) for vehicles the
caller does not own, so vehicle existence is not leaked.

### 9.1 Health (2 operations, public)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/health` | Liveness, no database access. |
| GET | `/api/v1/health/db` | `SELECT 1`; 200 healthy, 503 `status: "degraded"`. |

### 9.2 Authentication (5 operations)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | public | 201 with the created user (no token pair). `extra="forbid"`, so `role` or `is_active` in the body is 422. Email is case-normalised. Password 8-72 chars. |
| POST | `/api/v1/auth/login` | public | 200 `TokenResponse`. Returns the same 401 detail for an unknown email and a wrong password. |
| POST | `/api/v1/auth/refresh` | public (bearer token in body) | Rotates the refresh token. Single-use; reuse of a revoked token revokes every token for that user. |
| POST | `/api/v1/auth/logout` | public (token in body) | 204. Idempotent revoke. |
| GET | `/api/v1/auth/me` | user | Current user from a live DB read. |

### 9.3 Profile (2 operations)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/users/me` | user | Profile. |
| PATCH | `/api/v1/users/me` | user | `full_name` only (`max_length=120`); `extra="forbid"`, so any other field is 422. |

### 9.4 Vehicles (5 operations)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/vehicles` | user | Paginated. `page >= 1`, `page_size` 1-100 (default 20). Non-admins are filtered to their own vehicles; admins see all. |
| POST | `/api/v1/vehicles` | user | 201. VIN 5-50 chars, trimmed and upper-cased; `make`/`model` 1-100; `year` 1900-2100; `engine_type` optional <=100; `extra="forbid"`. `owner_user_id` is the caller. 409 on duplicate VIN. |
| GET | `/api/v1/vehicles/{vehicle_id}` | owner | 404 when missing or unowned. |
| PATCH | `/api/v1/vehicles/{vehicle_id}` | owner | Mutable metadata only: `make`, `model`, `year`, `engine_type`. VIN, owner, `status`, `source_type`, `simulation_enabled` are 422 by design. |
| DELETE | `/api/v1/vehicles/{vehicle_id}` | owner | 204. Cascades to telemetry, snapshots, and diagnoses; `owner_user_id` becomes `NULL` via `ON DELETE SET NULL`. |

### 9.5 Telemetry (2 operations)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/vehicles/{vehicle_id}/telemetry` | owner | Paginated, `page_size` 1-500 (default 50), optional ISO `start_time` / `end_time`. |
| POST | `/api/v1/vehicles/{vehicle_id}/telemetry` | owner | 201. `extra="forbid"`. Optional `source_event_id` (<=64) makes the write idempotent: a repeat returns the existing row instead of inserting. Metric bounds are enforced by the schema (see section 12). |

Telemetry metric bounds accepted by `TelemetryCreate`:

| Metric | Bound |
| --- | --- |
| `rpm`, `speed`, `engine_runtime`, `odometer` | `>= 0` |
| `engine_load`, `throttle_position` | `0..100` |
| `coolant_temperature`, `oil_temperature` | `-60..200` |
| `intake_air_temperature` | `-60..120` |
| `battery_voltage` | `0..40` |
| `fuel_level` | `0..100` |

### 9.6 Vehicle health (3 operations)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/api/v1/vehicles/{vehicle_id}/health/analyze` | owner | 200 with the full context. Optional `window_minutes` 1-1440; defaults to `HEALTH_ANALYSIS_WINDOW_MINUTES`. Persists a new immutable snapshot every call. |
| GET | `/api/v1/vehicles/{vehicle_id}/health` | owner | Latest snapshot as a full context, or 404 when none exists. |
| GET | `/api/v1/vehicles/{vehicle_id}/health/history` | owner | Paginated light-weight entries (`HealthSnapshotItem`), newest first. |

### 9.7 Agent (5 operations)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/api/v1/vehicles/{vehicle_id}/agent/query` | owner | **Invokes the LLM.** `query` 1-2000 chars, whitespace stripped. |
| POST | `/api/v1/vehicles/{vehicle_id}/agent/events/critical` | owner | **Invokes the LLM.** Optional `rule_ids` list, max 100. Identical rule sets within `AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS` return the existing diagnosis with no new LLM call. |
| GET | `/api/v1/vehicles/{vehicle_id}/agent/dashboard` | owner | **No LLM.** Latest health context plus latest diagnosis and its age. |
| GET | `/api/v1/vehicles/{vehicle_id}/agent/diagnoses` | owner | Paginated history (`AgentDiagnosisItem`), newest first. |
| GET | `/api/v1/vehicles/{vehicle_id}/agent/diagnoses/latest` | owner | Full latest diagnosis, or 404 when none. |

### 9.8 RAG, read-only (2 operations)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/rag/health` | **admin** | Enabled state, pgvector availability, adapter identities, corpus counts. Never loads weights. 403 for non-admins. |
| GET | `/api/v1/rag/search` | user | `q` 1-500 chars (required). Optional `make` (<=64), `model` (<=128), `year` (1900-2100), `top_k` (1-20). 503 when `RAG_ENABLED=false`. |

**Search response semantics - important.** The endpoint returns HTTP 200 with a body
when retrieval works:

| Situation | HTTP | Body |
| --- | --- | --- |
| Passages found | 200 | `available: true`, `reason: "hybrid"` or `"hybrid+rerank"` |
| Retrieval worked, nothing matched | 200 | `available: false`, `reason: "hybrid"` or `"hybrid+rerank"`, empty evidence |
| RAG disabled or backend unavailable | **503** | stable `detail` string |

`available: false` at HTTP 200 is a **successful zero-evidence search**, not an
outage. The frontend encodes exactly this distinction.

### 9.9 Admin RAG document management (4 operations)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/api/v1/admin/rag/documents` | **admin** | 201. `multipart/form-data`. Required: `file`, `canonical` (1-512). Optional: `make`, `model`, `year`, `year_end`, `manufacturer`, `title`, `source_uri`, `source_type`, `document_type`, `language`. Unknown form fields are rejected with 422. Runs the standard ingestion pipeline. 400 unsupported format, 413 too large, 422 ingestion failure, 503 backend unavailable. |
| GET | `/api/v1/admin/rag/documents` | **admin** | Paginated (`page_size` 1-100, default 20), newest first. Optional exact filters `make`, `model`, `canonical`, `year`, and `status` (version ingestion status). |
| GET | `/api/v1/admin/rag/documents/{document_id}` | **admin** | Document identity plus immutable version history with per-version chunk counts and status. 404 when absent. |
| DELETE | `/api/v1/admin/rag/documents/{document_id}` | **admin** | 204. Transactional cascade across document, versions, chunks, and vectors. |

### 9.10 Non-schema endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/` | `{"service": ..., "docs": "/docs"}`. `include_in_schema=False`, so it is not in the 23 paths. |
| GET | `/docs`, `/redoc`, `/openapi.json` | Interactive documentation and the committed spec. |

### 9.11 HTTP error contract

| Status | Meaning | Source |
| --- | --- | --- |
| 400 | Upload validation failure (unsupported extension, non-plain-name filename, empty file, non-UTF-8 text) | `RAGUploadValidationError` |
| 401 | Missing / invalid / expired bearer, or bad credentials | `AuthenticationError` |
| 403 | Authenticated but not an admin | `AuthorizationError` |
| 404 | Missing or unowned resource | `NotFoundError` |
| 409 | Duplicate VIN | `ConflictError` |
| 413 | Upload exceeds `RAG_MAX_UPLOAD_SIZE_MB` | `RAGUploadTooLargeError` |
| 422 | Request validation (structured `detail` array), or RAG ingestion failure | `RequestValidationError`, `RAGIngestionFailureError` |
| 500 | Unexpected DB error, agent misconfiguration, graph execution failure - details never leak | `DatabaseError`, `AgentConfigurationError`, `GraphExecutionError`, catch-all |
| 502 | LLM provider error: bad request, authentication, provider unavailable, generic provider failure, structured-output violation | `LLMBadRequestError`, `LLMAuthError`, `LLMProviderUnavailableError`, `LLMProviderError`, `StructuredOutputError` |
| 503 | LLM rate limiting; `/health/db` unreachable; RAG disabled or backend unavailable | `LLMRateLimitError`, `RAGEnabledError`, `RAGDocumentUnavailableError` |
| 504 | LLM provider timeout | `LLMTimeoutError` |

LLM errors additionally carry an `error_code` field: `llm_timeout`,
`llm_rate_limited`, `llm_authentication`, `llm_provider_unavailable`,
`llm_bad_request`, `llm_provider_error`, `structured_output_invalid`,
`agent_configuration_error`, `graph_execution_error`.

---

## 10. Authentication and authorization

### 10.1 Token model

| Token | Lifetime (default) | Storage | Transport |
| --- | --- | --- | --- |
| Access JWT | `AUTH_ACCESS_TOKEN_MINUTES`, default **20 min** | Backend: not stored. Frontend: memory + httpOnly cookie `dt_at` | `Authorization: Bearer <token>` |
| Refresh JWT | `AUTH_REFRESH_TOKEN_DAYS`, default **30 days** | Backend: SHA-256 **hash** only. Frontend: httpOnly cookie `dt_rt` scoped to `/api/session` | Request body, from the Next.js server only |

Access JWT claims are deliberately minimal: `sub` (user id) and a token type.
Authority is **never** read from the token.

### 10.2 Per-request authorisation

For every authenticated request the backend:

1. Extracts the bearer token.
2. Decodes and verifies it against the configured algorithm whitelist.
3. Checks expiry.
4. **Re-reads the user from PostgreSQL.**

Only then is role and active status evaluated. A token minted before an account was
deactivated or demoted therefore stops working immediately, and a token cannot carry a
forged role because the role was never trusted from the token in the first place.

### 10.3 Refresh rotation and theft detection

1. `POST /auth/login` returns an access token and a refresh token.
2. The refresh token is hashed with SHA-256 and stored with `expires_at`; the raw token
   is never persisted.
3. `POST /auth/refresh` looks the token up by hash, revokes the presented row, and
   issues a new pair. The presented token is single-use.
4. Presenting an **already-revoked** token is treated as theft: **all** of that user's
   tokens are revoked.

### 10.4 Authorisation rules

| Rule | Implementation |
| --- | --- |
| Vehicle access | `ensure_vehicle_access()` - admins bypass; non-owners get 404, never 403 |
| Admin routes | `require_admin` dependency on all four `/admin/rag/documents` operations and on `GET /rag/health` |
| RAG search | Any authenticated user |
| Health liveness | Public |
| Ownership on create | `owner_user_id` is taken from the authenticated caller, never from the request body |

### 10.5 Frontend session architecture

The backend speaks bearer tokens only and sets no cookies of its own. The frontend
therefore adds a thin server-side session proxy so the refresh token never has to
enter JavaScript.

| Cookie | Attributes | Purpose |
| --- | --- | --- |
| `dt_at` | httpOnly, `sameSite=lax`, `secure` in production, `path=/`, `maxAge` 12 h | Lets the Next.js server call the backend on the browser's behalf and survive a reload |
| `dt_rt` | httpOnly, `sameSite=lax`, `secure` in production, `path=/api/session`, `maxAge` 30 d | Only ever transmitted to the session route handlers |

Session route handlers:

| Route | Method | Behaviour |
| --- | --- | --- |
| `/api/session` | GET | Probe. No tokens -> 401 `{authenticated: false}`. Valid access token -> 200 with user. Expired access but valid refresh -> rotates server-side and returns a fresh pair. Backend unreachable -> **503 `{authenticated: false, detail: "Backend unavailable"}`**, deliberately distinct from signed-out, so a network blip does not sign the user out. Backend 403 (disabled/deleted account) -> cookies cleared, 401. |
| `/api/session/login` | POST | Exchanges credentials, writes both cookies, returns the access token and user to the browser. Malformed body -> 400. |
| `/api/session/login` | DELETE | Revokes the refresh token server-side, clears both cookies. Never fails the sign-out. |
| `/api/session/register` | POST | Backend `/auth/register` returns the created user and **no** token pair, so the handler performs a server-side login immediately. If that login fails it returns 201 with a message asking the user to sign in manually. |

Browser-side rules:

- The access token lives only in the Zustand session store. It is never written to
  `localStorage` and disappears when the tab closes.
- Any `401` on a data request triggers **one** silent renewal through `/api/session`,
  then the request is replayed **once**. Concurrent `401`s share a single renewal
  promise.
- A second `401` sets the session to anonymous and the user is routed to `/login`.
- Client-side route guards redirect for UX only. Every backend endpoint re-checks the
  token and ownership, so hiding a route never removes a security boundary.
- Sign-out calls `clearQueryCache()`, because the TanStack Query cache holds
  owner-scoped data in a tab-level singleton.

---

## 11. Database schema and migrations

Schema is owned exclusively by Alembic. The application never calls `create_all()` at
startup.

### 11.1 Migration chain

Linear, no branches. Head is `b7d9f1e2a3c4`.

```
e01c2724f67b  initial schema (vehicles, telemetry_records)
   -> 7e38f4f3d70b  add source_event_id + partial unique index
   -> a1b2c3d4e5f6  create vehicle_health_snapshots
   -> c7f2e8a1b3d4  create agent_diagnoses
   -> 4f9d3c2b1a8e  Phase 5: RAG tables + CREATE EXTENSION vector + HNSW/GIN indexes
   -> b8c3e1d4a9f7  add rag_* metadata columns to agent_diagnoses
   -> d6a9b1c2e3f4  Phase 6: users, refresh_tokens, vehicle ownership
   -> b7d9f1e2a3c4  rag chunk HNSW embedding index
```

The head (`b7d9f1e2a3c4`) is what is stamped and upgraded on a Supabase-managed
PostgreSQL (Phase 3.5 / verified live). No schema migration is required for the
Phase 10 health-context fields: they all live inside `context_json`
(`context_schema_version` = `1.1`) and the existing nullable columns.

### 11.2 Table inventory (9 tables, 7 modules)

| Module | Table |
| --- | --- |
| `models/vehicle.py` | `vehicles` |
| `models/telemetry.py` | `telemetry_records` |
| `models/health_snapshot.py` | `vehicle_health_snapshots` |
| `models/agent_diagnosis.py` | `agent_diagnoses` |
| `models/user.py` | `users` |
| `models/refresh_token.py` | `refresh_tokens` |
| `models/rag.py` | `rag_documents`, `rag_document_versions`, `rag_chunks` |

### 11.3 `users`

`id` (uuid PK), `email` (unique, case-normalised), `password_hash` (bcrypt), `role`
(CHECK `user|admin`), `full_name` (nullable), `is_active` (bool), `created_at`,
`updated_at`. Only the `user` role is reachable through the public API; `admin` is a
privileged, database-level promotion.

### 11.4 `refresh_tokens`

`id` (uuid PK), `user_id` (FK `users.id`, `ON DELETE CASCADE`), `token_hash` (SHA-256
of the raw token, indexed), `expires_at`, `revoked_at` (nullable). Raw tokens are never
stored.

### 11.5 `vehicles`

`id` (uuid PK), `vin` (unique, upper-cased at the API boundary), `make`, `model`,
`year`, `engine_type`, `owner_user_id` (FK `users.id`, `ON DELETE SET NULL`, indexed),
`source_type` (CHECK `simulator|real`, default `simulator`), `status` (CHECK
`active|disabled`, default `active`), `simulation_enabled` (bool, default `false`),
`created_at`, `updated_at`.

### 11.6 `telemetry_records`

`id` (uuid PK), `vehicle_id` (FK CASCADE), `timestamp` (timestamptz), 11 metric columns
(`rpm`, `speed`, `engine_load`, `coolant_temperature`, `oil_temperature`,
`battery_voltage`, `fuel_level`, `intake_air_temperature`, `throttle_position`,
`engine_runtime`, `odometer`), `raw_payload` (JSONB, nullable), `source_event_id`
(nullable, <=64), `created_at`.

**Idempotency index.** A partial unique index on `(vehicle_id, source_event_id) WHERE
source_event_id IS NOT NULL` guarantees at most one row per event id per vehicle. The
service checks first and treats an `IntegrityError` as a duplicate, so concurrent
deliveries converge instead of racing.

### 11.7 `vehicle_health_snapshots` (immutable)

`id`, `vehicle_id` (FK CASCADE), `generated_at`, `window_start`, `window_end`,
`sample_count`, `health_score`, `health_status`, `confidence`,
`context_schema_version`, `context_json` (JSONB, the complete context), `created_at`.
Indexes on `(vehicle_id, generated_at)` and `(vehicle_id, health_status,
generated_at)`. Rows are never updated; re-analysis inserts a new one, so history is an
append-only audit trail.

### 11.8 `agent_diagnoses`

`id`, `vehicle_id` (FK CASCADE), `agent_run_id`, `trigger_type`, `user_query`,
`diagnosis` (JSONB), `user_id` (FK `users.id`, `ON DELETE SET NULL`), `created_at`.

Promoted queryable columns: `severity`, `confidence`, `status`, `error_code`,
`provider`, `model`, `fallback_used`, `latency_ms`, `input_tokens`, `output_tokens`,
`context_timestamp`.

RAG provenance columns: `rag_used`, `rag_evidence_count`, `rag_embedding_model`,
`rag_reranker_model`, `rag_scope` (JSONB).

Indexes on `(vehicle_id, created_at)` and `(vehicle_id, trigger_type, created_at)`.

### 11.9 `rag_documents` (identity and scope only)

`id`, `source_type` (default `manufacturer`), `canonical_source` (**UNIQUE**),
`source_uri`, `manufacturer`, `make`, `model`, `model_year_start`, `model_year_end`,
`document_type`, `title`, `language`, `created_at`, `updated_at`. Indexes on
`(make, model)` and `(manufacturer)`.

Scope fields are nullable on purpose: `NULL` means "this document makes no claim", and
never silently widens or narrows a match.

### 11.10 `rag_document_versions` (immutable snapshots)

`id`, `document_id` (FK), `version` (int), `content_hash` (sha256, indexed),
`source_filename`, `parser_name`, `parser_version`, `language`, `page_count`,
`metadata` (JSON), `embedding_model`, `embedding_dimension` (default 1024),
`chunking_version`, `ingestion_status` (`pending|unchanged|completed|failed`),
`error_message`, `created_at`. `UNIQUE(document_id, version)`.

### 11.11 `rag_chunks`

`id`, `document_version_id` (FK), `chunk_index` (0-based),
`chunk_type` (`section|continuation|preamble`), `title`, `section_title`,
`heading_path` (JSON), `page_start`, `page_end`, `start_char`, `end_char`,
`content_plain`, `scope` (`GENERIC|MAKE|MODEL|EXACT_VEHICLE`), `make`, `model`,
`year_start`, `year_end`, `embedding_store` **`vector(1024)`** with an HNSW
`vector_cosine_ops` index, `content_tsv` with a GIN index maintained by a migration
trigger, `created_at`. `UNIQUE(document_version_id, chunk_index)`.

The embedding column is created through a lazy factory
(`make_embedding_column`) so the package stays importable on a database without
pgvector. That is also why the pgvector-gated tests skip locally.

---

## 12. Telemetry ingestion

Two producers, one write path.

### 12.1 MQTT envelope

**Telemetry topic:** `{prefix}/{vehicle_id}/telemetry` (default prefix `vehicles`).
Subscribe pattern: `{prefix}/+/telemetry`. QoS 1, `retain=false`.

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

Validation rules enforced by `TelemetryMessage`:

- `schema_version` must be `1`.
- `event_id` must be present and unique per vehicle.
- `timestamp` must be timezone-aware; naive timestamps are rejected.
- Every telemetry value must be within the schema bounds (section 9.5).
- Unknown fields are rejected.

**Status topic:** `{prefix}/{vehicle_id}/status`.

```json
{
  "vehicle_id": "11111111-2222-4333-8444-555555555555",
  "status": "online",
  "timestamp": "2026-09-20T10:00:00+00:00"
}
```

`online` at start, `offline` on graceful shutdown. **Not persisted.**

### 12.2 Subscriber behaviour

`app/mqtt/subscriber.py`:

- Reconnects with exponential backoff capped at `MQTT_RECONNECT_MAX_SECONDS`.
- Parses and validates every message; `TopicParseError` and `InvalidMessageError` are
  logged and skipped - never fatal.
- An event for an unknown vehicle is logged and discarded.
- Transient database errors are retried up to `MQTT_MESSAGE_RETRY_ATTEMPTS` with a
  delay; persistent failure drops the message rather than stalling the consumer.
- Duplicate `source_event_id` is a silent no-op (the service returns the existing row).
- `SIGINT` / `SIGTERM` set a stop event for graceful shutdown.
- Contains no persistence logic; it delegates to `TelemetryService`.

`app/mqtt/client.py` passes credentials only when **both** username and password are
set, and installs a Windows `SelectorEventLoop` because `aiomqtt` requires
`add_reader`.

### 12.3 Client-id uniqueness

`MQTT_CLIENT_ID` defaults to a per-process `dtwin-sub-<8 hex>` value. Two processes
sharing one client id cause MQTT session takeover, where each new connection kicks the
previous one - which on Windows surfaced as a corrupted selector loop
(`WinError 10038`). Setting `MQTT_CLIENT_ID` explicitly is supported but is the user's
responsibility to keep unique.

### 12.4 Simulator

`simulator/main.py` runs a deterministic drive cycle:

```
OFF (2s) -> STARTING (3s) -> IDLE (10s) -> ACCELERATING (15s) ->
CRUISING (30s) -> DECELERATING (10s) -> IDLE -> ... repeat
```

Physical invariants enforced by `SimulationEngine`:

- Fuel decreases only while the engine is running.
- The odometer increases only when there is speed.
- Engine runtime accumulates whenever the state is not `OFF`.
- Voltage tracks the running / not-running set point.

Scenarios (`SIMULATOR_SCENARIO`):

| Scenario | Effect |
| --- | --- |
| `normal` | Nominal targets |
| `high_temperature` | Coolant / oil targets around 115 / 108 degrees C |
| `low_battery` | Running set point about 11.9 V (vs 13.9), offline about 11.4 V (vs 12.5) |
| `high_engine_load` | Load multiplier 1.5, clamped at 100 % |

The same `SIMULATOR_SEED` reproduces the same run. The simulator is deterministic
test/development tooling, not a device emulator.

### 12.5 Idempotency

REST and MQTT both funnel into `TelemetryService.create_telemetry`:

1. If `source_event_id` is supplied and a row exists, return it.
2. Otherwise insert; on `IntegrityError`, roll back and re-read. If the existing row is
   found, return it (concurrent duplicate). Otherwise raise `DatabaseError`.

---

## 13. Vehicle health intelligence

`app/intelligence/` is a pure, transport-agnostic package: no database, no MQTT, no
API, no model. It consumes `TelemetryPoint(timestamp, values)` and emits a typed,
versioned, JSON-serialisable `HealthContext`.

- `context_schema_version` = `1.1` (added `data_sufficiency`, `provisional`, and the
  provisional `rating`; everything else from `1.0` is unchanged)
- `rule_engine_version` = `1.0`

### 13.1 Pipeline

| Stage | Output |
| --- | --- |
| `statistics.py` | Per-metric mean, median, min, max, IQR, std-dev, coefficient of variation. Never NaN or infinite. |
| `trends.py` | Ordinary-least-squares slope and a normalised slope -> `increasing` / `decreasing` / `stable`. |
| `baselines.py` | Median and scaled MAD (`1.4826 * MAD`) of the vehicle's own history; deviation -> `within` / `elevated` / `depressed`. |
| `rules.py` | Factual `Finding` objects. Never a diagnosis, never a repair instruction. |
| `scoring.py` | Score and status. |
| `context.py` / `engine.py` | Assembly and orchestration, including confidence. |

### 13.2 Supported metrics and units (11)

| Metric | Unit |
| --- | --- |
| `rpm` | RPM |
| `speed` | km/h |
| `engine_load` | % |
| `coolant_temperature` | deg C |
| `oil_temperature` | deg C |
| `intake_air_temperature` | deg C |
| `battery_voltage` | V |
| `fuel_level` | % |
| `throttle_position` | % |
| `engine_runtime` | s |
| `odometer` | km |

### 13.3 Rule thresholds

All centralised in the frozen dataclass `RuleThresholds`:

| Threshold | Value | Applies to |
| --- | --- | --- |
| `coolant_max_warning` | 100.0 | Coolant max in window |
| `coolant_max_critical` | 110.0 | Coolant max in window |
| `oil_max_warning` | 100.0 | Oil max in window |
| `oil_max_critical` | 110.0 | Oil max in window |
| `rapid_temp_rise_celsius` | 8.0 | Coolant or oil rise across the window |
| `battery_min_warning` | 12.0 | Battery minimum |
| `battery_min_critical` | 10.5 | Battery minimum |
| `battery_max_warning` | 15.0 | Over-charge |
| `engine_load_mean_warning` | 40.0 | Engine-load mean |
| `engine_load_mean_critical` | 60.0 | Engine-load mean |
| `rpm_mean_warning` | 4500.0 | RPM mean |
| `fuel_min_warning` | 15.0 | Fuel minimum |
| `fuel_min_critical` | 5.0 | Fuel minimum |
| `gap_multiplier` | 3.0 | Gap detection, times the expected interval |
| `coverage_minimum` | 0.5 | Data-coverage rule |

A fixed `INSUFFICIENT_DATA` rule is emitted when the sample count is below
`HEALTH_MINIMUM_SAMPLES`. The rule engines also emit the top-level
`LIMITED_DATA` rule (`"LIMITED_DATA"`) once a window holds 1..N samples — used to
label provisional assessments without altering the per-finding scoring.

### 13.4 Scoring

```
score = clamp(100 - total_penalty, 0, 100)
```

| Finding severity | Penalty |
| --- | --- |
| `info` | 0 |
| `warning` | 10 |
| `critical` | 30 |

Penalties accumulate **per category**, and each category is capped at
`CATEGORY_PENALTY_CAP = 40`. The response's `score_details` exposes each category's
raw penalty, applied penalty, counts, and whether the cap was hit, so a score is
always explainable rather than a black box.

| Score | Status |
| --- | --- |
| `>= 80` | `healthy` |
| `60 <= score < 80` | `attention` |
| `< 60` | `critical` |
| n/a (no telemetry) | `no_data` |
| n/a (below minimum) | `limited_data` |

Phase 10 distinguishes data state from rating. `health_status` (the column and the
`healthStatus` field) is a **data-state label**: `no_data` when the window is empty,
`limited_data` when 1..(`HEALTH_MINIMUM_SAMPLES`-1) samples exist. Both carry a
**provisional** assessment computed with the normal rules — the provisional rating
(e.g. `healthy`, `critical`) lives in `context_json.provisional_rating` and in
`score_details.status`, **not** in `health_status`. So a vehicle with two hot
samples is `limited_data` (board badge) and `critical` (detail rating), and it never
looks like a confirmed fault from the board, and it is never auto-escalated to an
LLM diagnosis until a full `HEALTH_MINIMUM_SAMPLES` window confirms `critical`.
The 15-minute window is an analysis window, not a minimum wait: the first sample
triggers an immediate provisional assessment and each subsequent one re-frames it.

### 13.5 Confidence

Confidence describes **confidence in the assessment**, not a probability of health. It
is derived from data quality: window coverage, duration, sample sufficiency, and metric
completeness. A low confidence means "there is not enough data to conclude", which is
different from a low score meaning "something is wrong". Under `limited_data`,
confidence is intentionally low (roughly proportional to sample_count /
`HEALTH_MINIMUM_SAMPLES`) and climbs as samples accumulate — the recompute-on-new-data
behaviour makes a vehicle's confidence visibly improve over the first minutes.

### 13.6 Data quality and windows

`POST /health/analyze` with `window_minutes`:

| Setting | Default | Effect |
| --- | --- | --- |
| `HEALTH_ANALYSIS_WINDOW_MINUTES` | 15 | Default window; the API allows 1-1440 |
| `HEALTH_MINIMUM_SAMPLES` | 10 | Below this, `data_sufficiency` is `limited_data` |
| `HEALTH_EXPECTED_INTERVAL_SECONDS` | 1.0 | Basis for gap detection |
| `HEALTH_BASELINE_WINDOW_MINUTES` | 360 | History window for baselines |
| `HEALTH_BASELINE_MINIMUM_SAMPLES` | 5 | Minimum history for a baseline comparison |

Both window loads are bounded by `int(minutes * 60 / expected_interval) * 2 + 100`
rows.

Baselines are evaluated whenever a vehicle has any retained history (5+ samples in the
baseline window), even under `limited_data` — a provisional deviation can therefore be
flagged against historical behaviour rather than global thresholds only.

### 13.6a Background monitor and escalation

`app/services/health_monitor.py` reduces config surface to three knobs:

| Setting | Default | Meaning |
| --- | --- | --- |
| `HEALTH_MONITOR_ENABLED` | `true` | Runs the loop when the API boots |
| `HEALTH_MONITOR_INTERVAL_SECONDS` | **10.0** | Ticks per pass (was 30 s) |
| `HEALTH_MONITOR_MIN_SECONDS` | 60.0 | Floor between consecutive snapshots per vehicle |
| `HEALTH_MONITOR_MAX_VEHICLES` | 25 | Vehicles scanned per pass |

Each pass analyses only vehicles whose telemetry is newer than their last snapshot,
then calls `should_escalate(health_status)` — which is true **only** for `"critical"`.
`unknown`, `no_data`, `limited_data` (even a provisional `critical`) and `attention`
never trigger an LLM diagnosis. With the 10 s tick and 60 s floor, a first snapshot
appears within seconds of a vehicle's first telemetry row (measured live: ~4.7 s).

### 13.7 What this is not

There is no ML model, no learned prior, no forecasting, and no anomaly detection. Every
finding is a statement about observed telemetry within the window.

---

## 14. Agentic reasoning

### 14.1 Graph

Compiled per execution by `build_agent_graph()` so request-scoped tools, LLM service,
and repository are injected via closures.

```
START
  -> supervisor          gather bounded context via VehicleContextTool;
                        decide needs_llm and needs_rag
     |
     +-> rag             conditional: RAG evidence retrieval
     |     -> reason     conditional: LLM call
     |     -> validate   conditional: no context needed, canned grounded reasoning
     |
     +-> reason          conditional: LLM call
     |
     +-> validate
            |
            -> persist   writes agent_diagnoses
            |
            -> END
```

Routing predicates are `should_reason_or_rag` (after `supervisor`) and `should_reason`
(after `rag`). RAG evidence alone is enough to route to reasoning even when telemetry
context is missing; when neither the LLM nor RAG is needed, the supervisor
short-circuits straight to `validate` so the persistence path stays uniform.

### 14.2 Triggers

| Trigger | Invokes LLM | Notes |
| --- | --- | --- |
| `USER_QUERY` | yes | `POST /agent/query` |
| `CRITICAL_TELEMETRY_EVENT` | yes | `POST /agent/events/critical`; identical rule sets inside `AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS` return the existing diagnosis with no extra call |
| `DASHBOARD_LOAD` | **no** | `GET /agent/dashboard`; still persists |

### 14.3 Deterministic control the LLM cannot override

**Severity** (`derive_severity`): the highest-severity finding wins
(`critical > warning > info`). With no findings it falls back to `health_status`
(critical -> critical, attention -> warning, otherwise info). Any severity the model
asserts is clamped to at most the corresponding rule severity.

**Confidence** (`derive_confidence`): `score_confidence * 0.6 + data_factor * 0.4`,
where `data_factor = 0.5 + 0.5 * coverage`, bounded to `[0.05, 0.95]`. A model-supplied
confidence must stay within +/- 0.2 of the deterministic value or be replaced.

**Evidence grounding** (`ground_evidence`): rule ids and metrics absent from the
deterministic context are dropped and recorded as `validation_warnings`. Numeric values
are compared with a 10 % tolerance and de-duplicated.

**Citations** (`build_citations_from_sources`): fabricated citations are removed;
out-of-range and duplicate indexes are dropped with warnings. **Negative grounding**
means zero retrieved evidence produces zero manufacturer claims - the system would
rather say nothing than invent a manual reference.

**Persistence integrity**: the stored response is reassembled from validated state.
No chain-of-thought is persisted.

### 14.4 Prompt contract

`SYSTEM_PROMPT` requires exactly one JSON object, with:

- hypotheses wording-corrected rather than invented;
- severity never exceeding rule severity;
- confidence within 0.2 when no rationale is offered;
- the health context treated as **untrusted data**;
- retrieved documents treated as **data, never instructions**;
- `cited_sources` expressed as 1-based indexes into the supplied evidence list.

### 14.5 Providers and fallback

| Provider | Base URL | Role |
| --- | --- | --- |
| OpenRouter | `https://openrouter.ai/api/v1` | Primary by default |
| Groq | `https://api.groq.com/openai/v1` | Fallback by default |
| Mock | none | Deterministic; the entire test suite runs on it |

Structured output uses
`with_structured_output(DiagnosisContent, method="function_calling", include_raw=True)`.

Retry policy: exponential backoff, up to `LLM_MAX_RETRIES`. The fallback-eligible error
set is `_FALLBACK_ELIGIBLE` in `app/agent/llm_service.py`:
`{TIMEOUT, RATE_LIMIT, CONNECTION, SERVER, UNKNOWN, AUTH}`. `BAD_REQUEST` and
structured-output failures are **not** retried and **not** rerouted, because retrying a
malformed request cannot help. No provider hard-codes a model id; both come from
settings, and missing configuration surfaces as `AgentConfigurationError` at
provider-build time rather than at call time.

### 14.6 Degradation is explicit

If RAG is unavailable, empty, malformed, or the guidance tool reports
`available=False`, the prompt is degraded and the run continues. An RAG outage never
crashes an agent run and never fabricates evidence.

---

## 15. Manufacturer documentation RAG

### 15.1 Gate and laziness

`RAG_ENABLED` (default `true`) is the only behavioural gate. Reading settings never
loads weights. Docling, `sentence-transformers`, and the cross-encoder are all imported
lazily, so `app.rag` stays importable - and the whole hermetic test suite runs - on a
machine that has never downloaded a model. The test suite additionally forces
`RAG_ENABLED=false` and uses stub embedder/reranker adapters.

### 15.2 Ingestion

```
parse -> canonical text -> sha256 hash -> pending version
      -> structure-aware chunk -> embed -> persist -> completed
```

| Property | Behaviour |
| --- | --- |
| Idempotent | Identical canonical text returns `status: "unchanged"`; no duplicate version row |
| Immutable | Changed content mints a new version; old versions and their chunks are never mutated |
| Failure-visible | A failed version keeps `ingestion_status = "failed"` with `error_message`, and only `completed` versions are ever retrieved |
| Retry-safe | Re-ingesting after a failure reuses the version rather than piling up rows |
| Transactional | The admin path commits on success and rolls back on failure explicitly |

### 15.3 Parsers

| Parser | Extensions | Notes |
| --- | --- | --- |
| `DoclingParser` | `.pdf .docx .doc .rtf .pptx .ppt .html .mhtml .xlsx .xls .odt .ods .odp .epub` (14) | Lazy import; **no silent plain-text fallback** - a PDF fails loudly with `RAGParseError` if Docling is missing or conversion fails. Records page buckets, heading-to-page mapping, parser name/version, and Docling version. |
| `PlainTextParser` | `.txt .md .text` (3) | Understands `----- Page 12 -----` markers; strips BOM and zero-width characters. |
| `_UnsupportedParser` | everything else | Deterministic `RAGParseError: no parser registered for '<ext>'` |

**17 accepted extensions in total.** There is no third fallback path.

The canonical intermediate is uniform for both parsers: headings are emitted as
Markdown `# ...` lines, so the structure chunker sees one format regardless of source.

### 15.4 Chunking

`chunk_by_structure` with `CHUNKING_VERSION = "structural-1.0.0"`, target
`rag_chunk_size` (800) and `rag_chunk_overlap` (120). Heading hierarchy becomes
`heading_path`; chunk types are `section`, `continuation`, `preamble`; page numbers are
estimated at roughly 4400 characters per page for parsers without real page data.

### 15.5 Retrieval

```mermaid
flowchart LR
    Q["QueryPlan<br/>VIN + noise stripped"] --> EMB["bge-m3 embed<br/>1024-dim"]
    EMB --> HYB["RagRepository.hybrid_search<br/>dense + FTS lexical"]
    HYB --> FUSE["fusion + dedup<br/>alpha 0.6 dense"]
    FUSE --> TIER["scope tier boost<br/>EXACT_VEHICLE > MODEL > MAKE > GENERIC"]
    TIER --> RR["bge-reranker-v2-m3<br/>top 30, threshold 0.2"]
    RR --> TOP["final top 5<br/>with provenance citations"]
```

- `QueryPlan` strips 17-character VIN-shaped tokens (`\b[0-9A-HJ-NPR-Z]{17}\b`) and
  produces lexical variants.
- Fusion is `rag_hybrid_alpha = 0.6` dense weight, `1 - alpha` lexical.
- Scope tiering is **conservative**: a chunk whose tier is stronger than the query's is
  always admissible (a MODEL-level manual is valid evidence for a specific repair on
  that model), and the boost can let a stronger chunk outrank a weaker one but never the
  reverse.
- Reranking is optional. If the reranker cannot load, `RAGService` logs a warning and
  falls back to hybrid order rather than failing the search.
- Final evidence text is bounded per passage by `rag_evidence_max_chars` (1800).

### 15.6 Admin document management

`AdminRagDocumentService` adds the management surface on top of the same ingestion
pipeline:

| Step | Behaviour |
| --- | --- |
| Filename | Sanitised to a plain basename; path separators or traversal are rejected with 400 |
| Extension | Checked against the parser registry before anything is written; unsupported -> 400 `unsupported document format '.csv'` |
| Empty file | Rejected with 400 |
| Text pre-check | Plain-text uploads must decode as UTF-8, else 400 |
| Size | Streamed to a temp directory under the system temp root with a running byte count; exceeding `rag_max_upload_bytes` -> 413, and the partial file is discarded |
| Transaction | `commit()` on success, `rollback()` on failure, with the failure surfaced as 422 rather than a fabricated success |
| Delete | Transactional cascade over document, versions, chunks, and vectors |

Nothing about document identity is invented for the API layer: the upload form reuses
the ingestion kwargs exactly.

### 15.7 Error taxonomy

`RAGError` and subclasses: `RAGUnavailableError`, `RAGEnabledError`,
`RAGConfigurationError`, `RAGVectorUnavailableError`, `RAGParseError`,
`RAGDocumentNotFoundError`, `RAGDiagnosticsUnavailableError`, plus the upload-specific
`RAGUploadValidationError`, `RAGUploadTooLargeError`, `RAGIngestionFailureError`,
`RAGDocumentUnavailableError`.

---

## 16. Frontend

### 16.1 Application shape

Next.js App Router with three route groups:

| Group | Purpose | Protection |
| --- | --- | --- |
| `(auth)` | Sign in, register | Public; redirects to `/dashboard` when already authenticated |
| `(app)` | Everything else | Client-side guard via `useAuthGuard` |
| `api/session/*` | Session lifecycle route handlers | Server-side only |

`next.config.ts` deliberately uses **no rewrite proxy**: the backend is a separate
origin that already sends the CORS headers this app needs, so data requests go straight
to the API with a bearer token and only the session lifecycle passes through the
server.

### 16.2 State strategy

| State | Mechanism | Lifetime |
| --- | --- | --- |
| Server data (vehicles, telemetry, health, diagnoses, RAG) | TanStack Query | Cached 15 s stale / 5 min GC; cleared at sign-out |
| Session | Zustand (`session-store.ts`) | In memory only |
| Selected vehicle | Zustand + `localStorage` key `dt-selected-vehicle` | Persisted across reloads |
| Theme | `useSyncExternalStore` over `localStorage` key `dt-theme` + `<html>` class | Persisted, synced across tabs |

Query retry policy: no retry for 4xx (a bad request stays bad), up to 2 attempts for
5xx and network failures, no retry for mutations. Polling is opt-in per query; the
telemetry window polls every 20 s with `refetchIntervalInBackground: false`.

### 16.3 Design system

`src/app/globals.css` defines a dark-first "automotive telemetry console" system:

- Surfaces: near-black graphite (never pure black) in dark, cool off-white in light.
- One cool signal accent (`--color-signal-*`, constant across themes).
- A restrained semantic status ramp: `healthy`, `attention`, `critical`, `info`,
  `unknown`, each with a `-soft` variant.
- Tailwind v4 `@theme` tokens for fonts, radii, palette, and two elevation shadows.
- Light theme via a `.light` class that remaps the surface and ink variables, so charts,
  forms, dialogs, and tables all follow automatically.
- Custom utilities: `panel`, `panel-inset`, `blueprint-grid`, `tabular`, `shimmer`,
  `animate-fade-rise`.
- One consistent focus ring on every interactive element; `prefers-reduced-motion`
  disables all animation.

Theme is applied by an inline script in the root layout **before first paint**, which
prevents a flash of the wrong theme, and the provider keeps React in step afterwards.

### 16.4 Error normalisation

`src/lib/api-error.ts` turns both backend error envelopes into one typed `ApiError`
with `status`, `code`, per-field `fieldErrors`, and `rawDetail`. FastAPI's `loc` tuples
are mapped to field names (`body.email` -> `email`), which is what lets the sign-in and
registration forms show per-field messages. Convenience predicates
(`isAuthError`, `isForbidden`, `isNotFound`, `isConflict`, `isValidationError`,
`isRateLimited`, `isServerOrNetwork`) drive UI decisions instead of status-code
scattering.

---

## 17. Frontend routes

18 routes as reported by `next build`. `o` = prerendered static, `f` = server-rendered
on demand.

| Route | Rendering | Auth | Purpose |
| --- | --- | --- | --- |
| `/` | o | - | Redirects to `/dashboard` |
| `/login` | o | public | Sign in; reads `?next=` to return after sign-in |
| `/register` | o | public | Create account and sign in |
| `/dashboard` | o | user | Health, telemetry, and diagnoses for the active vehicle |
| `/vehicles` | o | user | Vehicle registry: list, create, edit, delete |
| `/vehicles/[id]` | f | user | Vehicle overview |
| `/vehicles/[id]/health` | f | user | Health context: score, findings, statistics, charts |
| `/vehicles/[id]/telemetry` | f | user | Live telemetry explorer and table |
| `/vehicles/[id]/history` | f | user | Health snapshot history |
| `/vehicles/[id]/diagnosis` | f | user | Ask the agent; read diagnosis history |
| `/rag` | o | user | Manufacturer-documentation search |
| `/admin/rag` | o | **admin** | Corpus health, upload, document management |
| `/profile` | o | user | Profile and role; sign-out |
| `/api/session` | f | - | Session probe (GET) |
| `/api/session/login` | f | - | Login (POST) and logout (DELETE) |
| `/api/session/register` | f | - | Register and establish session (POST) |
| `/_not-found` | o | - | 404 page |
| `error.tsx` boundary | - | - | Route-level error boundary |

Notes:

- The authenticated chrome lives in `src/app/(app)/layout.tsx` via `AppShell`,
  wrapped in `Suspense` because the shell reads search params.
- `/admin/rag` is prerendered as a static shell; the admin check and the corpus fetch
  both run client-side. This is presentation only - the backend independently returns
  403 for non-admins, and the admin page surfaces that permission error rather than
  hiding the page.
- Every `/vehicles/[id]/*` route shares `VehicleWorkspace`, so switching tabs keeps the
  vehicle header and tab bar mounted.
- `src/app/error.tsx` only catches genuinely unexpected render failures. Expected API
  failures are handled in components with domain-specific empty and error states.

---

## 18. Frontend components

49 of the 94 source files are client components. Grouped by area:

### 18.1 `components/ui/` - design-system primitives

| Component | Purpose |
| --- | --- |
| `button.tsx` | CVA variants/sizes, `asChild` support via Radix Slot |
| `card.tsx` | Panel surfaces |
| `badge.tsx` | Status and count badges |
| `dialog.tsx` | Radix dialog with overlay and focus management |
| `input.tsx` | Labelled input with error state |
| `select-menu.tsx` | Accessible listbox for the vehicle and metric pickers, with focus management and typeahead |
| `tabs.tsx` | Radix tabs for the vehicle workspace |
| `tooltip.tsx` | Tooltip plus the `TooltipProvider` used in the provider tree |
| `pagination.tsx` | Pagination driven by the backend `PaginatedResponse` envelope (`items`, `page`, `page_size`, `total`) |
| `skeleton.tsx` | Loading skeletons, `shimmer` applied through a pseudo-element so one class covers all of them |

### 18.2 `components/layout/`

| Component | Purpose |
| --- | --- |
| `app-shell.tsx` | Sidebar + top bar + skip-link target; hosts the auth guard |
| `nav-items.tsx` | Navigation model with active-route matching |
| `page-header.tsx` | Consistent page title block |
| `user-menu.tsx` | Account menu, theme toggle, sign-out (calls `clearQueryCache()`) |
| `vehicle-selector.tsx` | Vehicle picker; only lists vehicles the backend returned, so it cannot surface another user's vehicle |

### 18.3 `components/health/`

| Component | Purpose |
| --- | --- |
| `health-summary-panel.tsx` | Score, status, confidence, window, data quality |
| `health-visuals.tsx` | Score/status visualisations |
| `metric-tile.tsx` | Headline metric card: latest value plus the min-max band from the analysis window |
| `findings-list.tsx` | Deterministic rule findings from `HealthContextResponse.findings` - rule-engine output, never LLM output |
| `telemetry-chart.tsx` | Recharts time-series with threshold overlays |

### 18.4 `components/telemetry/` and `components/diagnosis/`

| Component | Purpose |
| --- | --- |
| `telemetry-explorer.tsx` | Range selection, auto-refresh, chart/table switch |
| `telemetry-table.tsx` | Raw sample table; columns come from the mirrored `METRIC_UNITS` registry |
| `diagnosis-panel.tsx` | Renders a grounded diagnosis: summary, causes, recommended actions, citations, provenance, and the provider/model used |

### 18.5 `components/vehicles/`

| Component | Purpose |
| --- | --- |
| `vehicles-view.tsx` | Registry table with create/edit/delete |
| `vehicle-form-dialog.tsx` | Create/edit form with client-side validation (VIN upper-casing, year bounds) |
| `vehicle-workspace.tsx` | Shared header and tab bar for the `[id]` routes |
| `vehicle-overview.tsx` | Summary card |
| `vehicle-health-view.tsx` | Health context page body |
| `vehicle-telemetry-view.tsx` | Thin wrapper over the telemetry explorer |
| `vehicle-history-view.tsx` | Paginated snapshot history |
| `vehicle-diagnosis-view.tsx` | Ask-the-agent form plus history |

### 18.6 `components/admin/`

| Component | Purpose |
| --- | --- |
| `admin-rag-view.tsx` | Composes the three panels and gates them on the admin role |
| `admin-rag-health.tsx` | Corpus health; a 403 is surfaced as a legitimate permission state rather than hidden |
| `admin-rag-upload.tsx` | Multipart upload with client-side metadata validation; accepts exactly the 17 parser-registry extensions |
| `admin-rag-documents.tsx` | Document table with filters, version detail, and delete |

### 18.7 `components/rag/`

`rag-search-view.tsx` - query box, optional scoping to the active vehicle, and result
rendering with citations and long-passage truncation. Its central distinction:

| Backend response | UI presentation |
| --- | --- |
| 200 with evidence | Passage cards with citations |
| **200 with `available: false`** | **"No passages matched"** empty state |
| **503** | Retrieval-outage error with a retry affordance |

### 18.8 `components/auth/`, `components/profile/`, `components/states/`, `components/dashboard/`

| Component | Purpose |
| --- | --- |
| `auth-layout.tsx` | Split-screen shell: brand panel on large screens, centred form on small |
| `login-form.tsx` / `register-form.tsx` | Credential forms with per-field validation errors from the backend |
| `profile-view.tsx` | Profile, role display, sign-out |
| `states/feedback.tsx` | Shared `EmptyState`, `ErrorState`, `LoadingState`, skeleton helpers |
| `dashboard-view.tsx` | Composes health summary, metric tiles, chart, and latest diagnosis for the active vehicle |

### 18.9 Tests

| File | Focus |
| --- | --- |
| `src/lib/__tests__/api-client.test.ts` | Bearer handling, renewal, replay-once, abort |
| `src/lib/__tests__api-error.test.ts` | Error-envelope normalisation |
| `src/hooks/__tests__/use-auth-guard.test.tsx` | Bootstrap and redirect behaviour |
| `src/hooks/__tests__/use-vehicle-data.test.tsx` | 404-to-null normalisation, query wiring |
| `src/components/auth/__tests__/login-form.test.tsx` | In-memory token storage, 422 field errors, 401 handling |
| `src/components/rag/__tests__/rag-search-view.test.tsx` | Empty result vs 503 outage, scoping, citations, truncation |
| `src/components/vehicles/__tests__/vehicle-diagnosis-view.test.tsx` | Grounded diagnosis rendering, sanitized 502, non-404 failures |
| `src/components/vehicles/__tests__/vehicle-form-dialog.test.tsx` | VIN upper-casing, year bounds, create payload |
| `src/components/admin/__tests__/admin-rag-view.test.tsx` | Admin composition and states |

---

## 19. Frontend data flows

### 19.1 Request flow

```
component
  -> hook (use-vehicle-data / use-mutations)
     -> service (services/vehicles.ts | rag.ts)
        -> api-client (api.<method>)
           [proactive renewal if the token is known-expired]
           -> fetch(NEXT_PUBLIC_API_URL + path, { Authorization: Bearer <in-memory token> })
              -> 401? -> renewSession() via GET /api/session (single flight)
                         -> success: replay the request once
                         -> failure: setAnonymous(), throw ApiError
           -> ApiError thrown (or payload returned)
     -> TanStack Query caches / invalidates
```

### 19.2 Endpoint mapping

| Service call | Backend endpoint |
| --- | --- |
| `vehiclesApi.list/get/create/update/remove` | `/vehicles`, `/vehicles/{id}` |
| `telemetryApi.list/create` | `/vehicles/{id}/telemetry` |
| `healthApi.latest/analyze/history` | `/vehicles/{id}/health`, `/health/analyze`, `/health/history` |
| `agentApi.dashboard/ask/criticalEvent/history/latest` | `/vehicles/{id}/agent/*` |
| `ragApi.search/health` | `/rag/search`, `/rag/health` |
| `adminRagApi.list/get/upload/remove` | `/admin/rag/documents`, `/admin/rag/documents/{id}` |
| `authApi.session/login/register/logout` | `/api/session*` (proxy) |
| `authApi.me/updateProfile` | `/auth/me`, `/users/me` (direct, bearer) |

### 19.3 Invalidation graph

| Mutation | Invalidates / updates |
| --- | --- |
| Analyze health | Sets `health(vehicle)` directly, then invalidates health history, agent dashboard, and health |
| Ask agent | Latest diagnosis, agent history, agent dashboard |
| Create / update / delete vehicle | Vehicle list and, for update, the single vehicle |
| Create telemetry | Telemetry window keys |

### 19.4 Empty state vs error

Two 404s are normalised to `null` rather than surfaced as failures, because "not yet"
is not an error:

| Endpoint | 404 meaning | UI |
| --- | --- | --- |
| `GET /vehicles/{id}/health` | No snapshot yet | Empty state with a prompt to analyse |
| `GET /vehicles/{id}/agent/diagnoses/latest` | No diagnosis yet | Empty state with a prompt to ask |

Every other failure - including 404 from a different endpoint - is rendered as an error
state with a retry affordance.

---

## 20. User flows

### 20.1 Register

1. `/register` -> `RegisterForm`.
2. `POST /api/session/register` (proxy) -> backend `POST /auth/register` (201, user only).
3. Proxy performs a server-side `POST /auth/login`, writes `dt_at` and `dt_rt`.
4. Proxy returns the created user plus a fresh access token.
5. Client calls `setSession`, invalidates nothing (no prior cache), routes to
   `/dashboard`.
6. If step 3 fails, the proxy returns 201 with a message asking the user to sign in
   manually - the account exists either way.

### 20.2 Sign in

1. `/login?next=...` -> `LoginForm` -> `POST /api/session/login` (proxy).
2. Proxy -> backend `POST /auth/login`; on failure the FastAPI detail is passed through
   so the form can show per-field messages.
3. Proxy writes both cookies and returns the access token, expiry, and user.
4. Client stores the token in memory only and routes to `?next=` or `/dashboard`.

### 20.3 Cold start (page reload with a valid session)

1. `useSessionBootstrap` runs once, asking `GET /api/session`.
2. Proxy validates the access token against `GET /auth/me`; if valid, returns the
   session unchanged.
3. If the access token expired but `dt_rt` is valid, the proxy silently refreshes,
   rewrites both cookies, and returns the new pair.
4. If neither is usable, cookies are cleared and the client sets anonymous.
5. If the backend is unreachable, the proxy answers 503 and the client keeps the
   existing session so a transient network failure does not read as a sign-out.

### 20.4 Working with a vehicle

1. `/vehicles` -> create or select a vehicle. Create attributes ownership server-side.
2. The selected vehicle id is stored under `dt-selected-vehicle`; if it is stale or
   absent, `useActiveVehicleId` falls back to the first vehicle the backend returns, so
   a deep link such as `/dashboard` works on a brand-new account.
3. `/vehicles/[id]/telemetry` polls every 20 s and charts the selected metrics.
4. `/vehicles/[id]/health` shows the latest persisted snapshot. "Analyze health" calls
   `POST /health/analyze`, which persists a new snapshot and returns the fresh context.
5. `/vehicles/[id]/history` pages through `vehicle_health_snapshots`.
6. `/vehicles/[id]/diagnosis` -> "Ask" calls `POST /agent/query`. If no provider is
   configured the API answers 502 with a sanitised detail, which the panel renders as a
   provider problem rather than a crash.

### 20.5 Searching manufacturer documentation

1. `/rag` -> query plus optional make/model/year scoping (pre-filled from the active
   vehicle).
2. `GET /rag/search`; results render with citations and truncation.
3. A 200 with `available: false` shows "No passages matched". A 503 shows a retrieval
   outage with retry. The two are deliberately not conflated.

### 20.6 Sign out

`DELETE /api/session/login` -> proxy revokes the refresh token server-side, clears both
cookies -> client calls `clearQueryCache()` and sets anonymous -> redirect to `/login`.
The client clears its session even if the network call fails.

---

## 21. Admin flows

Admin routes require `role == "admin"`. The client guard is presentation only; the
backend returns 403 for non-admins on `GET /rag/health` and on all four
`/admin/rag/documents` operations.

### 21.1 Corpus health

`GET /rag/health` renders: enabled state, pgvector availability, embedding adapter and
dimension, reranker adapter, and document / version / completed-chunk counts. It never
loads model weights, so the page stays fast.

### 21.2 Upload a document

1. Admin selects a file. The client `accept` list is exactly the 17 parser-registry
   extensions.
2. Metadata form: `canonical` is required (this becomes document identity); make, model,
   year, `year_end`, manufacturer, title, `source_uri`, `source_type`, `document_type`,
   and language are optional.
3. `POST /admin/rag/documents` as `multipart/form-data`. The browser sets the multipart
   boundary; `api-client` deliberately omits `Content-Type` in that case.
4. Response is `status: "ingested"` with `version` and `chunks_created`, or
   `status: "unchanged"` when the identical content is already completed.
5. Failures surface with their real status: 400 unsupported format / invalid filename /
   empty file, 413 too large, 422 ingestion failure, 503 backend unavailable.

### 21.3 Browse and manage documents

1. `GET /admin/rag/documents` pages through the corpus (default 20 per page) with exact
   filters on make, model, year, canonical, and version ingestion status.
2. `GET /admin/rag/documents/{id}` shows identity plus the immutable version history:
   content hash, parser, chunk count, and ingestion status per version. This is where
   a `failed` version is visible rather than hidden.
3. `DELETE /admin/rag/documents/{id}` cascades document, versions, chunks, and vectors
   in one transaction; the document immediately stops appearing in search.

---

## 22. Configuration reference

Three independent settings objects, all `pydantic-settings`, all reading `.env` with
`extra="ignore"` and `case_sensitive=False`.

### 22.1 `app/core/config.py` - `Settings`

| Env var | Default | Notes |
| --- | --- | --- |
| `APP_NAME` | `Digital Twin API` | FastAPI title |
| `APP_VERSION` | `0.1.0` | OpenAPI version |
| `APP_ENV` | `development` | `development` / `local` relax the JWT-secret rule |
| `DEBUG` | `false` | SQL echo / log verbosity |
| `API_V1_PREFIX` | `/api/v1` | Mount point for every route |
| `DATABASE_URL` | **required** | asyncpg DSN |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON array |
| `MQTT_BROKER_HOST` | `localhost` | |
| `MQTT_BROKER_PORT` | `1883` | |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | empty | Passed only when both are set |
| `MQTT_CLIENT_ID` | per-process `dtwin-sub-<hex8>` | Must be unique per process |
| `MQTT_KEEPALIVE` | `60` | seconds |
| `MQTT_QOS` | `1` | |
| `MQTT_TOPIC_PREFIX` | `vehicles` | |
| `MQTT_RECONNECT_MAX_SECONDS` | `30.0` | Backoff cap |
| `MQTT_MESSAGE_RETRY_ATTEMPTS` | `3` | Per-message DB retries |
| `HEALTH_ANALYSIS_WINDOW_MINUTES` | `15` | Default window |
| `HEALTH_MINIMUM_SAMPLES` | `10` | Below this, `data_sufficiency` is `limited_data` (provisional assessment) |
| `HEALTH_EXPECTED_INTERVAL_SECONDS` | `1.0` | Gap detection basis |
| `HEALTH_BASELINE_WINDOW_MINUTES` | `360` | Baseline history |
| `HEALTH_BASELINE_MINIMUM_SAMPLES` | `5` | |
| `JWT_SECRET` | empty | Alias `json_web_token_secret`. Enforced >= 32 chars and non-default when `APP_ENV` is not `development`/`local` |
| `JWT_ALGORITHM` | `HS256` | Whitelisted, not free-form |
| `AUTH_ACCESS_TOKEN_MINUTES` | `20` | Access-token lifetime |
| `AUTH_REFRESH_TOKEN_DAYS` | `30` | Refresh-token lifetime |
| `AUTH_PASSWORD_MIN_LENGTH` | `8` | |
| `AUTH_PASSWORD_MAX_LENGTH` | `72` | bcrypt byte limit |

Derived: `is_debug`, and `sync_database_url` (rewrites the driver for tools that need a
synchronous DSN).

### 22.2 `app/agent/config.py` - `AgentSettings`

| Env var | Default |
| --- | --- |
| `LLM_PRIMARY_PROVIDER` | `openrouter` |
| `LLM_FALLBACK_PROVIDER` | `groq` |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | unset / empty |
| `GROQ_API_KEY` / `GROQ_MODEL` | unset / empty |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60.0` (must be > 0) |
| `LLM_MAX_RETRIES` | `2` (>= 0) |
| `LLM_TEMPERATURE` | `0.1` (0-1) |
| `LLM_MAX_TOKENS` | `1500` |
| `LLM_CONTEXT_MAX_CHARS` | `24000` |
| `AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS` | `300` |
| `RUN_LLM_SMOKE_TEST` | `false` |

### 22.3 `app/rag/config.py` - `RAGSettings`

| Env var | Default | Notes |
| --- | --- | --- |
| `RAG_ENABLED` | `true` | The only behavioural gate |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-m3` | |
| `RAG_EMBEDDING_DIMENSION` | `1024` | Fixed by the pgvector declaration |
| `RAG_EMBEDDING_DEVICE` | `auto` | |
| `RAG_EMBEDDING_BATCH_SIZE` | `16` | |
| `RAG_EMBEDDING_MAX_LENGTH` | `1024` | |
| `RAG_EMBEDDING_NORMALIZE` | `true` | Cosine normalisation |
| `RAG_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | |
| `RAG_RERANKER_DEVICE` | `auto` | |
| `RAG_RERANKER_MAX_LENGTH` | `512` | |
| `RAG_CHUNK_SIZE` | `800` | |
| `RAG_CHUNK_OVERLAP` | `120` | (>= 0) |
| `RAG_RETRIEVAL_TOP_K` | `25` | Candidate fetch |
| `RAG_RERANK_TOP_K` | `30` | Rerank shortlist |
| `RAG_FINAL_TOP_K` | `5` | Evidence cap |
| `RAG_HYBRID_ALPHA` | `0.6` | Dense weight, validated 0-1 |
| `RAG_MIN_RERANK_SCORE` | `0.2` | Validated 0-1 |
| `RAG_MIN_SCORE` | `0.0` | Validated 0-1 |
| `RAG_MAX_DOCUMENT_BYTES` | `52428800` (50 MiB) | Parser-side guard |
| `RAG_MAX_DOCUMENT_PAGES` | `2000` | Parser-side guard |
| `RAG_MAX_CHUNKS` | `20000` | Ingestion guard |
| `RAG_DOCUMENT_ROOTS` | `("data/documents",)` | Restricts CLI ingestion paths |
| `RAG_MAX_UPLOAD_SIZE_MB` | `50` (>= 1) | Admin API ceiling; 413 above it |
| `RAG_QUERY_MAX_CHARS` | `500` | Query leniency guard |
| `RAG_EVIDENCE_MAX_CHARS` | `1800` | Per-evidence prompt cap |

### 22.4 `simulator/config.py` - simulator `Settings`

| Env var | Default |
| --- | --- |
| `SIMULATOR_VEHICLE_ID` | **required** (the simulator refuses to start without it) |
| `SIMULATOR_SCENARIO` | `normal` (`normal`, `high_temperature`, `low_battery`, `high_engine_load`) |
| `SIMULATOR_INTERVAL_SECONDS` | `1.0` |
| `SIMULATOR_SEED` | `42` |
| `SIMULATOR_INITIAL_ODOMETER` | `45231.7` |
| `SIMULATOR_INITIAL_FUEL_LEVEL` | `75.0` |
| `SIMULATOR_INITIAL_ENGINE_RUNTIME` | `1820.0` |
| `SIMULATOR_CRUISE_SPEED` | `60.0` |
| `SIMULATOR_OFF_SECONDS` | `2` |
| `SIMULATOR_STARTING_SECONDS` | `3` |
| `SIMULATOR_IDLE_SECONDS` | `10` |
| `SIMULATOR_ACCELERATING_SECONDS` | `15` |
| `SIMULATOR_CRUISING_SECONDS` | `30` |
| `SIMULATOR_DECELERATING_SECONDS` | `10` |
| `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` / `MQTT_USERNAME` / `MQTT_PASSWORD` / `MQTT_TOPIC_PREFIX` | same platform defaults |
| `MQTT_CLIENT_ID` | per-process `dtwin-sim-<hex8>` |

### 22.5 Frontend environment

| Env var | Default | Scope |
| --- | --- | --- |
| `BACKEND_API_URL` | falls back to `NEXT_PUBLIC_API_URL`, then `http://localhost:8000/api/v1` | **Server-only.** Used by `src/lib/session-server.ts` for the session proxy |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | **Inlined into the browser bundle.** Used by `src/lib/api-client.ts` for data requests |

### 22.6 Documentation gaps found in configuration files

These are real inconsistencies in the repository, recorded rather than corrected:

| Location | Gap |
| --- | --- |
| `backend/.env.example` | Documents `RAG_MAX_UPLOAD_SIZE_MB` but omits every other `RAG_*` setting from section 22.3 (embedding model, chunking, retrieval, ingestion limits). An operator copying `.env.example` gets defaults silently. |
| `backend/app/main.py` | The API description still frames the service as the Phase 1 CRUD API, long after Phases 2-6 shipped. It renders on the Swagger landing page. |
| `backend/app/api/routes/admin_rag.py` | The OpenAPI description lists 13 supported formats and omits `.odt`, `.ods`, `.odp`, `.epub`, all of which the parser registry accepts. The frontend `accept` list is correct (17). |
| `frontend/src/lib/api-client.ts` | `SESSION_ROUTES` includes `/api/session/logout`, which has no route handler. Harmless (it only suppresses bearer injection on a path that is never called through `api`), but misleading: sign-out uses `DELETE /api/session/login`. |

---

## 23. Setup

### 23.1 Prerequisites

| Requirement | Version |
| --- | --- |
| Python | 3.12+ |
| PostgreSQL | 16+ (or a managed instance with pgvector) |
| pgvector extension | Required on the target database for RAG features |
| Node.js | Compatible with Next.js 16 |
| Mosquitto | Only for MQTT ingestion (optional; REST ingestion works without it) |

### 23.2 Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -e ".[dev]"
copy .env.example .env            # Windows; cp on POSIX
# Edit .env: DATABASE_URL at minimum, plus JWT_SECRET for anything but local dev
alembic upgrade head
```

The repository already contains a virtual environment at `backend/.venv`. The system
Python on this machine (`C:\Python314`) does **not** have the project dependencies
installed, so `python -m pytest` fails with `ModuleNotFoundError: asyncpg`. Use
`backend/.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (POSIX).

### 23.3 Frontend

```bash
cd frontend
npm install
copy .env.example .env.local      # Windows; cp on POSIX
```

`NEXT_PUBLIC_API_URL` must point at the backend, and the backend's `CORS_ORIGINS` must
include this app's origin (`http://localhost:3000` by default).

### 23.4 Sample data

`data/documents/toyota_camry_2024_cooling.md` is the sample corpus document. The
simulator expects a vehicle to exist; `scripts/seed_demo_vehicle.py` creates one
idempotently.

---

## 24. Run

### 24.1 Local (no Docker)

Windows launcher: `scripts/dt-start.ps1` prints the resolved DB target (host/port/db,
credentials redacted) and starts broker + API + subscriber + simulator with logs and
pid files under `%TEMP%\dtwin\`. Do **not** pass `--no-reload` to `uvicorn` — the option
does not exist and the process aborts with `Error: No such option`. If the API fails to
boot, check `%TEMP%\dtwin\api.err.log` and that `DATABASE_URL` in `backend/.env` still
points at your intended database (see `app/core/db_target.py`).

```bash
# Terminal 1 - broker (optional, for MQTT ingestion)
mosquitto -c infrastructure/mosquitto/mosquitto.local.conf

# Terminal 2 - API
uvicorn app.main:app --reload            # or: make dev

# Terminal 3 - MQTT subscriber (optional)
python -m app.mqtt.subscriber

# Terminal 4 - seed + simulate (optional)
python -m scripts.seed_demo_vehicle
python -m simulator.main

# Frontend
npm run dev                             # http://localhost:3000
```

### 24.2 Docker Compose

5 services:

| Service | Image / build | Purpose |
| --- | --- | --- |
| `postgres` | `postgres:16-alpine` | Database, healthchecked with `pg_isready`, `pgdata` volume |
| `backend` | built from `Dockerfile` | Runs `alembic upgrade head` then `uvicorn ... --reload` on 8000 |
| `mosquitto` | `eclipse-mosquitto:2` | Credentialed dev broker; the password file is generated **inside** the container from `MQTT_USERNAME`/`MQTT_PASSWORD`, never committed; healthchecked; `mqtt-data` volume |
| `mqtt-subscriber` | built from `Dockerfile` | `python -m app.mqtt.subscriber`, `restart: unless-stopped` |
| `simulator` | built from `Dockerfile` | `python -m simulator.main`, `restart: unless-stopped` |

```bash
docker compose up --build -d     # or: make up
docker compose logs -f           # or: make logs
docker compose down              # or: make down
```

`DATABASE_URL` is overridable, so the same stack runs against a managed PostgreSQL
without a local container. Compose credentials (`postgres`/`postgres`, `mqtt`/`mqtt`)
are development-only and are commented as such.

**The frontend is not in Docker Compose.** It runs via `npm run dev` / `npm run build`
only. There is no `Dockerfile` in `frontend/`.

### 24.3 Makefile targets (25)

`install`, `dev`, `test`, `lint`, `format`, `migrate`, `migration`, `db-check`,
`db-current`, `db-heads`, `db-history`, `db-reset-local`, `shell`, `docker-up`,
`docker-down`, `up`, `down`, `logs`, `seed-demo-vehicle`, `mqtt-subscriber`,
`simulator`, `mqtt-test`, `mqtt-broker`, `agent-llm-smoke`.

**Caveat.** Every target invokes `.venv/bin/...`, i.e. POSIX paths. On Windows they fail
unless run through a POSIX shell (Git Bash, WSL). On native PowerShell/cmd, run the
underlying commands directly (`.venv\Scripts\python.exe -m ruff check .`, etc.). This is
a genuine portability gap in the repository, not a usage mistake.

### 24.4 Backend scripts (8)

| Script | Purpose |
| --- | --- |
| `scripts/check_db.py` | Independent asyncpg connectivity probe; prints server version and TLS status |
| `scripts/seed_demo_vehicle.py` | Idempotently create the fixed demo vehicle |
| `scripts/reset_local_db.py` | Refuse-to-run SQL that drops-recreates the schema **only** against an explicitly named local database; refuses remote/Supabase/`default` targets with exit 1 (DB-target guardrail, Phases 13/14). Run via `make db-reset-local` |
| `scripts/smoke_agent_llm.py` | Live LLM smoke test, gated by `RUN_LLM_SMOKE_TEST=true` |
| `scripts/ingest_documents.py` | Corpus ingestion CLI; real bge-m3 by default, `--stub-embeddings` for deterministic runs |
| `scripts/query_rag.py` | Hybrid search from the CLI with the full scoring trail; `--json`, `--stub`, `--no-rerank`, `--top-k` |
| `scripts/phase5_real_model_smoke.py` | Real BGE-M3 / reranker smoke outside pytest |
| `scripts/phase5_agent_rag_verify.py` | Live end-to-end verifier (idempotent ingestion, scope isolation, negative grounding, prompt-injection defence, citation integrity, `rag_*` persistence, RAG-disabled fallback) |

---

## 25. Testing

### 25.1 Backend

```bash
cd backend
.venv/Scripts/python.exe -m pytest          # Windows
.venv/bin/pytest                            # POSIX
.venv/Scripts/python.exe -m pytest -m mqtt_e2e    # needs a running broker
```

`pyproject.toml` sets `asyncio_mode = "auto"`, `testpaths = ["tests"]`, and
`addopts = "-q -m 'not mqtt_e2e'"`, so the `mqtt_e2e` marker is deselected by default.

Harness behaviour (`tests/conftest.py`):

- Forces `APP_ENV=test`, `DEBUG=false`, `RAG_ENABLED=false`, and points
  `DATABASE_URL` at `TEST_DATABASE_URL` (default
  `postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_test`) **before any
  app model import**.
- **Refuses to start** when the test DSN host looks hosted (`supabase` / `pooler`), so
  destructive fixtures can never hit a shared database.
- Builds the schema from the models, truncates between tests, tears down afterwards.
- Agent tests run entirely on the mock provider; no API key is required.
- RAG tests use stub embedder/reranker adapters; pgvector-gated integration tests skip
  when the local server lacks the extension.

Test layout (40 files):

| Directory | Covers |
| --- | --- |
| `tests/intelligence/` | statistics, trends, baselines, rules, scoring, engine/context assembly |
| `tests/agent/` | settings, providers, error classification, retry/fallback routing, determinism, full agent API |
| `tests/api/` | vehicles, telemetry, vehicle health, health, auth, and an IDOR/authorization matrix |
| `tests/rag/` | chunking, scope, parsers, retrieval select + rerank, service/repository round-trips, agent guidance tool, admin API contracts, admin document integration |
| `tests/services/` | vehicle, telemetry (idempotency + concurrent `IntegrityError`), vehicle health |
| `tests/repositories/` | health snapshot repository |
| `tests/mqtt/` | topics, envelopes (ranges/timezone/unknown fields), parser, client id, publisher, subscriber with mocked MQTT, and a real-broker `mqtt_e2e` suite |
| `tests/simulator/` | telemetry generator state machine, physical invariants, config/env |
| `tests/core/` | config, and JWT secret/algorithm/expiry security rules |

### 25.2 Frontend

```bash
cd frontend
npm run test          # vitest run
npm run test:watch
npm run typecheck     # tsc --noEmit
npm run lint          # eslint .
npm run build         # next build
```

`vitest.config.mts` uses `jsdom`, `globals: true`, the `@` alias, and includes only
`src/**/*.test.ts(x)`. `vitest.setup.ts` registers `jest-dom`, cleans up after each
test, and stubs `ResizeObserver` and `matchMedia` so jsdom can host Recharts and Radix.
`src/test/utils.tsx` provides `renderWithProviders` (retries off, `gcTime` 0), a test
query client, and the `TEST_USER` / `TEST_VEHICLE` fixtures.

ESLint is a flat config combining `eslint-config-next` with
`typescript-eslint`, enforcing `no-explicit-any` as an error and allowing
`console.warn`/`console.error` only. Test files relax non-null assertions and `any`.

### 25.3 Test coverage gaps

| Area | Gap |
| --- | --- |
| Session route handlers | No unit tests for `/api/session`, `/api/session/login`, `/api/session/register` - the highest-value untested frontend surface, since they own cookie security |
| `theme-provider.tsx` | No tests |
| `use-mutations.ts` | No tests for the invalidation graph |
| Most feature components | Only 4 feature components have tests; `dashboard-view`, `vehicles-view`, `admin-rag-documents`, `telemetry-explorer`, `profile-view`, `auth-layout`, `register-form` have none |
| Theme tokens / `globals.css` | Not testable in the current setup |
| Backend `app/services/auth_service.py` | Covered indirectly through `tests/api/test_auth.py` rather than directly |

---

## 26. Verification evidence

Everything below was executed during this inspection on Windows with PowerShell.

### 26.1 Backend

| Check | Command | Result |
| --- | --- | --- |
| Test suite | `.venv/Scripts/python.exe -m pytest -q` | **391 tests: 381 passed, 10 skipped, 0 failed** (with `AUTH_ACCESS_TOKEN_MINUTES` at its default; see 26.3) |
| Lint | `.venv/Scripts/python.exe -m ruff check .` | `All checks passed!` |
| Format | `.venv/Scripts/python.exe -m ruff format --check .` | `175 files already formatted` |
| OpenAPI sync | compare `openapi.json` with live `app.openapi()` | Identical: 23 paths, 30 operations |

The 10 skips are pgvector-gated integration tests: the local `digital_twin_test`
database does not have the pgvector extension. They are covered live by
`scripts/phase5_agent_rag_verify.py` against a pgvector-enabled database.

### 26.2 Frontend

| Check | Command | Result |
| --- | --- | --- |
| Tests | `npx vitest run` | **9 files, 69 tests, all passed** (5.82 s) |
| Typecheck | `npx tsc --noEmit` | Clean, no diagnostics |
| Lint | `npx eslint .` | Clean, no findings |
| Build | `npm run build` | Succeeded; 18 routes prerendered/on-demand as listed in section 17 |

### 26.3 A real finding: two tests fail against a non-default local `.env`

Running the backend suite with the repository's own `backend/.env` produces **2
failures**:

```
FAILED tests/api/test_auth.py::test_login_returns_token_pair
FAILED tests/core/test_security_settings.py::test_settings_accept_strong_secret_in_production
```

Cause: `tests/conftest.py` neutralises `APP_ENV`, `DEBUG`, `RAG_ENABLED`, and
`DATABASE_URL` **before importing the app**, but it does not neutralise
`AUTH_ACCESS_TOKEN_MINUTES`. The local `.env` sets it to `100`, so both tests assert
against a value they never pin:

- `test_login_returns_token_pair` expects `expires_in == 1200` and receives `6000`.
- `test_settings_accept_strong_secret_in_production` expects
  `auth_access_token_minutes == 20` and receives `100`.

Setting `AUTH_ACCESS_TOKEN_MINUTES=20` in the process environment makes both pass,
confirming the cause is configuration leakage and not a code defect. This is a genuine
test-harness gap worth fixing (the harness should pin every timing-sensitive setting,
or the tests should construct settings explicitly rather than relying on ambient
`.env` values).

### 26.4 Live HTTP verification performed earlier in this engagement

| Area | Verified behaviour |
| --- | --- |
| Health | `POST /health/analyze` returns a full context and persists a snapshot; `/health` and `/health/db` reachable |
| Telemetry | Listing and manual ingestion behave as documented |
| Agent dashboard | Returns health context plus latest diagnosis **without** an LLM call |
| Agent query with no provider | Returns an honest, sanitised response rather than a fabricated diagnosis |
| Missing latest health / latest diagnosis | `404`, rendered as an empty state by the frontend |
| RAG health | `rag_enabled: true`, `pgvector_available: true`, embedding dimension `1024`, reranker `BAAI/bge-reranker-v2-m3`, `min_score: 0.2` |
| RAG upload | `.txt` upload via multipart succeeded; identical re-upload returned `unchanged` |
| RAG search | Content from an uploaded document was retrievable with citations |
| RAG format rejection | `.csv` upload -> `400 {"detail":"unsupported document format '.csv'"}` |
| RAG delete | `DELETE` returned `204`; the document then returned `404` |
| Authorization | Admin-only endpoints rejected non-admins; owner scoping rejected non-owners with `404` |

All probe users, vehicles, and documents created for these checks were removed
afterwards; pre-existing rows were preserved.

**Not verified live:** a successful provider-backed LLM diagnosis (no credentials) and
any browser-rendered behaviour (no browser automation available).

---

## 27. Known limitations

### Functional

| Limitation | Consequence |
| --- | --- |
| No scheduler | Health analysis only happens when a client asks. A vehicle can sit idle indefinitely with no fresh assessment. |
| Status messages not persisted | No online/offline history; a vehicle's connectivity is only visible in logs. |
| No ML prediction or anomaly detection | The health engine describes what was measured. It cannot forecast failure or detect novel anomalies. |
| Single-owner vehicles | No household sharing, no read-only delegation. |
| No soft delete | Deleting a vehicle is irreversible and cascades. |
| No password reset, MFA, or email verification | Account recovery is entirely out of band. |
| No REST rate limiting | Brute-force protection on `/auth/login` does not exist at the application layer. MQTT ACLs apply only to the broker. |
| VIN, `status`, `source_type`, `simulation_enabled` immutable over HTTP | Requires direct database access to change. Intentional, but worth knowing. |
| `top_k` for RAG search capped at 20 | Wide exploratory queries must be paged rather than widened. |
| Telemetry bounds are static | Validation is per-schema, not per vehicle model. A metric outside the static bound is rejected even if valid for that vehicle. |
| Agent has effectively one tool | No arbitrary function-calling loop over other APIs. |
| No long-term agent memory | Beyond persisted diagnosis rows, nothing is remembered between runs. |
| Frontend has no offline capability | Every view requires a reachable backend. |

### RAG performance

Observed during live verification:

| Scenario | Time |
| --- | --- |
| Cold RAG search (first call, lazy model load) | **Exceeded 240 s** and had to be abandoned |
| Warm RAG search (models resident) | ~44 s |

Cause: `bge-m3` and the cross-encoder load lazily on first use, and this machine runs
them on CPU. This is not a code defect, but it is a serious operational characteristic:
the first search after a process start or an idle period can take minutes, and there is
no separate inference service, no model pre-warming, and no progress reporting.

### Documentation and configuration gaps

Recorded in section 22.6: `.env.example` omits the core `RAG_*` settings; the Swagger
description in `main.py` is stale; the admin upload description omits four supported
extensions; `SESSION_ROUTES` lists a route that does not exist.

### Tooling gaps

- Makefile targets use POSIX `.venv/bin` paths and do not work on native Windows shells
  (section 24.3).
- The frontend is absent from Docker Compose.
- The backend test harness does not isolate `AUTH_ACCESS_TOKEN_MINUTES` from `.env`
  (section 26.3).

---

## 28. Security posture

### Implemented controls

| Control | Detail |
| --- | --- |
| Password storage | bcrypt with a 72-byte ceiling; minimum length enforced at the schema |
| Refresh token storage | SHA-256 hashes only; raw tokens never persisted or logged |
| Refresh rotation | Single-use; reuse of a revoked token revokes all of that user's tokens |
| JWT signing | HMAC via `JWT_ALGORITHM`, with an algorithm whitelist and expiry bounds |
| JWT secret strength | Rejected at startup if missing, shorter than 32 chars, or a known default, whenever `APP_ENV` is not `development`/`local` |
| Authoritative role checks | Role and `is_active` re-read from PostgreSQL on every request; never trusted from the token |
| Privilege escalation guard | `RegisterRequest` and `UserProfileUpdate` use `extra="forbid"`; `VehicleUpdate` forbids owner, status, source, and VIN |
| Ownership hiding | Unowned resources return 404, never 403, so vehicle existence is not leaked |
| Admin gating | `require_admin` dependency on all four document endpoints and on `GET /rag/health` |
| Refresh-token containment | httpOnly, `sameSite=lax`, path-scoped `/api/session` cookie; never exposed to JavaScript |
| Token containment | Access token in memory only; never in `localStorage` |
| Query-cache isolation | `clearQueryCache()` at sign-out prevents the next user in the same tab seeing the previous account's data |
| Error sanitisation | 500-family responses carry `{"detail": "Internal server error"}`; LLM provider exceptions are mapped to a taxonomy of codes, never raw upstream text |
| Prompt-injection defence | Retrieved documents are inserted as data, never instructions; grounded findings and citations are rebuilt deterministically |
| Upload hardening | Filename sanitisation, extension registry check, byte ceiling enforced while streaming, temp directory, transactional rollback, empty-file and UTF-8 checks |
| Unknown-field rejection | JSON schemas use `extra="forbid"`; the upload form rejects unknown multipart fields with 422 |
| CORS | Default `["http://localhost:3000"]`; must be widened deliberately per deployment |
| Test-harness safety | Refuses to run against a hosted database |

### Deliberate non-controls (documented posture)

| Item | Status |
| --- | --- |
| PostgreSQL row-level security | **Not enabled.** The backend connects with a privileged login and enforces access in application code. RLS should be revisited before exposing the database directly. |
| REST rate limiting | Not implemented; only the broker has ACLs. |
| HTTPS / TLS termination | Not handled by the application; expected from the reverse proxy. Cookies set `secure` only when `NODE_ENV=production`. |
| Secret rotation | No mechanism; `JWT_SECRET` change invalidates all sessions, which is the only lever. |
| Audit log | No security event log. Requests are logged in the standard log format only. |
| Document content sanitisation | Parsed text is stored as data. Rendering safety relies on the frontend, which does not use `dangerouslySetInnerHTML` for corpus content. |

### Live provider behaviour

No provider credentials are configured, so no successful provider-backed diagnosis was
observed. What the code does guarantee, and what was verified against the mock provider,
is enumerated in sections 14.3 to 14.6.

---

## 29. Performance and scaling

### Database

| Setting | Value |
| --- | --- |
| Pool (non-test) | `pool_size=5`, `max_overflow=5`, `pool_timeout=30`, `pool_recycle=1800`, `pool_pre_ping=True` |
| Pool (test) | `NullPool` |
| Pagination caps | 100 vehicles, 500 telemetry samples per page |
| Window row caps | `int(minutes * 60 / expected_interval) * 2 + 100`, applied to analysis and baseline windows |
| Context cap | 24,000 characters into the LLM prompt |
| Evidence cap | 1,800 characters per passage, 5 passages final |

The pool is deliberately small, which suits managed providers with connection limits but
is a bottleneck for a high-concurrency deployment.

### Indexes

| Index | Purpose |
| --- | --- |
| Partial unique `(vehicle_id, source_event_id)` | Telemetry idempotency, enforced by the database |
| `(vehicle_id, generated_at)`, `(vehicle_id, health_status, generated_at)` | Snapshot latest and history |
| `(vehicle_id, created_at)`, `(vehicle_id, trigger_type, created_at)` | Diagnosis latest, history, and trigger filtering |
| HNSW `vector_cosine_ops` on `vector(1024)` | Dense retrieval |
| GIN on `content_tsv` | Full-text lexical leg |
| `(make, model)`, `(manufacturer)` on documents | Scope filters |

### Bounded work

Analysis windows 1-1440 minutes with a capped load; baselines bounded to 360 minutes by
default; context and evidence capped; every list endpoint paginated; the RAG pipeline
caps candidates (25), rerank shortlist (30), and final evidence (5).

### RAG latency

Embeddings are precomputed at ingestion, so search never embeds the corpus. Searches
are index-accelerated. The cost is concentrated in **model loading** (cold start, tens
of seconds to minutes on CPU) and **reranking** of up to 30 shortlist items on every
query.

Known ceiling: embedding and reranker models are loaded once per process and held in
memory. High concurrency would benefit from a separate, pre-warmed inference service.
There is no sharding, no multi-tenant isolation, and no time-series engine.

### Frontend

| Concern | Mitigation |
| --- | --- |
| Duplicate queries | Module-level singleton `QueryClient` per tab |
| Over-fetching | `staleTime` 15 s, `gcTime` 5 min; vehicles `staleTime` 30 s |
| Background polling | `refetchIntervalInBackground: false`, so a hidden tab stops polling |
| 4xx retry storms | No retry for 4xx; capped at 2 for 5xx/network |
| Thundering herd on expiry | Single-flight session renewal shared by all concurrent requests |
| Stale data after sign-out | Full query-cache clear |
| Layout shift / theme flash | Theme applied by a pre-paint inline script; skeletons for loading states |
| Motion sensitivity | `prefers-reduced-motion` disables animation |

---

## 30. Observability and error handling

### Logging

Configured once per process in `app/core/logging.py`:

```
%(asctime)s | %(levelname)-8s | %(name)s | %(message)s
```

`uvicorn.access`, `httpx`, and `httpcore` are quieted. There is **no** JSON formatter;
that remains unimplemented.

### Health and diagnostics surfaces

| Surface | Purpose |
| --- | --- |
| `GET /api/v1/health` | Liveness without a database round-trip |
| `GET /api/v1/health/db` | `SELECT 1`; 503 `degraded` when unreachable |
| `GET /api/v1/rag/health` | Adapters, pgvector availability, corpus counts; never loads weights |
| `GET /docs`, `/redoc`, `/openapi.json` | Contract and interactive exploration |
| Docker `HEALTHCHECK` | `curl` against `/api/v1/health` in the backend image |

### Error contract

Section 9.11 is the authoritative table. Three properties are worth restating because
they are easy to get wrong when integrating:

1. **404 over 403 for ownership.** A non-owner is told the vehicle does not exist.
2. **Degradation is a distinct status, never an empty success.** An unavailable RAG
   backend is 503; an unavailable database is 503 on `/health/db`. The one deliberate
   exception is a RAG *search* that runs successfully and matches nothing, which is a
   200 with `available: false`.
3. **Provider errors are a taxonomy, not a transcript.** `error_code` values are stable
   identifiers (`llm_timeout`, `llm_rate_limited`, `llm_authentication`,
   `llm_provider_unavailable`, `llm_bad_request`, `llm_provider_error`,
   `structured_output_invalid`), and the detail text is sanitised.

### MQTT failure handling

Malformed, unknown-topic, out-of-range, or duplicate messages are logged and skipped.
Transient database errors are retried with a bounded count. The consumer loop never
crashes on bad input.

---

## 31. Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'asyncpg'` when running pytest or uvicorn | Using the system Python. Run `backend/.venv/Scripts/python.exe -m pytest` (Windows) or `.venv/bin/python`. |
| Makefile targets fail on Windows | Every target uses `.venv/bin/...`. Run the underlying commands with `.venv\Scripts\...`, or use Git Bash / WSL. |
| 2 backend test failures (`test_login_returns_token_pair`, `test_settings_accept_strong_secret_in_production`) | Local `.env` sets a non-default `AUTH_ACCESS_TOKEN_MINUTES`. See section 26.3. |
| App starts but `/health/db` returns 503 | `DATABASE_URL` unreachable. Check network/TLS, then `python -m scripts.check_db` (`make db-check`). |
| Supabase connection times out | Prefer the direct `db.<ref>.supabase.co:5432`; use the session pooler only on IPv4-only networks; never transaction mode (asyncpg needs `statement_cache_size=0`); append `?ssl=require`. |
| Startup fails with `JWT_SECRET must be a strong random secret` | Generate one: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. The check is skipped only when `APP_ENV` is `development` or `local`. |
| `JWT_SECRET` error even though it is set | It is shorter than 32 characters or matches a known placeholder. |
| Subscriber crashes or flaps repeatedly on Windows | Two processes share an MQTT client id, causing session takeover (surfacing as `WinError 10038`). Leave `MQTT_CLIENT_ID` unset for the per-process default. |
| Subscriber keeps reconnecting | Broker down or credentials wrong. Check the Mosquitto config and `MQTT_USERNAME` / `MQTT_PASSWORD` against the container ACL. |
| pgvector-gated tests skip | The local test database lacks the extension. `CREATE EXTENSION vector;` or rely on `scripts/phase5_agent_rag_verify.py` against a pgvector-enabled database. 10 skips is the expected local result. |
| Agent endpoints return 502 / 503 / 504 | Provider key missing or invalid, rate limited, or timed out. Check `OPENROUTER_API_KEY` / `GROQ_API_KEY` and the `LLM_*` settings. Smoke test: `RUN_LLM_SMOKE_TEST=true python -m scripts.smoke_agent_llm`. |
| Agent endpoints return 500 `agent_configuration_error` | No usable provider at all - both keys missing. Dashboard and history still work because they do not call the LLM. |
| `GET /rag/health` returns 403 | The caller is not an admin. Promote at the database level; there is deliberately no HTTP promotion path. |
| RAG search returns 503 | `RAG_ENABLED=false`, or the target database has no pgvector, or the reranker/embedder failed to load. |
| First RAG search takes minutes | Cold model load on CPU. Subsequent searches are far faster. Pre-cache `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3` for air-gapped use. |
| RAG search returns 200 with `available: false` | Not an error. Retrieval worked and nothing matched. Widen the query or relax the scope. |
| `400 unsupported document format '.csv'` | `.csv` is not in the parser registry. There are exactly 17 supported extensions; convert the file first. |
| RAG upload returns 413 | File exceeds `RAG_MAX_UPLOAD_SIZE_MB` (default 50). The partial temp file is discarded. |
| RAG upload returns 422 with an ingestion detail | Parsing or embedding failed. The version is stored as `failed` with an error message - inspect it via the document detail endpoint. |
| Login or refresh returns 401 | Refresh tokens are single-use by design. The client must persist and rotate them; reusing a revoked token revokes every session for that user. |
| Vehicle endpoints return 404 for a vehicle the user owns | Check ownership. 404 is deliberate for non-owners. Admins bypass ownership. |
| Health status is `limited_data` | Fewer than `HEALTH_MINIMUM_SAMPLES` in the window, or the DB schema predates Phase 10 (`null`/`unknown` semantics). Ingest more telemetry or widen `window_minutes`. A `limited_data` result is provisional and never escalates. |
| Health score is low but confidence is also low | Low confidence means the data was thin. Treat the score as provisional and gather more samples. |
| Frontend shows "No sessions found" / signs out unexpectedly | The `dt_rt` cookie expired or was cleared. Sign in again. |
| Frontend cannot reach the backend | Check `NEXT_PUBLIC_API_URL` in the browser bundle and `BACKEND_API_URL` on the server; both must point at a backend whose `CORS_ORIGINS` includes `http://localhost:3000`. |
| Frontend returns 503 from `/api/session` | The Next.js server cannot reach the backend. This is reported as "Backend unavailable" precisely so the session is not destroyed. |
| Recharts or Radix components fail in tests | `ResizeObserver` / `matchMedia` stubs live in `vitest.setup.ts`; make sure it is registered as a setup file. |
| `alembic current` is not `b7d9f1e2a3c4` | Migrations are pending. Run `alembic upgrade head`; inspect with `alembic current` / `heads` / `history`. |

---

## 32. Architectural decisions

| Decision | Rationale | Consequence accepted |
| --- | --- | --- |
| Health analysis is a pure function | Makes the most safety-critical logic exhaustively testable with no fixtures | Engine cannot read the database; a service must load and persist |
| Immutable snapshots and immutable document versions | History and provenance must be auditable; an "update" would destroy the record of what was known | Storage grows monotonically; a correction means a new row/version |
| Rule findings are facts, diagnoses are generated | A threshold breach and a mechanical "diagnosis" are different claims, and conflating them is how health systems mislead | Users see two surfaces; findings are never phrased as conclusions |
| Severity and confidence are clamped deterministically | An LLM must not be able to escalate a warning into a critical or claim false certainty | The model's own severity is advisory only |
| Retrieved documents are data, never instructions | Prompt injection through a manual is a real threat | Evidence is quoted, not obeyed |
| Negative grounding | Zero evidence must mean zero manufacturer claims | Some diagnoses answer "I found no documentation for that" |
| 404 instead of 403 for unowned resources | 403 confirms the resource exists | Clients cannot distinguish "missing" from "not yours" - intentional |
| Role and active status re-read per request | Token contents cannot go stale, so a deactivated or demoted account stops working immediately | One extra query per authenticated request |
| Refresh reuse revokes all sessions | Standard theft-detection trade-off: a stolen token is used at most once before detection | A double-submitting client logs itself out; the client therefore rotates carefully |
| No rewrite proxy in Next.js | The backend already sends CORS headers; proxying every request would add latency and a second failure domain | The browser talks to two origins, so CORS must be configured correctly |
| Session proxy only for token lifecycle | Keeps the refresh token out of JavaScript without proxying all traffic | Two code paths for HTTP, which is why `api-client.ts` and `session-server.ts` are separate |
| Register returns a user, not tokens | Keeps the backend contract minimal | The frontend must perform a second call; the proxy does it server-side so the browser makes one request |
| Real LLM output is never persisted verbatim | The stored diagnosis is reassembled from validated state, so unvalidated text cannot be stored | Slightly less "authentic" prose, much higher integrity |
| Client route guards are presentation-only | A frontend guard is a UX affordance, never a security boundary | Every page must still tolerate a 403 or 404 |
| 404 normalised to `null` for latest health/diagnosis | "Not yet" is not an error, and treating it as one produces alarming empty screens | Callers must distinguish `null` from an empty list |
| RAG degradation is explicit | A fabricated empty result treated as truth is worse than an outage | Clients must handle 503 and `available: false` separately |
| Degraded-but-serving database at startup | `/health/db` is the readiness signal; refusing to boot hides the failure | Startup logs a warning rather than exiting |
| Deterministic, seeded simulator | Reproducible end-to-end runs | Not a device emulator |
| Bounded row estimates instead of `COUNT(*)` | Avoids a second full scan on every analysis | Very high-frequency intervals silently truncate to the cap |

---

## 33. Comparison with the historical guide

`backend/docs/DIGITAL_TWIN_COMPLETE_SYSTEM_GUIDE.md` (1,077 lines) remains the most
detailed backend reference in the repository, and its correctness on backend internals
is high: the migration chain, health thresholds, scoring constants, provider fallback
set, RAG pipeline, MQTT behaviour, and simulator dynamics all match the source as
inspected. Its problem is **coverage and staleness**, not accuracy.

### 33.1 What is obsolete or wrong

| Location | Historical claim | Current reality |
| --- | --- | --- |
| Scope note (lines 3-8) | "single authoritative reference for the ... **backend** (Phases 1-6)" | The system now includes a 94-file Next.js frontend. The guide is not a whole-system reference. |
| Section 14, limitations | "**NOT IMPLEMENTED / FUTURE**: ... Phase 8 Next.js frontend" | The frontend is implemented: 18 routes, session proxy, admin console, 69 passing tests. |
| Section 15, phase status | "7 \| (future phases / dashboard) \| **NOT STARTED**" | The dashboard exists at `/dashboard`. |
| Section 3, directory map | `alembic/versions (6)` | There are **7** migrations. (Its own section 5 chain diagram lists all 7, so the guide contradicts itself.) |
| Section 9.3 | "**293 passed**, 7 skipped, 2 deselected" | 381 passed, 10 skipped. |
| Section 16.3 | "**349 collected: 342 passed / 7 skipped**" | 381 passed, 10 skipped. (Also mutually inconsistent with section 9.3.) |
| Section 7.1, route table | Lists 6 route modules | There are **9**: it omits `auth.py`, `users.py`, `admin_rag.py`. |
| Section 7.2, services | `vehicle`, `telemetry`, `vehicle_health` | Also `auth_service.py` and `vehicle_access.py`. |
| Section 7.3, repositories | 5 repositories listed | Also `user_repository.py` and `refresh_token_repository.py`. It also cites `repositories/rag_repository.py`, but the file is `app/rag/repository.py`. |
| Section 16.1, REST reference | 26 operations, no admin document endpoints | The four `/admin/rag/documents` operations are missing from the reference table, even though section 8.3 demonstrates them. |
| Section 8.1 | Contains a corrupted line: `T.Set^  # (PowerShell) set TEST_DATABASE_URL for tests` | A PowerShell instruction that was mangled. Should be `$env:TEST_DATABASE_URL = "..."`. |
| Section 5.5 | "local `digital_twin_test` database has **no pgvector**" | Still true here, and still the reason for the 10 skips. |
| Reference revision | Head `d6a9b1c2e3f4` | Was correct when written; the current head is now `b7d9f1e2a3c4` (rag chunk HNSW embedding index added since). |

### 33.2 What it never covered

| Gap | Now documented in |
| --- | --- |
| The entire frontend: routes, components, hooks, stores, services, design system, theme, error normalisation | Sections 16-21 |
| Session/cookie architecture and the `dt_at` / `dt_rt` split | 10.5 |
| Frontend environment variables (`BACKEND_API_URL`, `NEXT_PUBLIC_API_URL`) | 22.5 |
| Admin RAG document management as a first-class flow | 9.9, 15.6, 21 |
| The admin upload validation and transactional semantics | 15.6 |
| RAG search response semantics (`available` / `reason`) | 9.8 |
| The exact 17-extension parser registry | 15.3 |
| Frontend test suite and results | 18.9, 25.2, 26.2 |
| Measured RAG cold/warm latency | 27, 29 |
| The `.env`-leakage test failure | 26.3 |
| Makefile portability gap on Windows | 24.3 |
| Docker Compose service inventory and the frontend's absence from it | 24.2 |
| Test-coverage gaps | 25.3 |
| The six configuration/documentation inconsistencies | 22.6 |

### 33.3 What it got right and this guide preserves

The historical guide's treatment of the deterministic health engine, the scoring
constants and per-category cap, the confidence semantics, agent determinism and
grounding, the provider fallback-eligible error set, the RAG ingestion and retrieval
semantics, MQTT envelope validation, simulator physical invariants, the security
posture, the HTTP error table, and the troubleshooting matrix were all verified against
the current source and are accurate. Where this guide restates them, it does so with
current measurements and without the stale counts.

---

## 34. Phase status

| Phase | Scope | Status in this repository |
| --- | --- | --- |
| 1 | Foundation: FastAPI, async SQLAlchemy, Alembic, vehicle and telemetry CRUD | Complete |
| 2 | MQTT ingestion: broker, envelopes, subscriber, simulator, idempotency | Complete |
| 3 | Vehicle health intelligence: deterministic engine, snapshots, API | Complete |
| 3.5 | Managed PostgreSQL via configuration (no code change) | Complete |
| 4 | Agentic reasoning: LangGraph supervisor, providers, grounding, persistence | Complete |
| 5 | Manufacturer-documentation RAG: pgvector, hybrid retrieval, agent grounding | Complete |
| 6 | Identity, roles, vehicle ownership: JWT, refresh rotation, bcrypt, IDOR protection | Complete |
| 6.x | Admin RAG document management: upload, list, detail, delete | Complete |
| 8 | Next.js frontend: App Router, session proxy, dashboard, vehicle workspace, RAG search, admin console | Complete |
| 10 | Deterministic health: literal `no_data` / `limited_data` / `healthy` / `attention` / `critical` statuses, provisional rating in detail, recompute-on-data so the first assessment is within seconds, escalation only for confirmed `critical` | Complete, verified live (Phase 10) |
| 12 | Owner-aware marker fix (deployed) | Complete |
| 13/14 | DB-target guardrails: `app/core/db_target.py`, `scripts/reset_local_db.py`, `make db-reset-local`, `.env.example` env-matrix, `dt-start.ps1` target banner | Complete |

Not started anywhere in the tree: PDF report generation, ML prediction or anomaly
analytics, background schedulers, RLS policies, structured JSON logging, and any
time-series engine. Phase 7 was never given a distinct scope in this repository; the
historical guide used it as a placeholder for "dashboard", which now exists.

---

## 35. Final checklist

Use this to re-verify the document against reality after any change. Each item names the
authoritative source.

### Structural facts

| Check | Authoritative source | Expected |
| --- | --- | --- |
| OpenAPI paths / operations | `backend/openapi.json` and live `app.openapi()` | 23 / 30, and the two must agree |
| ORM tables | `app/models/*.py` `__tablename__` | 9 |
| Alembic migrations and head | `backend/alembic/versions/`, `alembic heads` | 8 files, head `b7d9f1e2a3c4` |
| Route modules mounted | `app/api/router.py` | 9 modules |
| Backend route handler prefixes | same | `/health`, `/auth`, `/users/me`, `/vehicles`, telemetry, health, agent, `/rag`, `/admin` |
| Frontend source files / lines / client files | `frontend/src` | 94 / 11,921 (`ts`, `tsx`) / 49 |
| Frontend build routes | `next build` output | 18 |
| Docker Compose services | `backend/docker-compose.yml` | 5 |
| Makefile targets | `backend/Makefile` | 24 |
| Backend scripts | `backend/scripts/` | 7 |

### Behavioural invariants

| Invariant | Where to confirm |
| --- | --- |
| Access JWT lifetime default is 20 minutes | `app/core/config.py` |
| `dt_at` is httpOnly, path `/`, 12 h; `dt_rt` is httpOnly, path `/api/session`, 30 d | `frontend/src/lib/session-server.ts` |
| Unowned vehicle returns 404, not 403 | `app/services/vehicle_access.py` |
| Role and `is_active` re-read from the database per request | `app/dependencies/auth.py` |
| Refresh reuse revokes every token for that user | `app/services/auth_service.py` |
| Telemetry idempotency via partial unique index plus service check | migration `7e38f4f3d70b`, `app/services/telemetry_service.py` |
| Snapshots are never updated | `app/services/vehicle_health_service.py` |
| Scoring: 100 base, info 0 / warning 10 / critical 30, 40 per-category cap, thresholds 80 / 60 | `app/intelligence/scoring.py` |
| `context_schema_version` = `1.1`, `rule_engine_version` = `1.0` | `app/intelligence/models.py` |
| Graph is `supervisor -> (rag) -> reason -> validate -> persist` | `app/agent/graph.py` |
| Fallback-eligible errors are TIMEOUT, RATE_LIMIT, CONNECTION, SERVER, UNKNOWN, AUTH | `app/agent/llm_service.py` (`_FALLBACK_ELIGIBLE`) |
| RAG search: 200 with `available: false` is success; 503 is outage | `app/rag/rag_service.py`, `app/api/routes/rag.py` |
| Exactly 17 accepted upload extensions | `app/rag/parser/docling.py` |
| Only `completed` document versions are retrieved | `app/rag/repository.py` |
| Frontend treats only 503 as a RAG outage | `frontend/src/components/rag/rag-search-view.tsx` |
| Query cache is cleared on sign-out | `frontend/src/stores/query-provider.tsx`, `components/layout/user-menu.tsx` |

### Quality gates

| Gate | Command | Expected |
| --- | --- | --- |
| Backend tests (phase-touched dirs) | `backend/.venv/Scripts/python.exe -m pytest tests/api tests/intelligence tests/services tests/mqtt` | 288 passed, 0 failed (Phase 10, verified) |
| Backend full suite | `backend/.venv/Scripts/python.exe -m pytest -q` | 381 passed, 10 skipped, 0 failed - with `AUTH_ACCESS_TOKEN_MINUTES` at its default (section 26.3); too slow to run inside a tool timeout, run in a terminal |
| Backend lint | `backend/.venv/Scripts/python.exe -m ruff check .` | `All checks passed!` |
| Backend format | `backend/.venv/Scripts/python.exe -m ruff format --check .` | all files formatted |
| Frontend tests | `cd frontend && npx vitest run` | 92 passed |
| Frontend types | `cd frontend && npx tsc --noEmit` | clean |
| Frontend lint | `cd frontend && npx eslint .` | clean |
| Frontend build | `cd frontend && npm run build` | succeeds |

### Known-good state at the time of writing

- Git `HEAD` `3d1aca2`, working tree clean apart from the addition of this document.
- Backend: Phase-10-touched suites (`tests/api`, `tests/intelligence`, `tests/services`,
  `tests/mqtt`) = 288 passed, 0 failed; lint and format clean.
- Frontend: 92 tests passed; typecheck, lint, and build clean.
- Live verification of health, telemetry, agent, RAG, and authorization behaviour had been
  performed earlier in this engagement; probe data was cleaned up afterwards.
- Phase 10 was additionally verified **live against Supabase**: with the API + MQTT
  subscriber + simulator running, a vehicle with zero telemetry produced its first health
  snapshot ~4.7 s after its first telemetry row, with `status=limited_data`,
  `data_sufficiency=limited_data`, `provisional=true`, `provisional_rating=healthy`,
  `score=100`, `confidence≈0.28`, `sample_count=2`. A second run confirmed progression:
  `sample_count` 2 → 7 and `confidence` 0.28 → 0.31 as telemetry accumulated. No
  destructive operations were performed; `reset_local_db.py` was run against a Supabase
  target only to confirm it refuses to execute (exit 1, redacted target).
- Six documentation/configuration inconsistencies are recorded in section 22.6 and are
  intentionally **not** fixed here, because this engagement's scope was documentation
  only.