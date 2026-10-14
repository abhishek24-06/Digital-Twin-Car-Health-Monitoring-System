# Digital Twin — Complete System Documentation

**Date:** 2026-10-14 · **Branch:** `main` · Everything below was verified against source code, manifests, migrations, the live OpenAPI document, or executed test runs. Unverifiable items are labeled **UNVERIFIED**; proposals are labeled **proposal**.

> **Honest scope.** Health assessment is a project-defined deterministic rules system — **not** a machine-learning fault-prediction model, and its thresholds are **not** manufacturer-validated. The LLM explains findings; it does not certify diagnoses.

## 1. Overview

The Digital Twin Car Health Monitoring Platform makes vehicle telemetry observable and explainable. A deterministic driving simulator streams OBD-II-style telemetry over MQTT into FastAPI + PostgreSQL; a rule engine converts telemetry windows into explainable health scores with persisted evidence; a LangGraph agent answers driver questions grounded in that health context plus manufacturer-manual RAG; a Next.js workspace visualises telemetry, health, simulation, alerts, and workflow execution live. JWT auth with per-vehicle ownership guards every endpoint.

## 2. Features and implementation status

| Feature | Status | Where |
|---|---|---|
| Telemetry simulator + MQTT ingestion | Implemented | `backend/simulator/`, `backend/app/mqtt/` → `telemetry_records` |
| Telemetry REST + live SSE streams | Implemented | `POST/GET …/telemetry`, `GET …/telemetry/stream` (newest-first pages, ascending cursor) |
| Deterministic health scoring + snapshots | Implemented | `backend/app/intelligence/` → `vehicle_health_snapshots` |
| Live vs historical analysis | Implemented | `analyze_live_vehicle` (active run + sufficiency gate) vs `analyze_vehicle` (trailing window) |
| Alerts with dedup/auto-resolve | Implemented | `alert_service.py`, `dedup_key = {vehicle}:{rule}`, `alert_events` audit trail |
| Background health monitor | Implemented | 10 s pass, current-session only, escalates definitive criticals |
| RAG ingestion (upload → chunks → embeddings → pgvector) | Implemented | `backend/app/rag/`, admin-only, versioned, hash-deduped re-uploads |
| RAG query (hybrid → rerank → citations) | Implemented | top-30 hybrid, bge-reranker-v2-m3, `min_score` 0.2, verbatim citations |
| AI diagnosis agent | Implemented, provider-gated | LangGraph supervisor + tools, 300 s cooldown dedup, persisted diagnoses; needs OpenRouter/Groq key |
| Workflow Monitor | Implemented | In-memory bus (cap 500) + SSE + `workflow_events` audit table + filterable UI |
| Simulation control | Implemented | Per-vehicle start/stop/restart, scenario + interval controls, pipeline steppers |
| Auth, roles, ownership | Implemented | JWT access (20 min) + rotating refresh (30 d), `user`/`admin`, IDOR-tested |
| ML fault prediction | **Not implemented** | No predictor exists in `app/intelligence` or the agent graph |
| GPU inference | Not implemented | CPU-only; no device plumbing beyond `*_DEVICE` settings |
| Production hosting | Not implemented | Local scripts only; no registry/hosting target in-repo |

## 3. Technology stack (verified from manifests + installed environment)

| Layer | Technology |
|---|---|
| Frontend | Next.js 16.3.7, React 19.3, TypeScript 5.9, Tailwind CSS 4.3, TanStack Query 5, Zustand 5, Recharts 3, Radix UI |
| Backend | FastAPI 0.141.1, Uvicorn 0.53, SQLAlchemy 2.0.54 (async) + asyncpg, Alembic 1.20, Pydantic 2.13.5 |
| Data | PostgreSQL 16 + pgvector 0.5.0 (HNSW), Mosquitto MQTT (QoS 1, no retain) |
| AI | LangGraph 1.2.12 + LangChain, BGE-M3 embeddings (1024-d), bge-reranker-v2-m3, OpenRouter/Groq (60 s timeout, 2 retries) |
| Tests | pytest + pytest-asyncio, Vitest + Testing Library, Playwright |
| Toolchain | Python ≥ 3.12, Node 24 (per CI), Ruff, ESLint, `tsc` |

## 4. Repository structure

```
backend/                 FastAPI app (app/), simulator/, alembic/ (11 migrations), tests/, scripts/
  app/api/routes/        13 routers → 39 paths / 48 ops under /api/v1 (openapi-verified)
  app/intelligence/      engine, rules, scoring, statistics, trends, baselines, context, models
  app/rag/               ingestion, chunking, embeddings, retrieval, reranker, service, repository
  app/agent/             service, graph nodes, tools (vehicle/health/RAG), config, errors
  app/services/          telemetry, health, monitor, alerts, simulation, subscriber, analytics
  app/models/            user, vehicle, telemetry, health_snapshot, alert(+events), agent_diagnosis,
                         rag (documents/versions/chunks), workflow_event, refresh_token
  simulator/             drive-cycle engine, scenarios, MQTT publisher, config
  scripts/               e2e/mqtt backends, ingestion, RAG query/smoke CLIs, pgvector verify, DB reset
frontend/src/            Next.js App Router: app/(app)/ + app/(auth)/, components/, hooks/,
                         services/, lib/, stores/, test/
  app/(app)/vehicles/[id]/  overview, health, simulation, analytics, telemetry, diagnosis, history, alerts
  app/(app)/             dashboard, simulations, workflow, admin/rag, rag, profile
scripts/                 dt-start.ps1 / dt-status.ps1 / dt-stop.ps1 (broker + API :8000 + subscriber)
docs/research/           frozen evaluation protocol, final report, result sets (metrics + figures)
docs/assets/             application screenshots (this doc + README embeds)
data/documents/          sample RAG corpus documents
```

## 5. Architecture

```mermaid
flowchart TB
    SIM["Simulator engine<br/>drive-cycle state machine"] -->|MQTT QoS 1| BRK[("Mosquitto")]
    BRK --> SUB["Subscriber<br/>batch validate + persist"]
    SUB --> DB[("PostgreSQL + pgvector")]
    API["FastAPI (lifespan)"] <--> DB
    API -->|REST + SSE| FE["Next.js workspace"]
    MON["Health monitor (10 s)"] --> DB
    MON -->|definitive critical| AGENT["LangGraph agent"]
    AGENT --> RAG["RAG query"]
    RAG --> DB
    ING["Admin upload"] --> CHUNK["chunk → embed → store"]
    CHUNK --> DB
    BUS["Workflow event bus"] --> FE
```

One asyncio loop per uvicorn worker: monitor task, short-lived DB sessions per tick, subprocess supervisors on threads, CPU-bound model work in worker threads, symmetric lifespan teardown (cancel monitor → stop supervisors → dispose engine). Pool: 5 + 5 overflow, 30 s checkout timeout, pre-ping, recycle.

## 6. End-to-end data flows

### 6.1 Simulator → ingestion → persistence
`SimulationEngine.step()` (`simulator/telemetry_generator.py`) → `TelemetryMessage{event_id, run_id, tz-aware ts}` → topic `{prefix}/{vehicle_id}/telemetry` → subscriber batch (250 msgs / 0.25 s) → parser (topic check, JSON, schema ranges, vehicle cross-check) → `telemetry_records` with sensor keys verbatim, payload ts kept, `created_at` = received time, dedup on `(vehicle_id, source_event_id)`. Invalid rows are logged + skipped with a `TELEMETRY_VALIDATION_ERROR` event; unknown vehicles dropped and counted. Scenarios: `normal`, `high_temperature` (coolant→115 °C, oil→108 °C), `low_battery` (11.9/11.4 V), `high_engine_load` (load ×1.5); 1 s cadence.

### 6.2 Stored telemetry → health → snapshots/alerts
`get_recent_telemetry` (always chronological, bounded) → `_to_points` (11 metrics verbatim) → `compute_data_quality` + `analyze_metrics` (nulls dropped; empty metrics omitted) → `HealthRuleEngine.evaluate` → `score_findings` → `compute_confidence` → `build_context` → snapshot persisted with full `context_json` → `sync_from_snapshot` materializes alerts. Historical: trailing 15-min window, ≥10 samples. Live: active-run rows only, window shrunk to run span, 30-sample/30-s/50%-coverage/15-s-age gate, `persist=False` supported for reads.

### 6.3 Document → ingestion → vector storage
Admin `POST /admin/rag/documents` (pdf/docx/md/txt; hash-deduped re-uploads) → parse (docling/plaintext) → heading + window chunking → metadata attach → BGE-M3 1024-d embeddings → pgvector HNSW, versioned per document.

### 6.4 Query → retrieval → rerank → LLM → citations
`build_plan` → embed query → hybrid dense+lexical top-30 → bge-reranker-v2-m3 cross-encoder (30 pairs) → `min_score ≥ 0.2` filter → guidance assembled from evidence + verbatim citations. Adapters cached process-wide by config; encoding/rerank run in worker threads (`_run_blocking`) so the event loop never stalls. First model load costs seconds-to-minutes on CPU (logged with `elapsed_ms`); inference scales with candidate token length. Reranking is never skipped to save time.

### 6.5 Agent diagnosis
User question (`POST …/agent/query`) or monitor escalation (`…/agent/events/critical`, definitive critical only) → rule-id resolution → cooldown dedup (completed same-trigger diagnosis < 300 s old covering current rules is reused) → supervisor → vehicle/health/RAG tools (each degrades to `available=False` with a reason instead of fabricating) → validated `DiagnosisResponse` persisted. Failures publish `AGENT_ERROR` and surface sanitized 502/503.

### 6.6 API → frontend state → dashboard
Single typed `api-client.ts` (`NEXT_PUBLIC_API_URL`, bearer, one-flight 401 renewal) → `services/*.ts` → TanStack Query hooks (5–20 s polls, 404→null) + `EventSource` stream hooks (id-deduped newest-first buffers, backoff reconnect) → components. Charts re-sort newest-first rows to chronological with per-unit axes (rpm isolated); sparklines chronological; skeleton/empty/error/stale states everywhere; no-data is never rendered as healthy.

### 6.7 Workflow events → monitoring UI
Every pipeline stage emits typed events (workflow/stage/status/message/ids/duration/sanitized metadata) to a bounded bus (500 events, 50 subscribers, 15 s heartbeats) + durable `workflow_events` table. The monitor page filters by category with toolbar AND-semantics; model weight loads log durations for slow-query diagnosis.

### 6.8 Auth → authorization → ownership
Register/login → JWT access + rotating hashed refresh (reuse detection revokes family) → bearer on all `/api/v1` except login/register/health probes → `ensure_vehicle_access` per vehicle/document/alert → RAG ingestion restricted to `admin`. Cross-account access returns 403/404 without leaking existence (IDOR-tested).

## 7. API reference (39 paths / 48 operations, `/api/v1` prefix)

| Area | Endpoints |
|---|---|
| Service | `GET /health`, `/health/db`, `/health/deployment` |
| Auth | `POST /auth/{register,login,refresh,logout}`, `GET /auth/me`, `PATCH /auth/password` |
| Users | `GET/PATCH /users/me` |
| Vehicles | `GET/POST /vehicles`, `GET/PATCH/DELETE /vehicles/{id}` |
| Telemetry | `POST/GET /vehicles/{id}/telemetry`, `GET …/telemetry/stream` (SSE) |
| Health | `POST …/health/analyze`, `GET …/health` (latest), `GET …/health/history`, `GET …/health/live` |
| Analytics | `GET …/historical-analytics` (ranges, buckets, gaps, run segments) |
| Agent | `POST …/agent/query`, `POST …/agent/events/critical`, `GET …/agent/dashboard`, `GET …/agent/diagnoses`, `GET …/agent/diagnoses/latest` |
| Simulation | `GET/POST …/simulation`, `POST …/simulation/restart`, `GET /simulations` |
| RAG | `GET /rag/search`, `GET /rag/health` |
| Admin RAG | `POST/GET /admin/rag/documents`, `GET/DELETE /admin/rag/documents/{id}` |
| Alerts | `GET …/alerts`, `GET …/alerts/{id}`, `POST …/alerts/{id}/acknowledge`, `POST …/alerts/{id}/resolve` |
| Workflow | `GET /workflow/events/recent`, `GET /workflow/events/stream`, `GET /workflow/state`, `GET /workflow/status` |

All errors are `{detail}` envelopes (arrays for 422); DB failures return generic 500s; auth failures 401/403; rate limiting 429 with `Retry-After`.

## 8. Data models and migrations

`users` → `vehicles` (owner, unique VIN) → `telemetry_records` (11 nullable sensors, tz `timestamp` + `created_at`, `source_event_id`, `simulation_run_id`) → `vehicle_health_snapshots` (score/status/confidence + full `context_json`) → `agent_diagnoses`; `vehicles` → `alerts` (`dedup_key` index) → `alert_events`; RAG: `rag_documents` → versions → `rag_chunks` (HNSW embedding); `workflow_events` audit table; `refresh_tokens` (hashed, revocable). 11 Alembic migrations from initial schema through identity, snapshots, RAG/pgvector, alerts, and workflow audit.

## 9. Health intelligence (exact)

**Sensors and units:** rpm (RPM), speed (km/h), engine_load (%), coolant/oil (°C), battery (V), fuel (%), intake (°C), throttle (%), runtime (s), odometer (km). Only coolant, oil, battery, load, rpm, fuel have rules — speed, intake, throttle, runtime, odometer are display-only.

**Rules** (`RuleThresholds`, all project-defined): coolant max >110 critical / >100 warning; oil max same; battery min <10.5 critical / <12.0 warning, max >15.0 warning; load mean >60 critical / >40 warning; rpm mean >4500 warning; fuel min <5 critical / <15 warning; rapid coolant/oil rise (last−first ≥ 8, n≥3) warning; gap >3×interval and coverage <0.5 informational. At-threshold values do not fire (except rapid-rise at exactly 8.0).

**Scoring:** start 100; info 0 / warning 10 / critical 30 per finding, summed per category, each category capped at 40; `score = round(100 − total, 2)` clamped [0,100]; status ≥80 healthy, ≥60 attention, else critical, `None` → unknown. Worked example: coolant critical (30) + oil/rapid×3 warnings (10 each), all `temperature` = 60 → capped 40 → **60.0/attention** — reproduced live by the `high_temperature` simulator and visible in `docs/assets/vehicle-dashboard-score-60-attention.png`.

**Confidence/coverage:** coverage = present/expected samples (capped 1.0); confidence = `0.10 + 0.90·(0.30·coverage + 0.25·duration + 0.25·sufficiency + 0.20·completeness)` — trust in the evidence, **not** accuracy (a fully-observed critical scores ~0 at confidence 1.0).

**Sufficiency paths:** 0 samples → `no_data` (no score, no escalation); below minimum or failed live gate → `limited_data` + provisional rating (provisional alerts only, never agent escalation, no auto-resolve until definitive). Stopped vehicles are skipped, never re-scored. Failed evaluations persist nothing; the previous timestamped snapshot remains latest.

**Alerts → agent:** warning/critical non-data findings → alerts (recurrence folds into `{vehicle}:{rule}` with occurrence counts and audit events; severity changes recorded); definitive `critical` only → agent (300 s cooldown dedup; failures isolated with error events).

## 10. RAG and AI details

Documents: pdf/docx/md/txt (docling + plaintext), structure-aware chunking, BGE-M3 1024-d, pgvector HNSW hybrid search, bge-reranker-v2-m3 over 30 candidates, threshold 0.2, verbatim citations with provenance. Providers: OpenRouter primary, Groq fallback, 60 s timeout, 2 retries; unconfigured provider → explicit 503/degraded paths, never silent empties. Defenses: evidence-only tool contracts (documents never become instructions), descriptive-not-diagnostic rule text, metadata redaction, sanitized errors. Known cost: first weight load + CPU inference (tens of seconds to minutes); mitigated by process-wide caching + worker threads, never by skipping rerank.

## 11. Frontend details

Routes: `/dashboard`, `/vehicles` + per-vehicle `overview, health, simulation, analytics, telemetry, diagnosis, history, alerts`, `/simulations`, `/workflow`, `/admin/rag`, `/rag`, `/profile`, `/login`, `/register`. Eight vehicle tabs render independently against live endpoints (e2e-verified incl. a mock-LLM diagnosis and a zero-console-error sweep). Charts map every sensor field to its unit/axis/precision (rpm isolated); tables show full timestamps; dialogs (add-vehicle, alert detail with evidence + audit history) validated client-side against backend bounds. State: TanStack Query + SSE hooks + Zustand session. Accessibility: icon+text+colour status triples, labeled controls, keyboard-dismissable menus.

## 12. Authentication and security

Env-only secrets (`.env` git-ignored; no hardcoded credentials in `backend/app`); bcrypt passwords; rotating refresh with reuse detection; role + ownership checks incl. admin-only ingestion; auth rate limiting; CORS allowlist defaulting to localhost:3000; redacted workflow metadata; no auth-header logging; generic 500s; test suites fail closed to loopback disposable databases (`digital_twin_test`, `digital_twin_browser_test`, MQTT harness DB). `npm audit --omit=dev` reports 2 high advisories (Next.js image-optimization SSRF; source-map-js event-loop DoS) with fixes available — apply in a maintenance window.

## 13. Configuration (placeholder values only)

Copy `backend/.env.example` → `backend/.env`. Key groups: `DATABASE_URL` (e.g. `postgresql+asyncpg://user:pass@localhost:5432/digital_twin`), `JWT_SECRET` (long random), `MQTT_*` (host/port/credentials/qos), `SIMULATOR_*` (vehicle id, scenario, interval, seed), `HEALTH_*` (window, minimums, baselines, live-gate bounds, monitor cadence), `LLM_*` (providers, models, timeout), `RAG_*` (models, chunking, retrieval top-k, thresholds), `CORS_ORIGINS`. Frontend: `NEXT_PUBLIC_API_URL` + `BACKEND_API_URL` (e.g. `http://localhost:8000/api/v1`) via `frontend/.env.local`.

## 14. Local setup, testing, simulator

```powershell
cd backend; python -m pip install -e ".[dev]"   # + ".[rag]" for real model inference
Copy-Item .env.example .env                     # fill placeholders, see §13
alembic upgrade head                            # fresh dev DB (needs pgvector ext)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# or: .\scripts\dt-start.ps1  (broker + API + subscriber; dt-status/dt-stop)
cd ..\frontend; npm install   # CI: npm ci on Node 24
npm run dev                   # :3000
# tests (isolated DBs only — never production):
cd ..\backend; .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check .; .\.venv\Scripts\python.exe -m ruff format --check .
cd ..\frontend; npm run typecheck; npm run lint; npm run test; npm run test:e2e
```

### MQTT integration tests (isolated broker + disposable DB)

`make mqtt-integration` (`backend/scripts/run_mqtt_integration.py`) runs the Phase C suite against a real Mosquitto on a loopback free port (`make mqtt-broker` uses `infrastructure/mosquitto/mosquitto.local.conf`) and a dedicated disposable database. `DT_MQTT_TEST_DATABASE_URL` must be set explicitly (default: loopback `digital_twin_mqtt_test`) or the suite skips; non-loopback hosts or other database names fail closed. Markers `mqtt_e2e`/`mqtt_integration` are excluded from the default pytest run (`addopts`).

Simulator: `SIMULATOR_SCENARIO=normal|high_temperature|low_battery|high_engine_load`, or drive per-vehicle runs from Simulation Control (start/stop/restart, scenario + interval). Docs: live OpenAPI at `:8000/docs`.

## 15. Evaluation and analysis (synthetic — not real-world validation)

The frozen protocol (`docs/research/accuracy_evaluation_plan.md`) evaluates the deterministic pipeline on harness-injected fault scenarios over disposable infrastructure, with every quantity tagged MEASURED / SIMULATED / NOT EVALUABLE. Headline results (`docs/research/evaluation_final_report.md`):

| Question | Result |
|---|---|
| RQ1 fault detection (steady view) | accuracy / macro-F1 **1.000** over 20 episodes; normal control raised 0 alert-worthy findings |
| RQ1 full (warm-up-inclusive) view | accuracy **0.250** — cold-start warm-up trips rapid-rise rules in every episode incl. control (reported, not suppressed) |
| RQ2 health separation | ROC-AUC **1.000** (anomaly vs normal); no regression metrics (no independent continuous reference) |
| RQ3 alerts | episode recall 100% (9/9), precision 75%; 0 duplicate rows; TTR 30 s; publish→alert p50 21.8 ms |
| RQ4 latency | publish→persist p50 3.9 ms; engine analyse p50 1.2 ms; monitor pass p50 16.1 ms |
| RQ5 AI-diagnosis correctness | **NOT EVALUABLE** — no expert-labelled reference diagnoses exist |
| RQ6 robustness | 10/10 injected-fault cases (duplicates, gaps, malformed payloads, DB failure, broker restart) |

![Health scores separate cleanly by injected fault family in the steady view](docs/research/results/synthetic-eda-v1/figures/fig06_health_scores.png)
*Health scores by injected family (steady vs full view): thermal episodes score 60/attention; the full view shows warm-up sensitivity.*

![Detection confusion: perfect on steady view, collapsed on full view](docs/research/results/synthetic-eda-v1/figures/fig07_rq1_confusion.png)
*Detection confusion by view: perfect diagonal on steady (acc 1.0); everything collapses to “thermal” on full (acc 0.25) from cold-start rapid-rise transients.*

![Pipeline latency distributions in milliseconds](docs/research/results/synthetic-eda-v1/figures/fig09_latency.png)
*Wall-clock pipeline latencies (log scale, ms): ingest, engine analysis, monitor pass (n=180), publish-to-alert (n=9).*

Full figures: `docs/research/results/synthetic-eda-v1/figures/` (11 plots) and `docs/research/results/synthetic-pipeline-v1/figures/`; metrics + provenance JSON beside each report. None of this establishes real-world accuracy — the reference is the injected scenario.

## 16. Troubleshooting

“Cannot reach the Digital Twin API” → backend down or wrong `NEXT_PUBLIC_API_URL`. First diagnosis slow → model weights loading (watch for `weights loaded … elapsed_ms`) + CPU inference. `alembic` failing on `vector` → install pgvector. Subscriber “not running” → broker host/port. RAG 503 → disabled or weights missing. E2E “another dev server” → Next.js allows one dev server per dir (suite boots its own; use `E2E_REUSE_SERVERS=1`). No-data states render as “No report yet”/“No data”, never as healthy.

## 17. Current limitations

Project-defined (non-manufacturer) thresholds; heuristic score, not a calibrated probability; no ML prediction; 4 of 19 findings unreachable via simulator (rpm>4500, fuel bands, battery critical); CPU-only slow rerank on full-length chunks; single-worker in-memory bus; `ruff format --check` currently failing (34 files); no coverage gate, downgrade-migration tests, load harness, or SLOs; no production hosting target; no license/contributing files (confirm with owner).

## 18. Roadmap (proposals, not commitments)

Patch npm advisories; `ruff format` (or gate decision); align REST/MQTT validation; exact-boundary + cooldown regression tests; unique alert-dedup constraint + scope guard (needs migration + approval); isolated load harness with SLOs; disposable-corpus RAG retrieval E2E; manufacturer-threshold calibration against real vehicle data; inference service/GPU path; multi-worker bus/cache.
