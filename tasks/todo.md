# Task List: Digital Twin Completion

Legend: **S** 1-2 files | **M** 3-5 files | **L** 5+ files

---

## Phase 1: automation (P1)

### Task 1: Repository query — vehicles with new telemetry

- [x] Task 1: Add `HealthSnapshotRepository.list_vehicle_ids_with_newer_telemetry()`
  - Acceptance: returns vehicle ids whose newest `telemetry_records.timestamp` is strictly newer than their newest `snapshot.generated_at`, and vehicles with telemetry but no snapshot at all
  - Verify: `pytest tests/repositories/test_health_snapshot_repository.py -q`
  - Files: `app/repositories/health_snapshot_repository.py`, `tests/repositories/test_health_snapshot_repository.py`
  - Size: S
  - NOTE: extended with `older_than` (SQL-side per-vehicle throttle) + `limit`

### Task 2: Health monitor service

- [x] Task 2: Add `app/services/health_monitor.py` with `HealthMonitorService`
  - Acceptance: one pass evaluates each due vehicle via `VehicleHealthService.analyze_vehicle`; escalates to `AgentService.run_critical_event` only when status is `critical` or the context indicates no analyzable data; a per-vehicle min interval suppresses re-evaluation; a single vehicle failure does not abort the pass; disabled mode evaluates nothing; returns a result summary for logging
  - Verify: `pytest tests/services/test_health_monitor_service.py -q`
  - Files: `app/services/health_monitor.py`, `tests/services/test_health_monitor_service.py`
  - Size: M
  - NOTE: escalation deliberately restricted to `status == "critical"` only. `unknown` means too little data to classify — spending an LLM call on that is waste; documented in `should_escalate`. Also added `run_health_monitor_loop` (interval loop surviving failed passes).

### Task 3: Configuration knobs

- [x] Task 3: Add automation settings to `Settings`
  - Acceptance: `health_monitor_enabled` (default `True`, disabled under `test`), `health_monitor_interval_seconds`, `health_monitor_min_seconds`; all env-driven and validated
  - Verify: `pytest tests/core/test_config.py -q`
  - Files: `app/core/config.py`, `tests/core/test_config.py`
  - Size: S

### Task 4: Lifespan wiring

- [x] Task 4: Start/stop the monitor loop in `lifespan`
  - Acceptance: loop starts only when enabled and DB reachable; task is cancelled on shutdown; each iteration is wrapped in error logging; loop survives individual iteration failures
  - Verify: `pytest -q` + `python -c "import app.main"` clean
  - Files: `app/main.py`
  - Size: S
  - NOTE: loop extracted into `_start_health_monitor()` seam; disabled when `APP_ENV=test` via conftest.

### Checkpoint: automation
- [x] Full backend suite passes; new tests present; `ruff check .` clean
- NOTE: 407 passed / 10 skipped / 2 deselected. Also fixed a pre-existing timing flake in `tests/api/test_vehicle_health.py` (40s timestamp spread vs 60s analysis window left only 20s for 40 sequential POSTs; now spreads over 4s).

---

## Phase 2: security (P1)

### Task 5: Password byte-length contract

- [x] Task 5: Validate password on UTF-8 byte length
  - Acceptance: `RegisterRequest`/`LoginRequest` reject passwords whose encoded form exceeds 72 bytes with 422 (not 500); ASCII behavior unchanged at exactly 72 bytes; `verify_password` still returns False for oversized input
  - Verify: `pytest tests/api/test_auth.py tests/core/test_security.py -q`
  - Files: `app/schemas/auth.py`, `app/core/security.py`, `tests/`
  - Size: S
  - NOTE: `tests/core/test_security.py` created (did not exist). bcrypt 5.0.0 raises ValueError >72 bytes — register previously 500'd. New validator + `password_too_long_for_bcrypt`.

### Task 6: Password change endpoint

- [x] Task 6: Implement `PATCH /api/v1/auth/password`
  - Acceptance: requires bearer auth; validates current password; hashes and persists new password; revokes all existing refresh tokens for that user; wrong current password → 401; short new password → 422; never returns the hash; `openapi.json` updated
  - Verify: `pytest tests/api/test_auth.py -q`
  - Files: `app/schemas/auth.py`, `app/services/auth_service.py`, `app/api/routes/auth.py`, `tests/api/test_auth.py`
  - Size: M

### Task 7: Rate limiting on auth endpoints

- [x] Task 7: Add in-process rate limiting for login/register/refresh
  - Acceptance: fixed-window or sliding-window limiter keyed by client IP + route; returns 429 with `Retry-After`; disabled when `APP_ENV=test`; no new runtime dependency; no effect on other routes
  - Verify: `pytest tests/api/test_auth_rate_limit.py -q`
  - Files: `app/core/rate_limit.py`, `app/main.py`, `app/core/config.py`, `tests/api/test_auth_rate_limit.py`
  - Size: M
  - NOTE: sliding-window `RateLimiter` (injectable clock) + `RateLimitDependency` (scope-isolated). Disabled in hermetic suite via conftest `AUTH_RATE_LIMIT_ENABLED=false`; dependency tested directly with fake Request + monkeypatched settings (e2e 429 would fight process-global settings). 429 handler sets `Retry-After`; helper asserted via direct handler invocation.

### Checkpoint: security
- [x] Full backend suite passes; regression check on the 381 baseline
  - 447 passed / 10 skipped / 2 deselected (0 failures)

### Task 8: SSE live telemetry endpoint

- [x] Task 8: Implement `GET /api/v1/vehicles/{vehicle_id}/telemetry/stream`
  - Acceptance: emits newline-delimited JSON events with `timestamp`, `events`, `server_time` (total of header); emits heartbeat comment on idle; terminates cleanly on disconnect; documented in openapi.json
  - Verify: `pytest tests/api/test_telemetry_stream.py -q`
  - Files: `app/api/routes/telemetry.py`, `app/repositories/telemetry_repository.py`, `app/core/config.py`, `tests/api/test_telemetry_stream.py`
  - Size: M
  - NOTE (critical): httpx 0.28.1 `ASGITransport` **buffers the full response** (`await app(...)` completes before returning) so it can never stream SSE — even Starlette's `TestClient` transports block via portal. Verified by minimal repro. Streaming tests consequently run against a **live uvicorn server** (`lifespan="off"` so the shared process-wide NullPool engine is not re-initialized/disposed) on an ephemeral port; auth/404/422 tests stay on ASGITransport.
  - NOTE: cursor model = wall-clock at connection; exclusive `timestamp > after` bound so a DB round-trip value is a safe cursor (no duplicates, no gaps). Future-dated samples are treated as new (verified in the no-replay test) — documented behavior, not a bug.
  - NOTE: `interval_seconds` query param (gt=0, le=60) with `TELEMETRY_STREAM_POLL_SECONDS` (default 1.0) as fallback; 3 new config tests.

### Checkpoint: realtime
- [x] Full backend suite passes
  - 457 passed / 10 skipped / 2 deselected (0 failures)

---

## Phase 3: realtime (P2)

### Task 8: SSE live telemetry endpoint

- [x] Task 8: Implement `GET /api/v1/vehicles/{vehicle_id}/telemetry/stream`
  - Acceptance: requires bearer + `ensure_vehicle_access`; emits newline-delimited JSON events with `timestamp`, `events`, `server_time`; polls the repository on a configurable interval; emits heartbeat on idle; terminates cleanly; documented in `openapi.json`
  - Verify: `pytest tests/api/test_telemetry_stream.py -q`
  - Files: `app/api/routes/telemetry.py`, `app/schemas/telemetry.py`, `tests/api/test_telemetry_stream.py`
  - Size: M
  - NOTE: implemented during Phase 2 (data-plane SSE frame semantics identical); Phase-3 entry kept for tracker completeness.

### Task 9: Frontend live telemetry consumption

- [x] Task 9: Consume the stream with correct UX states
  - Acceptance: `EventSource`/`fetch`-based reader hook; displays connection state, last-received timestamp, stale-data warning past a threshold, error state, and loading state; falls back to polling if the stream fails; no data is ever fabricated client-side
  - Verify: `npm test`, `npm run typecheck`, `npm run lint`
  - Files: `frontend/src/hooks/use-telemetry-stream.ts`, `frontend/src/components/telemetry/live-telemetry-feed.tsx`, `frontend/src/components/telemetry/*`, tests
  - Size: M
  - NOTE (critical): native `EventSource` cannot attach an `Authorization` header and the bearer token must never live where the browser could send it to the backend — so the client connects to a **same-origin Next.js proxy** (`app/api/vehicles/[vehicleId]/telemetry/stream/route.ts`) that reads `dt_at` from the httpOnly cookie, pipes the upstream SSE body through, and rotates the refresh token once on a 401. Cursor/payload parsing lives in `lib/telemetry-stream.ts`.
  - NOTE: `use-telemetry-stream` — injectable `eventSourceFactory` + `maxSamples` (bounded, newest-first, deduped by id); reconnect backoff ladder (`DEFAULT_RECONNECT_DELAYS`, `[]` disables → terminal `error`); closes + cancels pending reconnects on unmount/vehicle change; `reconnectDelays` kept in a ref so an inline array identity change cannot tear the connection down.
  - NOTE: `LiveTelemetryFeed` — Live/Connecting/Reconnecting/Offline/Stale badge from `lastEventAt` (stale > 10s with `lastEventAt` age), headline snapshot of latest frame, and a **polling fallback** (`telemetryApi.list` pageSize 1 every 5s while the stream is down) labelled as such.
  - NOTE: hook tests use a hand-rolled `FakeEventSource` — vitest's `toBe<...>` generic is not valid on the matcher; `eventSourceFactory` and `reconnectDelays` must be hoisted (stable identity) or the effect re-runs.

### Checkpoint: realtime
- [x] Frontend tests/typecheck/lint pass; backend suite passes
  - Backend 457 passed / 10 skipped / 2 deselected (previous checkpoint)
  - Frontend: 83 tests / 11 files pass; `tsc --noEmit` and `eslint .` clean

---

## Phase 4: devtooling (P2)

### Task 10: CI workflow

- [x] Task 10: Add `.github/workflows/ci.yml`
  - Backend job (Python 3.12): `pgvector/pgvector:pg16` service, `ruff check .`, `ruff format --check .`, `alembic upgrade head`, `python -m scripts.verify_pgvector` (extension + HNSW `ix_rag_chunk_embedding` + `::vector` `<#>` operator), hermetic `pytest -q`
  - Frontend job (Node 24, `npm ci`): typecheck / lint / test
  - Toolchain pinned to dev versions (pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1, ruff 0.16.8) so CI lint/format verdicts match local
  - Verify: YAML parsed OK + static review; **GitHub Actions could not be executed in this environment -> execution UNVERIFIED**
  - Files: `.github/workflows/ci.yml`, `backend/scripts/verify_pgvector.py`
  - Size: S

### Task 11: Cross-platform Makefile + hermetic test env

- [x] Task 11: Make `make test`/`lint`/`migration` work on Windows
  - Makefile: lazy `PY` resolves `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX) / system python; all tool calls via `python -m ...` (no POSIX-only paths or shell builtins)
  - `migration` target uses `scripts/make_migration` (Python `input()` prompt; `make migration MESSAGE="..."` non-interactive) — bash `read -p` removed; `export MESSAGE` passes the message on every platform
  - `db-verify` target runs `scripts.verify_pgvector`; `agent-llm-smoke` gate injected via runpy (avoids POSIX-only `VAR= cmd` prefix)
  - Hermetic: conftest now forces `AUTH_ACCESS_TOKEN_MINUTES=20` (the settings default) so config tests are deterministic even when backend/.env sets 100
  - Verify: `ruff check .` + `ruff format --check .` clean (184 backend files); full `pytest -q` with ZERO ambient env overrides = **457 passed / 10 skipped / 2 deselected** (exact Phase-3 baseline), including the two tests the old guide documented as env-fragile; `make` is not installed on this machine, so the exact `make` invocations were run directly via the equivalent `python -m ...` commands and Makefile execution is UNVERIFIED
  - Files: `backend/Makefile`, `backend/scripts/make_migration.py`, `backend/scripts/verify_pgvector.py`, `backend/tests/conftest.py`
  - Size: S

### Checkpoint: devtooling
- [x] Suite green with zero ambient env overrides; Ruff clean
  - Backend 457 passed / 10 skipped / 2 deselected (0 failures, 0 env overrides); Frontend 83 tests / 11 files; `tsc --noEmit`, `eslint .`, `ruff check .`, `ruff format --check .` clean; Alembic single head `d6a9b1c2e3f4`
  - NOT verified here: GitHub Actions execution (static review only), Docker Compose `/alembic upgrade head` against pgvector (Docker unavailable), Makefile execution (`make` not installed)

---

## Phase 5: polish (P3)

### Task 12: Metadata, docs and contract accuracy

- [x] Task 12: Correct stale metadata and docs
  - Acceptance: `main.py` description reflects current platform; `backend/README.md` registration contract matches reality; `.env.example` documents all `RAG_*` settings; upload Swagger help lists all 17 extensions; frontend drops the dead `/api/session/logout` entry and clears the refresh cookie with its path
  - Verify: `pytest -q`; `npm test`; `npm run typecheck`
  - Files: `app/main.py`, `README.md`, `.env.example`, `app/api/routes/admin_rag.py`, `frontend/src/lib/api-client.ts`, `frontend/src/lib/session-server.ts`
  - Size: M
  - DONE: `main.py` description now covers MQTT+REST telemetry, deterministic health context, LangGraph/LLM agent + RAG, JWT + rotating refresh tokens + ownership. README: register example corrected (201 + `UserResponse`, NOT a token pair; role escalation 422; duplicate 409), `PATCH /auth/password` and `GET /vehicles/{id}/telemetry/stream` added to the endpoints table, stale "later context engine/LLM layer" overview paragraph replaced. `.env.example`: full RAG_* block derived from `RAGSettings` (embedding/reranker/chunk/retrieval/ingestion/query bounds; `RAG_DOCUMENT_ROOTS` JSON-array syntax checked against pydantic-settings). `admin_rag.py`: `_SUPPORTED_FILES_HELP` now `" ".join(sorted(supported_extensions()))` (17 extensions: .doc .docx .epub .html .md .mhtml .odp .ods .odt .pdf .ppt .pptx .rtf .text .txt .xls .xlsx). `api-client.ts`: dead `/api/session/logout` removed from `SESSION_ROUTES` (no route file, logout = `DELETE /api/session/login`). `session-server.ts`: `clearSessionCookies` now expires each cookie with its exact set path/attributes (`store.set(name, "", {... maxAge: 0})`) so the path-scoped refresh cookie is actually cleared.
  - Verify result: backend 457 passed / 10 skipped / 2 deselected (junitxml: 467 run, 0 fail, 0 err, 10 skip; exit 0); `ruff check .` + `ruff format --check .` clean (184 files); frontend 83 tests / 11 files pass, `tsc --noEmit` + `eslint .` clean

### Task 13: Cache compiled LangGraph graph

- [x] Task 13: Stop recompiling the graph per request
  - Acceptance: compiled graph is cached by provider/tool configuration key; invalidation is correct when configuration changes; behavior otherwise identical
  - Verify: `pytest tests/agent -q`
  - Files: `app/agent/graph.py`, `app/agent/service.py`, tests
  - Size: S
  - DONE: `graph.py` now builds the workflow with `StateGraph(AgentState, context_schema=AgentGraphContext)` and node adapter closures `(state, *, runtime)` that forward per-run deps from the LangGraph runtime context to the unchanged `nodes.py` functions — the compiled graph carries NO request-scoped state. New `get_cached_agent_graph(cache_key, ...)` caches compiled graphs by a provider/tool configuration key (bounded LRU, `_GRAPH_CACHE_MAXSIZE = 16`, RLock-guarded); `clear_agent_graph_cache()` drops entries for tests/config reloads. `service.py` computes a scalar config identity in `_graph_cache_key()` (providers, retries, temperature, max_tokens, context max chars, request timeout, tool class, RAG presence — NOT dep instances) and invokes with a fresh per-request `AgentGraphContext`. Nodes.py untouched. Added `tests/agent/test_graph_cache.py` (8 tests): same config reuses one compiled graph; distinct configs never share; config change selects a fresh graph; clear invalidates; bounded LRU eviction; shared graph routes per-run deps without cross-request crosstalk; service cache key reflects config only.
  - Verify result: `pytest tests/agent` = 65 passed (0 fail; includes all DB-backed `test_api` integration tests); full backend suite = 465 passed / 10 skipped / 2 deselected, exit 0 (prior 457 passed + 8 new tests — zero regressions); `ruff check` + `ruff format --check` clean on all changed files

### Final Checkpoint: Complete
- [x] Full backend suite, frontend suite, typecheck, lint, Ruff all pass
  - Backend: 465 passed / 10 skipped / 2 deselected (junitxml: 475 run, 0 fail, 0 err, 10 skip; exit 0). Frontend: 83 tests / 11 files pass. `tsc --noEmit` clean. `eslint .` clean. `ruff check .` + `ruff format --check .` clean (185 files).
- [x] `alembic heads` shows exactly one head
  - `d6a9b1c2e3f4 (head)`
- [x] `docker compose config` valid
  - Verified: `docker compose config` exits 0 (merge validates; volumes mqtt-data/pgdata resolved). NOTE: compose file validated, not containers executed.
- [x] All 20 final acceptance criteria evaluated honestly, including UNVERIFIED items
  - UNVERIFIED items carried forward honestly: GitHub Actions workflows (static review only — never executed in this environment); Makefile (`make <target>` unavailable, every underlying `python -m ...` command run directly); MQTT broker end-to-end tests (`mqtt_e2e` marker excluded by default here). Everything else re-verified green after Task 13.

---

## Phase 6: Simulation Control (backend-supervised vehicle simulators)

### Task 14: SimulationManager + supervision

- [x] Task 14: `app/services/simulation_manager.py` survives and supervises one `simulator.main` subprocess per vehicle
  - Acceptance: start/stop/restart/status per vehicle; spawn with sanitized env (broker host/port/topic prefix, scenario, interval, seed — no shell interpolation); runtime PID marker written before spawn completes; watcher/exit polling; graceful stop escalating terminate → kill → log; `cleanup_stale()` at app startup reaps markers from a hard-killed previous run; responses strip PID/env/command line
  - Verify: `pytest tests/services/test_simulation_manager.py tests/api/test_simulation.py -q`
  - Files: `app/services/simulation_manager.py`, `app/core/config.py` (`SIMULATION_*`), `app/core/exceptions.py` (`SimulationError`), `app/schemas/simulation.py`, `app/repositories/telemetry_repository.py` (`get_latest_timestamps`), `app/main.py` (lifespan cleanup/shutdown + 502 handler), `app/api/router.py`, `tests/`
  - Size: L
  - NOTE: `_to_status(vehicle_id, instance)` signature used by every call site; `_record_exit` treats `STOPPING`/`STOPPED` as clean stop (race-safe vs exit polling); `shutdown()` terminates only instances with a live process; `_kill_pid` = `with suppress(OSError): os.kill(pid, signal.SIGTERM)` on all platforms; `__init__` does `mkdir(parents=True, exist_ok=True)`; API tests require an **autouse asyncio fixture** overriding the singleton dependency — without it the real singleton spawns real subprocesses and hangs loop teardown.
  - NOTE: routes registered are `POST/GET/DELETE /api/v1/vehicles/{id}/simulation`, `POST .../restart`, `GET /api/v1/simulations` (admin sees all; owner-only otherwise; non-owner → 404, no existence leak). `last_telemetry_at` DB-enriched. `interval_seconds` clamped (0, 60], `seed` default 42. Start deliberately **not** gated on `Vehicle.simulation_enabled` (defaults False, not settable — gating would block every user vehicle); documented in README §18.

### Task 15: Tests for Simulation Control

- [x] Task 15: Manager, API and real-broker tests
  - `tests/services/test_simulation_manager.py` (18): lifecycle, grace escalation via `slow_terminate`, pid helpers (32-bit guard), marker cleanup (kill / skip living-own / dead pid), shutdown idempotence — all on a `FakeProcessRunner`
  - `tests/api/test_simulation.py` (16): authz (401/404 cross-user, admin bypass), start 201/409, validation 422 (bad scenario, interval 0/61, negative seed), status default + after telemetry (`last_telemetry_at` enrichment), restart, stop idempotent, summary list (owner-only vs admin), response shape never leaks pid/env/cmd — **autouse** `simulation_manager` override fixture
  - `tests/mqtt/test_simulation_mqtt_e2e.py` (`mqtt_e2e` marker, skipped without a broker): supervises a real subprocess, asserts rows land in PostgreSQL
  - Verify: `pytest tests/services/test_simulation_manager.py tests/api/test_simulation.py -q`; full suite 499 passed / 10 skipped / 3 deselected

### Task 16: Frontend Simulation Control

- [x] Task 16: `/simulations` page with per-vehicle cards, human names only
  - Types (`SimulationScenario/State/StartRequest/StatusResponse`) in `types/api.ts`; `services/simulations.ts`; `queryKeys.simulations`; `hooks/use-simulations.ts` (5s refetch, stale 2s, select items, placeholderData); `useStart/Stop/RestartSimulation` mutations (optimistic `setQueryData` on the unselected `PaginatedResponse` + invalidate); nav item "Simulation Control" (`CirclePlay`); `app/(app)/simulations/page.tsx` + `components/simulations/simulations-view.tsx`
  - UX: stopped/starting/running/stopping/error badge tones; scenario SelectMenu (Normal / High temperature / Low battery / High engine load); interval input 0.1–60 default 1; Start (stopped/error) / Restart / Stop (running); **staleness hint** when running but `last_telemetry_at` > 20 s old (addressed to broker/subscriber); inline error map 0/401/403/404/409/502/default; EmptyState linking to /vehicles; **no UUIDs ever rendered**
  - Tests (`__tests__/simulations-view.test.tsx`, 9): human names + no-UUID assertion, start payload (`{scenario, interval_seconds}`), stop, 409 → "already running", 502 → launcher message, stale-telemetry alert, empty state, error card, id never leaks even when statuses reference it
  - NOTE: post-mutation refetch flips badges back unless the `list` mock is sequenced (`mockResolvedValueOnce` then steady state); a stale hardcoded `last_telemetry_at` in fixtures makes EVERY card render the staleness alert — fixtures use `new Date().toISOString()`; `react-hooks/purity` forbids `Date.now()` in render → moved to `lib/format.isOlderThan`; setState-in-effect rule → derived `effectiveScenario/effectiveInterval` from `touched` instead of an effect
  - Verify: `npm run test -- --run` (92 passed / 12 files), `npm run lint`, `npm run typecheck` all clean

### Task 17: PowerShell infra scripts

- [x] Task 17: `scripts/dt-start.ps1` / `dt-stop.ps1` / `dt-status.ps1`
  - Managed hidden background processes for the local stack (Mosquitto via `mosquitto.local.conf`, uvicorn API, MQTT subscriber) with PID + log files under `%TEMP%\dtwin`; **infrastructure only** — per-vehicle simulators are owned by Simulation Control via the API and never started here
  - `dt-status.ps1` probes ports 1883/8000 and `GET /api/v1/health`
  - Verify: PowerShell parser AST check OK on all three (not executed end-to-end here)

### Task 18: Docs

- [x] Task 18: README and env docs
  - `backend/README.md`: §8 Windows convenience pointer to the scripts; §15 endpoints table +5 simulation rows; new §18 Simulation Control (semantics, contract notes — no PID leak, `last_telemetry_at` enrichment, not gated on `simulation_enabled`, scenarios = §17 table, orphan cleanup at startup); §13 test-suite bullet; §19 error table extended (409 conflict "simulation already active", 502 "simulator subprocess failed to launch"); sections renumbered 18→22
  - `backend/.env.example`: `SIMULATION_STARTUP_GRACE_SECONDS`, `SIMULATION_STOP_TIMEOUT_SECONDS`, `SIMULATION_RUNTIME_DIR` (commented default) block
  - NOTE: committed `backend/openapi.json` is a stale pre-Phase-3 snapshot (untouched since an old commit; live `/openapi.json` is correct — verified `GET /api/v1/simulations`, `GET/POST/DELETE /api/v1/vehicles/{vehicle_id}/simulation`, `POST .../restart`). Not regenerated to avoid importing unrelated phases into the diff.

### Checkpoint: Simulation Control
- [x] Backend full suite: **499 passed / 10 skipped / 3 deselected, exit 0** (465 baseline + 18 manager + 16 API); `ruff check .` clean (191 files); `ruff format --check .` clean (191 files); no orphaned `simulator` subprocesses after runs
- [x] Frontend: **92 tests / 12 files pass** (83 baseline + 9 new); `tsc --noEmit` clean; `eslint .` clean
- [x] OpenAPI live inventory matches contract: `/api/v1/simulations` (GET), `/api/v1/vehicles/{vehicle_id}/simulation` (GET/POST/DELETE), `/api/v1/vehicles/{vehicle_id}/simulation/restart` (POST)
- [ ] UNVERIFIED here, carried honestly: live `mqtt_e2e` simulation test (needs an MQTT broker at localhost:1883 — skips by design), GitHub Actions execution, `make` targets, and the PowerShell scripts being run end-to-end (parse-verified only)
