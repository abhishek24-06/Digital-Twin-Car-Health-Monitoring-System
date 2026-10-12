# Digital Twin — Implementation Roadmap

Tracks the phased implementation of `docs/PRODUCT_SPECIFICATION.md` against the
live working tree. Updated at each phase gate. No phase silently proceeds.

## Phase 0 — Baseline and implementation plan  ✅ complete (no code changed)

Baseline (read-only, this working tree):

- Branch `main`; HEAD `3f53a89`. Working tree carries the user's uncommitted
  live/historical-separation feature (backend + frontend + tests). Treat as
  user-owned; do not revert.
- Health API (`backend/app/api/routes/vehicle_health.py`):
  - `POST /api/v1/vehicles/{id}/health/analyze` → `analyze_vehicle_for_user`
    → `VehicleHealthService.analyze_vehicle` (windowed, **no run filter**,
    persists a snapshot).
  - `GET  /api/v1/vehicles/{id}/health` → latest persisted snapshot
    (`get_latest_for_user` → `get_latest`), any scope/run.
  - `GET  /api/v1/vehicles/{id}/health/history` → paginated snapshots.
  - `GET  /api/v1/vehicles/{id}/health/live` → `analyze_live_vehicle_for_user`
    → `analyze_live_vehicle` (active-run only; persists a snapshot on GET).
- Live contract: `LiveHealthStatusResponse` (`backend/app/schemas/vehicle_health.py`)
  and `useLiveHealth` (`frontend/src/hooks/use-vehicle-data.ts`). Already used
  by the Simulation tab (`vehicle-simulation-view.tsx`).
- Simulation lifecycle: `SimulationManager` (in-memory `_instances`, `uuid4`
  run id per spawn, `active_run_id`, `get_status`); no `simulation_runs` table.
- Schema: telemetry has `simulation_run_id` (nullable) + partial unique index
  (migration head `c3f7a2d5e9b1`).
- Historical analytics: `historical_analytics_service.py` +
  `historical_analytics.py` aggregate over an explicit range and segment runs.

Confirmed defects relevant to Phase 1:

1. The **Health tab** (`vehicle-health-view.tsx`) reads `GET /health` (latest
   *historical, run-mixed* snapshot) and presents it as the current health,
   instead of the live current-run contract.
2. `HealthSummaryPanel` shows an "Analysis window" selector defaulting to `60`
   next to a snapshot whose actual window may be `1440` min — a selector that
   implies the displayed report changed when no request ran.
3. `POST /health/analyze` builds an assessment with **no run filter**, so a
   mixed-run window can be persisted and later served as "latest".
4. No field marks an assessment's scope (current-session vs historical), so
   consumers cannot tell them apart without reading `simulation_run_id`/
   `live_sufficiency`.

Phase 0 checklist (mapped to existing files) — all items are Phase 1 work:

- [x] Add explicit assessment scope (`current_session` | `historical_window`) to
      `app/intelligence/models.py` + `context.py` + `schemas/vehicle_health.py`.
- [x] Mark `POST /health/analyze` and `GET /health` as historical in
      `app/api/routes/vehicle_health.py` summaries/descriptions.
- [x] Point the Live Health tab at `GET /health/live`
      (`frontend/.../vehicle-health-view.tsx`) and render the honest live states.
- [x] Remove the misleading window selector from the live view; label the
      historical selector in `health-summary-panel.tsx` (requested vs report
      window) and add a scope badge.
- [x] Rename the tab label to "Live Health" (`frontend/.../nav-items.tsx`).
- [x] Add regression tests (backend isolation; frontend live states).

## Phase 1 — Correctness and run isolation  ✅ implemented (stopped at gate)

Report appended at the end of this file. Not committed.

## Phase 2 — Persistence, workflow observability, security  ✅ implemented (stopped at gate)

Report appended at the end of this file. Not committed.

## Phase 3 — Persistent alerts  ✅ implemented (stopped at gate)

Report appended at the end of this file. Not committed.

## Phase 4 — Finalize the eight-tab product  ✅ implemented (stopped at gate)

Report appended at the end of this file. Not committed.

## Phase 5 — Full-system acceptance  ✅ implemented (stopped at gate)

---

## Phase 1 report — Correctness and run isolation (appended at gate)

**Status:** implemented; stopped for review. Branch `main` @ `3f53a89`, all work
uncommitted. No phase proceeds without approval.

### What changed

Scope is now explicit and honest end-to-end.

- **Assessment scope.** `backend/app/intelligence/models.py` gained
  `AnalysisScope = Literal["current_session", "historical_window"]` and a
  `analysis_scope` field on `HealthContext` (default `historical_window`);
  `CONTEXT_SCHEMA_VERSION` bumped `1.1` → `1.2`. `build_context()` sets
  `current_session` **iff** a live sufficiency outcome is present
  (`live_sufficiency is not None`) — i.e. the assessment came from the
  active-run path — otherwise `historical_window`. Surfaced on
  `HealthContextResponse` (`backend/app/schemas/vehicle_health.py`). Legacy
  (pre-1.2) snapshots deserialize with the default, so an old record can never
  be surfaced as current.
- **Historical endpoints made explicit.** OpenAPI summaries/descriptions of
  `POST /health/analyze` and `GET /health`
  (`backend/app/api/routes/vehicle_health.py`) now state they are historical
  (windowed, run-mixed) reports; the live current-session contract is
  `GET /health/live` alone. Route behaviour is unchanged — only the contract
  docs and the new response field.
- **Live Health tab rewired.** `frontend/src/components/vehicles/vehicle-health-view.tsx`
  consumes `useLiveHealth` (the `GET /health/live` contract) instead of
  `GET /health`. It renders the shared live-status body (simulator state,
  freshness, run id, samples/duration/coverage vs required, newest-sample age,
  insufficiency reasons) and the deterministic assessment sections **only when a
  definitive current-run assessment exists**. With no active run (or when
  collecting/stale) it shows an honest "no current-session assessment" state —
  never a stale historical score.
- **Misleading selector removed / relabelled.** The live view has no window
  selector. `frontend/src/components/health/health-summary-panel.tsx` (Overview
  & Dashboard) keeps the request control but labels it **"Historical report
  window"** and separates it from the report actually shown: a scope badge plus
  a "This report" block (scope / window boundaries / generated time / run id,
  or "legacy / mixed scope"), stating the control only affects the next
  generated report.
- **Shared component.** New `frontend/src/components/health/live-health-status.tsx`
  (`LiveHealthStatusBody`), extracted from the Simulation view and reused by
  both Simulation and Live Health so both tell the same story.
- **Tab renamed** "Health" → "Live Health"
  (`frontend/src/components/layout/nav-items.tsx`); frontend types gained
  `AnalysisScope` and optional `analysis_scope` (`frontend/src/types/api.ts`).

### Migrations

**None.** Scope lives inside the existing `HealthSnapshot.context_json`; the
schema version is carried in that JSON. No DB migration, no table/column change,
and **no deletion or rewrite of historical data, snapshots, or telemetry**.

### Files changed (Phase 1 only)

Backend: `app/intelligence/models.py`, `app/intelligence/context.py`,
`app/schemas/vehicle_health.py`, `app/api/routes/vehicle_health.py`.
Backend tests: `tests/intelligence/test_engine.py`,
`tests/api/test_vehicle_health.py`,
`tests/services/test_vehicle_health_service.py`,
`tests/services/test_health_monitor_service.py` (timestamp-anchoring fix only).
Frontend: `src/types/api.ts`, `src/components/layout/nav-items.tsx`,
`src/components/health/health-summary-panel.tsx`,
`src/components/health/live-health-status.tsx` (new),
`src/components/vehicles/vehicle-health-view.tsx`,
`src/components/vehicles/vehicle-simulation-view.tsx`,
`src/components/vehicles/__tests__/vehicle-health-view.test.tsx`.
Docs: `docs/PRODUCT_SPECIFICATION.md` (new), `docs/IMPLEMENTATION_ROADMAP.md` (new).

### Regression tests added

- `tests/services/test_vehicle_health_service.py::test_analyze_live_ignores_legacy_and_old_run_outliers`
  — a live analysis with `exclude_run_id` and an old-run/legacy outlier present
  yields a current-session assessment that counts only active-run rows.
- `tests/api/test_vehicle_health.py::test_live_uses_only_active_run_over_api`
  — over HTTP, `GET /health/live` isolates the active run and returns
  `analysis_scope == "current_session"`; the historical endpoints return
  `"historical_window"`.
- Updated three `context_schema_version == "1.1"` assertions to `1.2` and added
  an `analysis_scope` assertion in `tests/intelligence/test_engine.py`.
- `tests/services/test_vehicle_health_service.py` fixture `_ingest_run_window`
  and `tests/services/test_health_monitor_service.py` fixture `_ingest_run` now
  anchor each sample's timestamp to its own write moment (oldest first) so the
  newest sample is always fresh. Fixes a test-harness timing bug: against this
  test DB a 40-row insert loop takes ~16s, so the previously fixed pre-loop
  `now` anchor tripped the 15s live freshness bound
  (`limited_data` instead of `healthy`) — a pre-existing flake that also hit the
  new isolation test and the monitor's live-run test. Product code unchanged.
- `frontend/.../vehicle-health-view.test.tsx` rewritten against `useLiveHealth`
  (6 cases incl. no active session, fresh current-session with scope, stale).

### Tests executed (exact commands + results)

- Targeted backend:
  `python -m pytest tests/api/test_vehicle_health.py
  tests/services/test_vehicle_health_service.py tests/intelligence/test_engine.py
  -q -p no:cacheprovider` → **passed** (added tests included).
- Targeted frontend:
  `npx vitest run src/components/vehicles/__tests__/vehicle-health-view.test.tsx
  src/components/vehicles/__tests__/vehicle-simulation-view.test.tsx`
  → **2 files, 9 tests passed**.
- Types/lint: `npx tsc --noEmit` → **exit 0**; `npx eslint <changed files>` →
  **exit 0**.
- Full backend:
  `python -m pytest -q -p no:cacheprovider` → **672 collected; 662 passed,
  10 skipped, 0 failed**.
- Full frontend: `npx vitest run` → **22 files, 154 passed, 0 failed**
  (run without the backend suite concurrently).

### Acceptance criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Seeded legacy + two runs proves current health uses only the active run | Pass (service + API regression tests) |
| 2 | Old-run/NULL rows don't affect current stats/score/confidence/coverage/trends/findings/alert eligibility | Pass (live path filters by active `simulation_run_id`; `exclude_run_id` regression test) |
| 3 | No active run → UI shows no current-session assessment, not a stale score | Pass (`no_session` state; `vehicle-health-view` test) |
| 4 | Displayed window matches the executed request/report | Pass (live view has no selector; panel separates requested vs reported window) |
| 5 | Stale/insufficient run visibly marked | Pass (freshness + insufficiency reasons in shared live body) |
| 6 | Historical analytics still include old data and label run segments | Pass (untouched `historical_analytics_service`; historical endpoints labelled) |
| 7 | Existing snapshots/telemetry intact | Pass (no migration; no deletion/rewrite; scope stored in existing `context_json`) |
| 8 | Tests cover it | Pass (backend + frontend regression tests above) |

### Risks / notes

- The **running** backend at `http://127.0.0.1:8000` has not been reloaded, so its
  live `/openapi.json` does not yet show `analysis_scope`. The application module
  does expose it (verified by importing `app.main` and generating the schema), so
  a restart picks it up. Left running deliberately.
- Test-harness timing fix: `_ingest_run_window` (service tests) and `_ingest_run`
  (monitor tests) anchor timestamps per-row (see "Files changed" /
  "Regression tests") so the live freshness gate is not tripped by insert-loop
  latency (~16s for 40 rows on this test DB). Pre-existing service and monitor
  tests that were flaky (not Phase 1 regressions) now pass deterministically.
- Frontend full suite timeouts under concurrent load (5000ms vitest budget):
  all failing tests pass in isolation; the final full run below was executed
  without the backend suite running concurrently.
- Real-time alert **delivery** is out of scope for Phase 1 (Phase 3).

**Stopped at gate — awaiting review before Phase 2.**

---

## Phase 2 report — Persistence, workflow observability, security (appended at gate)

**Status:** implemented; stopped for review. Branch `main` @ `3f53a89`, all work
uncommitted (mixed with the pre-existing Phase 1 working tree). No phase proceeds
without approval.

Scope = the audit's five P2/security items mapped to the spec's Phase 2
acceptance criteria. P2-5 (`POST /health/analyze` read-triggered write
amplification) is explicitly out of this phase (see "Deferred").

### What changed

**P2-1 — `GET /health/live` no longer writes.**
`VehicleHealthService.analyze_live_vehicle` / `analyze_live_vehicle_for_user`
(`backend/app/services/vehicle_health_service.py`) gained a `persist: bool = True`
flag; `persist=False` evaluates and returns the snapshot without
`create`/`commit`. The live route
(`backend/app/api/routes/vehicle_health.py`) calls `persist=False`, so a poll
loop can never fill the snapshot table. The background monitor keeps the
default (`persist=True`), so current-session evidence is still captured. The
route description now states it is read-only.

**P2-2 — workflow events have a bounded durable audit copy (additive).**
The process-local bus stays the real-time feed; a best-effort persister mirrors
each buffered event to a new `workflow_events` table.

- New model `backend/app/models/workflow_event.py` (`WorkflowEventRecord`;
  `event_id` unique, no foreign keys so history outlives vehicle/document
  lifecycle; JSONB `metadata`). Registered in `app/models/__init__.py`.
- New migration `backend/alembic/versions/d4e5f6a7b8c9_create_workflow_events.py`
  (single head; `down_revision = c3f7a2d5e9b1`).
- New `backend/app/repositories/workflow_event_repository.py`
  (`insert_many` idempotent on `event_id`, sanitizes metadata again;
  `prune_before`; `count`; `list_recent` with the same visibility rule as the
  live buffer).
- New `backend/app/services/workflow_event_persistence.py`
  (`WorkflowEventPersister`): fire-and-forget, rate-limited age-based pruning,
  **never raises** into callers. Wired in `app/main.py` lifespan and installed
  on the bus via the new `WorkflowEventBus.set_persister`; `publish` schedules
  the audit copy **outside the lock** and swallows hook failures, so the live
  feed is never blocked or broken by persistence.
- `GET /workflow/events/recent?persisted=true`
  (`backend/app/api/routes/workflow.py`) reads the durable store (filters +
  ownership parity). Default is unchanged (live buffer).
- `GET /workflow/status` now discloses `event_persistence_enabled`,
  `event_retention_hours`, and `persisted_events` (buffer is process-local and
  lost on restart; the durable store is bounded by
  `WORKFLOW_EVENT_RETENTION_HOURS`, default 72h). Frontend
  `WorkflowStatusResponse` (`frontend/src/types/api.ts`) gained the three
  optional fields.
- Config: `workflow_event_persistence_enabled` (default `True`) and
  `workflow_event_retention_hours` (`> 0`, default `72`) in
  `backend/app/core/config.py`; wired in `app/main.py` lifespan.

**P2-3 — `get_recent_telemetry` LIMIT keeps the newest rows.**
`backend/app/repositories/telemetry_repository.py`: when `limit` is set the
query now orders `timestamp DESC, id DESC`, applies the limit, then reverses in
Python (ascending contract preserved) and logs a warning when the limit binds.
Previously an ascending `LIMIT` silently dropped the newest evidence.

**P2-4 — JWT secret fails closed, with an explicit dev opt-in.**
`backend/app/core/config.py`: `_is_weak_jwt_secret` (length < 32 or placeholder)
now raises in **every** environment unless `APP_ENV ∈ {development, local,
test}` **and** the new `AUTH_ALLOW_INSECURE_DEV_SECRET=true` opt-in is set.
Default is fail-closed.

**CORS tightening.**
`backend/app/core/config.py`: outside permissive envs the built-in default
origin list (`http://localhost:3000`) is refused; `CORS_ORIGINS` must be
declared explicitly.

**Docs.** `docs/workflow-observability.md` updated: the bus is still process-local
but is now mirrored best-effort into the age-bounded `workflow_events` table;
`events/recent` documents `?persisted=true`; `/workflow/status` disclosure
described. Frontend type `WorkflowStatusResponse` gained the three optional
disclosure fields.

### Migrations

- **New:** `d4e5f6a7b8c9_create_workflow_events` (creates `workflow_events` and
  4 indexes). Additive only; no existing table/column/row is altered or
  deleted. `alembic heads` → single head `d4e5f6a7b8c9`.
- No other migrations. Telemetry, snapshots, diagnoses and historical reports
  are untouched (no deletion/rewrite).

### Files changed (Phase 2 only)

Backend: `app/core/config.py`, `app/main.py`, `app/models/__init__.py`,
`app/models/workflow_event.py` (new), `app/repositories/telemetry_repository.py`,
`backend/app/repositories/workflow_event_repository.py` (new),
`backend/app/services/vehicle_health_service.py`,
`backend/app/services/workflow_event_bus.py`,
`backend/app/services/workflow_event_persistence.py` (new),
`backend/app/api/routes/vehicle_health.py`, `backend/app/api/routes/workflow.py`,
`backend/app/schemas/workflow.py`,
`backend/alembic/versions/d4e5f6a7b8c9_create_workflow_events.py`.
Frontend: `frontend/src/types/api.ts` (status-response disclosure fields).
Docs: `docs/workflow-observability.md`, this file, and the audit follow-up (§20).

### Regression tests added

- P2-1: `tests/services/test_vehicle_health_service.py::test_analyze_live_vehicle_persist_false_is_side_effect_free`
  and `tests/api/test_vehicle_health.py::test_live_read_is_side_effect_free`
  (repeated live GETs leave snapshot history unchanged but still return a
  definitive assessment).
- P2-3: `tests/services/test_telemetry_service.py::test_get_recent_telemetry_limit_keeps_newest_rows`.
- P2-4/CORS: reworked `backend/tests/core/test_security_settings.py` — weak
  secret refused in dev/local without the opt-in; accepted with it; default and
  empty CORS refused outside dev; explicit origins accepted.
- P2-2: `backend/tests/services/test_workflow_event_persistence.py` (store,
  idempotency, metadata redaction, retention prune, failure swallowed, empty
  batch); `backend/tests/services/test_workflow_event_bus.py` (+3: persister
  receives events, hook failure does not break publish, disabled by default);
  `backend/tests/api/test_workflow_routes.py` (+4: `persisted=true` visibility,
  filters, default still the live buffer, `/workflow/status` disclosure).
- `backend/tests/conftest.py`: `workflow_events` added to the `_truncate_all`
  table list.

### Tests executed (exact commands + results)

- Targeted backend (P2-1): `python -m pytest tests/api/test_vehicle_health.py
  tests/services/test_vehicle_health_service.py -q -p no:cacheprovider` →
  **36 passed**.
- Targeted backend (P2-3): `python -m pytest
  tests/services/test_telemetry_service.py -q -p no:cacheprovider -k
  "recent_telemetry or ingest_batch_timestamps"` → **2 passed**.
- Targeted backend (P2-4/CORS): `python -m pytest
  tests/core/test_security_settings.py tests/core/test_config.py -q
  -p no:cacheprovider` → **31 passed**.
- Targeted backend (P2-2): `python -m pytest
  tests/api/test_workflow_routes.py tests/services/test_workflow_event_bus.py
  tests/services/test_workflow_event_persistence.py -q -p no:cacheprovider` →
  **45 passed**. (Order matters: the bus singleton test closes the shared bus,
  so `tests/api` must run before `tests/services`; the full suite already does.)
- Migration chain: `python -m alembic heads` → **`d4e5f6a7b8c9 (head)`** (single
  head).
- Lint/format: `python -m ruff check app tests` → **clean**;
  `python -m ruff format --check <changed backend files>` → **clean**.
- OpenAPI: `app.main` imports cleanly; `/workflow/events/recent` exposes the
  `persisted` parameter and `WorkflowStatusResponse` exposes
  `event_persistence_enabled` / `event_retention_hours` / `persisted_events`.
- Full backend: `python -m pytest -q -p no:cacheprovider` → **693 collected;
  683 passed, 10 skipped, 0 failed**.
- Full frontend: `npx vitest run` → **23 files, 157 passed, 0 failed**;
  `npx tsc --noEmit` → **exit 0**; `npx eslint src/types/api.ts` → **clean**.

### Acceptance criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | A read endpoint must not persist (P2-1) | Pass — `/health/live` evaluates with `persist=False`; regression test asserts snapshot count unchanged |
| 2 | Workflow events are durable with bounded retention, or ephemerality is disclosed (P2-2) | Pass — `workflow_events` table + best-effort persister + age-based prune; `/workflow/status` discloses enablement/retention/count; `?persisted=true` reads history |
| 3 | Bounded telemetry reads keep the newest evidence (P2-3) | Pass — DESC+limit+reverse; regression test |
| 4 | Security defaults fail closed (P2-4 + CORS) | Pass — weak JWT refused everywhere without explicit dev opt-in; default CORS refused outside permissive envs |
| 5 | Existing telemetry/snapshots/historical reports preserved; contracts aligned | Pass — additive migration only; no deletes/rewrites; new response fields optional in the frontend type |

### Risks / notes

- **Operational change (P2-4).** `backend/.env` sets
  `JWT_SECRET=PASTE_A_RANDOM_SECRET_HERE` (a 26-char placeholder) under
  `APP_ENV=development`. With fail-closed defaults, a backend restart now
  **refuses to start** until the operator either sets a real `JWT_SECRET`
  (≥ 32 random chars) or adds `AUTH_ALLOW_INSECURE_DEV_SECRET=true`. The running
  server was **not** restarted (per instructions); the file was not edited
  (user-owned, holds secrets). This is the audit's intended fail-closed
  behaviour, surfaced here as an explicit operational note.
- **P2-2 is best-effort by design.** Persistence runs fire-and-forget; a store
  outage degrades audit history only and is logged, never surfaced to callers.
  `/workflow/status.persisted_events` is `null` (never a fabricated `0`) when the
  store cannot be read. Tests exercise the durable path by wiring the repository
  directly, because `httpx.ASGITransport` does not run the app lifespan (so the
  global bus has no persister under the test client).
- The **running** backend at `http://127.0.0.1:8000` has not been restarted, so
  its live schema lags the new `persisted` parameter and status fields until
  reload. Left running deliberately.
- The `workflow_events` table is **not** exercised by the alembic migration in
  the test suite (tests build the schema via `Base.metadata.create_all`); the
  chain is validated via `alembic heads`, and the app queries were exercised
  against the ORM-created table.

### Deferred (out of Phase 2 scope)

- **P2-5** (`POST /health/analyze` write amplification / UI-driven, no rate
  limit) — read-path write amplification, not in this phase's acceptance
  criteria.
- **P1-3** persistent alerts — Phase 3.
- Surfacing the durability disclosure in the workflow UI (the API + type fields
  exist; the frontend does not yet render them).

**Stopped at gate — awaiting review before Phase 3.**

---

## Phase 3 report — Persistent alerts (appended at gate)

**Status:** implemented; stopped for review. Branch `main` @ `3f53a89`, all work
uncommitted. No phase proceeds without approval.

### What changed

Findings inside a health snapshot are **immutable evidence**; alerts are now the
**mutable, first-class** counterpart with a full lifecycle and audit trail.

- **Model.** New `backend/app/models/alert.py`:
  - `alerts` (`Alert`): `vehicle_id` (FK, CASCADE), `simulation_run_id`,
    `dedup_key`, `rule_id`, `category`, `severity`, `status`, `title`, `message`,
    `metric`/`observed_value`/`threshold`/`unit`/`confidence`, `provisional`,
    `occurrence_count`, `first_seen_at`/`last_seen_at`, `evidence` JSONB,
    `snapshot_id`, the acknowledge fields (`acknowledged_at/by`,
    `acknowledge_note`), the resolve fields (`resolved_at/by`,
    `resolution_note`) and created/updated timestamps. CheckConstraints pin
    `severity`/`status`; three indexes cover listing by status/severity/dedup.
  - `alert_events` (`AlertEvent`): append-only audit rows
    (`created`/`recurred`/`acknowledged`/`resolved`) with `from_status`/
    `to_status`, nullable `actor_user_id` (null = automated) and `note`.
- **State machine.** `open → acknowledged → resolved`; `resolved` is terminal.
  Acknowledge and resolve are **idempotent**; acknowledging a resolved alert is a
  `409`. A recurrence after resolution creates a **new** alert — the resolved
  record and its audit trail are never rewritten.
- **Deduplication.** `dedup_key = "{vehicle_id}:{rule_id}"`. A repeated finding
  folds into the existing **active** (open/acknowledged) alert: it updates
  `last_seen_at`, increments `occurrence_count`, refreshes severity/values and
  appends a `recurred` audit row (noting any severity change). Deduplication is
  scoped to active alerts only.
- **Materialization (the producer).** `AlertService.sync_from_snapshot()` turns a
  live snapshot's findings into alerts. Alert-worthy = `severity ∈ {warning,
  critical}` and **not** a data-quality/meta rule (`TELEMETRY_GAP`,
  `LOW_DATA_COVERAGE`, `INSUFFICIENT_DATA`, `LIMITED_DATA`,
  `LIVE_DATA_SUFFICIENCY`). The background monitor calls it after each live
  evaluation; failures are isolated (an alert-store failure degrades alerts only,
  the snapshot/pass still succeeds). Historical windowed analyses never create
  alerts, mirroring the live-vs-historical split.
- **Auto-resolution.** When a **definitive** (non-provisional) evaluation no
  longer observes an active alert's rule, the alert auto-resolves with an
  automated audit row. A provisional evaluation never auto-resolves (insufficient
  data is not evidence the condition cleared).
- **API (ownership-enforced).** `backend/app/api/routes/alerts.py`, mounted at
  `/api/v1/vehicles/{vehicle_id}/alerts`:
  - `GET /` — paginated list; `?status=open|acknowledged|resolved` (repeatable)
  and `?severity=` filters; most-severe-first ordering. List items never include
  raw evidence.
  - `GET /{alert_id}` — detail incl. `evidence` and the full `events` history.
  - `POST /{alert_id}/acknowledge`, `POST /{alert_id}/resolve` — optional
    `{ "note": ... }` body. Ownership is enforced below the router via
    `ensure_vehicle_access`; an alert on another vehicle is a `404` (never a
    cross-tenant leak).
- **Wiring.** `get_alert_service` dependency added; the router is registered under
  `/vehicles/{vehicle_id}/alerts`; `HealthMonitorService` gained an optional
  `alert_service_factory`, wired in `main._start_health_monitor`.

### Migrations

- **New:** `e5f6a7b8c9d0_create_alerts` (creates `alerts` + `alert_events` with
  their PKs, FKs, check constraints and indexes). Additive only; no existing
  table/column/row is altered or deleted. `alembic heads` → single head
  `e5f6a7b8c9d0`.
- No other migrations. Telemetry, snapshots, diagnoses and historical reports
  are untouched.

### Files changed (Phase 3 only)

Backend: `app/models/alert.py` (new), `app/models/__init__.py`,
`app/models/vehicle.py` (relationship), `app/repositories/alert_repository.py`
(new), `app/services/alert_service.py` (new), `app/schemas/alert.py` (new),
`app/api/routes/alerts.py` (new), `app/api/router.py`,
`app/dependencies/database.py`, `app/services/health_monitor.py`, `app/main.py`,
`alembic/versions/e5f6a7b8c9d0_create_alerts.py` (new).
Tests: `tests/services/test_alert_service.py` (new),
`tests/api/test_alert_routes.py` (new), `tests/services/test_health_monitor_service.py`
(+1, plus a backward-compatible `_ingest_run` parameterization),
`tests/conftest.py`.
Docs: this file, `docs/alerts.md` (new), and the audit follow-up (§21).
Frontend: **none** (the eighth "Alerts" tab is Phase 4).

### Regression tests added

- `tests/services/test_alert_service.py` (20): worthiness predicate (parametrized
  incl. data-quality warnings), create, dedup/recurrence, severity update,
  auto-resolve on cleared condition, **no** auto-resolve while provisional,
  recurrence-after-resolution creates a new alert, acknowledge/resolve lifecycle
  with audit assertions, idempotency, resolved-acknowledge conflict, ownership
  enforcement, ordering + status/severity filters.
- `backend/tests/api/test_alert_routes.py` (11): empty list, list shape (no
  evidence leak), status/severity filters, detail with history, acknowledge+resolve
  flow, empty-body resolve, 409 on acknowledge-after-resolve, unknown alert 404,
  cross-vehicle 404, other-user 404, unauthenticated 401.
- `backend/tests/services/test_health_monitor_service.py`: a critical current-run
  pass materializes persistent open alerts (and records the run id).
- `backend/tests/conftest.py`: `alerts`/`alert_events` added to `_truncate_all`.

### Tests executed (exact commands + results)

- Targeted backend:
  `python -m pytest tests/services/test_alert_service.py
  tests/api/test_alert_routes.py tests/services/test_health_monitor_service.py
  -q -p no:cacheprovider` → **55 passed**.
- Lint/format: `python -m ruff check alembic app tests` → **clean**;
  `python -m ruff format --check <changed backend files>` → **clean**.
- Migration chain: `python -m alembic heads` → **`e5f6a7b8c9d0 (head)`** (single
  head). Upgrade + downgrade exercised on a throwaway local DB
  (`digital_twin_mig_check`) seeded with the minimal prior schema: upgrade created
  `alerts`/`alert_events` with the expected PKs, FKs and indexes; downgrade
  removed them cleanly and returned `alembic_version` to `c3f7a2d5e9b1`.
- Full backend: `python -m pytest -q -p no:cacheprovider` → **715 passed, 10
  skipped, 4 deselected, 0 failed** (+32 vs the Phase 2 total).
- Frontend unchanged in this phase (no UI files touched), so the Phase 2
  frontend result stands.

### Acceptance criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | P1-3: an `alerts` model + lifecycle endpoints exist and are tested | Pass — `alerts`/`alert_events` model + `GET`/acknowledge/resolve endpoints, all covered by tests |
| 2 | Acknowledgment, resolution, deduplication, audit history | Pass — state machine, idempotent actions, `dedup_key` folding, append-only `alert_events` |
| 3 | Alerts are vehicle-scoped and ownership-enforced | Pass — cross-vehicle and other-user access are `404`; unauthenticated is `401` |
| 4 | No false alerts / no silent resolution from bad data | Pass — data-quality/meta findings excluded; auto-resolve gated on a definitive evaluation |
| 5 | Historical data preserved; additive schema only | Pass — new tables only; no snapshot/telemetry/history mutation |

### Risks / notes

- **Hosted database was not migrated.** `backend/.env`'s `DATABASE_URL` points at
  a **hosted Supabase** instance (not localhost). During verification an
  `alembic upgrade` was invoked before this was noticed; the migration failed
  mid-way and, because Alembic runs the pending set in a single transaction, it
  **rolled back completely** — the hosted DB remains at `c3f7a2d5e9b1` with no
  `alerts`/`alert_events`/`workflow_events` (confirmed read-only). No hosted data
  was changed. The migration is therefore **not applied** to the live DB; run
  `alembic upgrade head` against the target database when ready.
- **Operational (P2-4).** Because the JWT secret in `.env` is still the weak
  placeholder, Alembic and the app refuse to start without a strong `JWT_SECRET`
  (or `AUTH_ALLOW_INSECURE_DEV_SECRET=true` in dev). `.env` was **not** edited and
  the running backend was **not** restarted.
- The running backend at `http://127.0.0.1:8000` still serves the older schema and
  code; the Alerts API is not reachable there until it is restarted and the DB is
  migrated.
- The migration is **not** exercised by the pytest suite (tests build the schema
  via `Base.metadata.create_all`); it is validated on a dedicated throwaway DB as
  described above.

### Deferred (out of Phase 3 scope)

- **Phase 4** — the eight-tab product: add the **Alerts** tab UI
  (`VEHICLE_TABS`, an alerts view, `types/api.ts` + hooks) and finalize the tab
  set. Phase 3 delivers the backend contract the tab will consume.
- **P2-5** (`POST /health/analyze` write amplification) remains open.

**Stopped at gate — awaiting review before Phase 4.**

---

## Phase 4 report — Finalize the eight-tab product (appended at gate)

**Status:** implemented; stopped for review. Frontend-only; no commit. Branch
`main`, all work uncommitted.

**Scope delivered.** The eighth tab — **Alerts** — is now a first-class part of the
vehicle workspace, consuming the Phase 3 backend contract. Decision 4 of
`docs/PRODUCT_SPECIFICATION.md` (the seven existing tabs plus Alerts = eight) is
now enforced by a regression test.

### What changed

- **Tab chrome.** `VEHICLE_TABS` (`frontend/src/components/layout/nav-items.tsx`)
  gains an `Alerts` entry (`/alerts`, `Bell` icon) after `History`. The workspace
  needs no other change — `vehicle-workspace.tsx` already maps `VEHICLE_TABS`.
- **Route.** `frontend/src/app/(app)/vehicles/[id]/alerts/page.tsx` renders
  `VehicleAlertsView`, matching the thin-wrapper pattern of the sibling tabs.
- **API types.** `frontend/src/types/api.ts` gains `AlertStatus`, `AlertItem`,
  `AlertEventItem`, `AlertDetail` and `AlertActionRequest`, mirrored
  **field-for-field** from `backend/app/schemas/alert.py` (including
  `created_at`/`updated_at` and the nullable `evidence`).
- **Service.** `frontend/src/services/alerts.ts` (`alertsApi.list/get/acknowledge/
  resolve`). List filters are single-valued (`status`, `severity`) plus
  `page`/`page_size`; action bodies omit `note` when blank and trim it otherwise.
- **Query keys + hooks.** `queryKeys.alertsRoot/alerts/alert`
  (`frontend/src/lib/query-keys.ts`); `useVehicleAlerts` / `useAlertDetail`
  (`frontend/src/hooks/use-vehicle-data.ts`); `useAcknowledgeAlert` /
  `useResolveAlert` (`frontend/src/hooks/use-mutations.ts`), which write the
  returned detail into the detail cache and invalidate every list page.
- **View.** `frontend/src/components/vehicles/vehicle-alerts-view.tsx`:
  - list with severity / status / occurrence / `provisional` badges, rule id,
    metric label, first→last seen, and the total count;
  - status and severity filters plus pagination (20/page);
  - inline **Acknowledge** / **Resolve** quick actions and a detail dialog with the
    raw evidence and the full append-only audit timeline;
  - honest empty states (“No alerts” vs “No alerts match these filters”) and
    error/retry states;
  - lifecycle correctness: `resolved` is terminal and offers no action; the dialog
    attributes automated transitions to “System”.

### Regression tests added

- `frontend/src/components/vehicles/__tests__/vehicle-alerts-view.test.tsx` (7):
  render with severity/status/rule; empty state; detail + evidence + audit history
  (system-attributed creation); acknowledge calls the API without opening the
  dialog; **no** acknowledge/resolve on a resolved alert; the status filter is
  forwarded to the request; and switching vehicles never leaks the previous
  vehicle's alerts (the scoped placeholder).
- `frontend/src/services/__tests__/alerts.test.ts` (7): list URL + query
  defaults/filters/abort signal; detail URL; acknowledge/resolve bodies (blank
  note omitted; a supplied note is trimmed).
- `frontend/src/components/layout/__tests__/nav-items.test.ts` (2): `VEHICLE_TABS`
  is exactly the eight approved labels, in order, with their sub-paths.

### Tests executed (exact commands + results)

- `npx vitest run` (in `frontend/`) → **173 passed (26 files), 0 failed**.
- `npx tsc --noEmit` → clean.
- `npx eslint <changed files>` → clean.
- Backend unchanged in Phase 4; the Phase 3 gate stands.

### Acceptance criteria

- The vehicle workspace exposes eight tabs in the spec order; Alerts is one of
  them.
- The Alerts tab lists persisted alerts, filters by status/severity, paginates,
  shows raw evidence and the append-only audit history, and performs acknowledge
  and resolve with optional notes — all against the ownership-enforced Phase 3
  API. It never fabricates an alert or a state.

### Risks / notes

- No backend change, so the **hosted database is still not migrated** and the
  running backend still lacks the Alerts API. Until it is migrated and restarted
  (see the Phase 3 note), the tab renders its loading/error states rather than
  data.
- `GET /vehicles/{id}/alerts` accepts repeated `status` params; the UI sends a
  single value, which is a valid one-element filter.

**Stopped at gate — awaiting review before Phase 5.**

---

## Phase 5 report — Full-system acceptance (appended at gate)

**Status:** implemented; stopped for review. Branch `main`, all work
uncommitted. No phase proceeds without approval.

**Scope.** This phase is the product-level acceptance pass, not a feature phase.
It (a) adds a hermetic, real-stack acceptance test that asserts the cross-tab
invariants a per-feature suite cannot express; (b) exercises the *current* code as
a real, separately-booted server over TCP against a real database; and (c) records
read-only evidence of the running stack (which predates Phase 3).

**Non-destructive by construction.** No hosted database was touched and no
destructive alembic was run. The acceptance test uses the sanctioned
`digital_twin_test` database (conftest builds/drops the schema around the session
and truncates between tests). The live smoke booted a **second** uvicorn on
`127.0.0.1:8010` pointed at a **throwaway** local DB (`digital_twin_phase5`) with
an isolated simulator runtime dir; the second server was stopped and the throwaway
DB was dropped afterwards. The running stack (8000 / 3000 / 1883) was **not**
restarted.

### What changed

- New `backend/tests/acceptance/__init__.py` and
  `backend/tests/acceptance/test_full_system_acceptance.py` (5 tests). It drives
  the **real** FastAPI app over `httpx.ASGITransport` against a **real** Postgres
  DB. It is hermetic: an autouse fixture overrides `get_simulation_manager`
  (in-memory `FakeProcessRunner`) and `get_agent_service` (deterministic mock LLM
  provider), so no OS subprocess is spawned and no LLM is called. It reuses the
  established per-feature patterns (`FakeProcessRunner`, `_seed_alert`,
  `_assert_status_body`) rather than duplicating coverage.

  The five cross-tab invariants:

  1. **Overview + Telemetry + AI Diagnosis + History + Analytics** — bounded
     ingest; telemetry `total`; read-only analytics; a windowed analysis is
     `analysis_scope == "historical_window"`; history paginates; the dashboard
     hook needs no LLM; workflow status reachable; and — the key cross-tab
     invariant — a **historical analysis never creates a live alert**
     (`alerts == []`).
  2. **Live Health honesty** — with a historical snapshot already persisted, a
     stopped vehicle reports `no_session` / `assessment is None` (it never
     re-surfaces the historical score); an active run with insufficient fresh
     current-run evidence reports `collecting` (with reasons) and still no
     assessment.
  3. **Alerts lifecycle** — list / detail / filters; raw evidence + append-only
     history on detail; acknowledge → resolve attributed to the acting user;
     `resolved` is terminal (acknowledge → `409`, resolve idempotent); a
     recurrence after resolution mints a **new** alert; ownership enforced (other
     user `404`).
  4. **Simulation lifecycle** — start → status → list → restart (new run id) →
     stop; the status body never leaks the process (`pid`/`env`/`command`/`cmd`
     absent).
  5. **Cross-tab ownership isolation** — every vehicle-scoped GET (`telemetry`,
     `health`, `health/live`, `health/history`, `historical-analytics?range=24h`,
     `agent/dashboard`, `agent/diagnoses`, `alerts`, `simulation`) is `404` for
     another user and `401` unauthenticated; telemetry ingest and analyze
     likewise.

### Live-server acceptance (runtime evidence)

The current code was booted as a second, isolated server and driven over TCP:

```
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
  (DATABASE_URL -> local digital_twin_phase5; APP_ENV=development;
   JWT_SECRET=<temp strong>; HEALTH_MONITOR_ENABLED=false;
   RAG_ENABLED=false; AUTH_RATE_LIMIT_ENABLED=false;
   SIMULATION_RUNTIME_DIR=<isolated temp dir>)
```

A Python `httpx` harness walked the eight-tab surface over HTTP. **All 18 checks
passed:**

- `GET /api/v1/health` → 200; `GET /api/v1/health/db` → `database == "ok"`.
- `GET /openapi.json` exposes all eight tabs' endpoints (telemetry, live health,
  analyze, history, historical-analytics, simulation, agent dashboard, alerts).
- register → `201`; login → `200`; create vehicle → `201`.
- ingest 40 telemetry rows → `201` each; list `total == 40`.
- `POST /health/analyze` → `200`, `analysis_scope == "historical_window"`;
  `GET /health` → 200; `GET /health/live` → 200 with no active session
  (`assessment is None`); `GET /historical-analytics?range=24h` → 200;
  `GET /agent/dashboard` → 200 with a non-null `health_context`;
  `GET /alerts` → 200 with the exact empty contract
  `{"items": [], "page": 1, "page_size": 20, "total": 0}`;
  `GET /workflow/status` → 200.

The smoke's server and DB were torn down afterwards (port 8010 released;
`DROP DATABASE ... WITH (FORCE)`; the throwaway DB no longer exists).

### Read-only evidence of the running stack (stale instance)

The actively-running backend at `http://127.0.0.1:8000` was probed read-only:

- `/openapi.json` → **34 paths**, including `/health/live`,
  `/historical-analytics`, `/agent/dashboard`, `/simulation`, but **no
  `/alerts`**.
- The current code (second server) → **38 paths**, including `/alerts`.
- `scripts/dt-status.ps1` → ports 1883 / 8000 open; `/api/v1/health` ok
  (`digital-twin-api`).

Conclusion: the running instance predates Phase 3 (it has the Phase 1/2
endpoints but not the alerts API). It was started **without** `--reload` and was
deliberately **not** restarted. Until it is restarted and the target database is
migrated to head `e5f6a7b8c9d0`, the running stack serves the pre-Phase-3
contract; the Alerts tab renders its loading/error states, by design.

### Regression tests added

- `backend/tests/acceptance/test_full_system_acceptance.py` (5) — as above.
- `backend/tests/acceptance/__init__.py` (package marker).

### Tests executed (exact commands + results)

- Acceptance module: `python -m pytest tests/acceptance -q -p no:cacheprovider`
  → **5 passed in 23.67s**.
- Lint/format: `python -m ruff check backend\tests\acceptance` → **clean**;
  `python -m ruff format --check backend\tests\acceptance` → **2 files already
  formatted**.
- Live-server smoke: **18/18 checks passed** (see above).
- Full backend: `python -m pytest -q -p no:cacheprovider` (run from `backend/`)
  → **720 passed, 10 skipped, 4 deselected, 0 failed** (exit 0; +5 passing over
  the Phase 3 gate, exactly the five new acceptance tests).
- Full frontend: `npx vitest run` → **173 passed (26 files), 0 failed**;
  `npx tsc --noEmit` → **exit 0**; `npx eslint .` → **exit 0**.

### Acceptance criteria

| # | Criterion | Result |
|---|---|---|
| 1 | The eight tabs work together end-to-end on a real stack | Pass (5-test acceptance module over real app + real Postgres) |
| 2 | Cross-tab correctness: historical analyses never fabricate live alerts | Pass (`alerts == []` after a windowed analysis) |
| 3 | Live Health honesty: a historical snapshot is never surfaced as current | Pass (`no_session` / `collecting`, `assessment is None`) |
| 4 | Alerts lifecycle + terminal resolve + recurrence = new alert + ownership | Pass (full lifecycle in the acceptance module) |
| 5 | Simulation lifecycle; the VM never exposes the process | Pass (start/status/restart/stop; `pid`/`env`/`cmd` absent) |
| 6 | Per-owner isolation across every vehicle-scoped tab | Pass (`404` other user, `401` unauthenticated) |
| 7 | Acceptance is **non-destructive** (no hosted-DB mutation, no destructive alembic) | Pass (sanctioned test DB; throwaway DB + spare port for the live smoke, both torn down) |
| 8 | The current code is genuinely runnable as a server, not only under ASGI tests | Pass (live smoke, 18/18) |

### Risks / notes

- **Running instance is stale (operational).** `http://127.0.0.1:8000` predates
  Phase 3 and was **not** restarted (per instructions). A restart + `alembic
  upgrade head` on the target DB makes the Alerts API and the Phase 2/3 schema
  live.
- **Hosted DB still not migrated** (Phase 3 note) and `.env`'s weak `JWT_SECRET`
  remains (P2-4): the app refuses to start until the operator sets a strong
  secret or opts into the dev escape hatch. `.env` was **not** edited.
- The live smoke required a **dedicated** runtime dir; the second server's
  startup cleanup would otherwise have been able to reap the running stack's
  simulators. This is called out so a future live-probe follows the same
  isolation.
- **Local Postgres has no pgvector**, so the live smoke created only the
  non-RAG tables (the RAG tables are skipped locally anyway). The acceptance
  module likewise never touches RAG.
- The full alembic chain **from base** fails on a fresh DB at `4f9d3c2b1a8e`
  (pgvector `DO $$ … EXCEPTION` under asyncpg) — pre-existing and unrelated;
  `alembic heads` still resolves to the single head `e5f6a7b8c9d0`.

### Deferred (out of Phase 5 scope)

- **P2-5** (`POST /health/analyze` write amplification) — unchanged.
- Applying `alembic upgrade head` to the hosted DB and restarting the running
  backend (operational; requires a real `JWT_SECRET`).

**Stopped at gate — awaiting review before any further phase.**


