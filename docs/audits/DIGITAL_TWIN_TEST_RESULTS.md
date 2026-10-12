# Digital Twin — Test Results (supporting artifact)

**Companion to:** `DIGITAL_TWIN_SYSTEM_AUDIT_2026-10-11.md`
**Date:** 2026-10-11 · **Repo:** `C:\Users\Abhishek\Desktop\Digital Twin`

Only tests **actually executed during this audit** are counted below. No claim is made that a behavior works merely because a test exists.

---

## 1. Executed suites

| Suite | Command (workdir) | Result | Notes |
|---|---|---|---|
| Backend full | `.\\.venv\\Scripts\\python.exe -m pytest -q` (`backend`) | **674 collected · 664 passed · 10 skipped · 0 failed · exit 0** | skips are broker-dependent; `addopts="-q -m 'not mqtt_e2e'"` |
| Frontend unit | `npx vitest run` (`frontend`) | **22 files · 151 passed · 0 failed** | ~8 s |
| Frontend types | `npx tsc --noEmit` (`frontend`) | **exit 0** | clean |
| Backend lint | (not re-run this session) | — | reported clean earlier; not re-executed |

Pytest config — `backend/pyproject.toml:58-62`: `asyncio_mode="auto"`, `testpaths=["tests"]`, `addopts="-q -m 'not mqtt_e2e'"`, marker `mqtt_e2e`.

> `mqtt_e2e` tests require a running broker and are excluded by default, so **broker round-trips are not covered** by the run above.

---

## 2. Live probes executed

| Probe | Result |
|---|---|
| `GET /health` | ok |
| `GET /health/db` | ok |
| `POST /auth/login` (acceptance user) | 200; role `user` |
| `GET /workflow/status` | `subscriber_running=true`, `active_simulations=2`, `events_in_buffer=500`, finite oldest/newest event ts |
| `GET /workflow/state` | one vehicle; stages `mqtt_broker:degraded, mqtt_subscriber:success, parser:degraded, postgres:degraded, health_engine:running, health_snapshot:degraded`, reason `Newest telemetry is stale` |
| Read-only DB (BMW `a10ecde3…`) | 17 426 rows; 2 036 current-run + 15 390 legacy `NULL`; latest snapshot 1440 min, score 60, conf 0.5391, coverage 0.2017, `run_id=null` |
| Ownership | unowned demo vehicle → 404 |

---

## 3. What is well covered (Verified by inventory of executed tests)

- Health formulas: statistics, rules, scoring, penalty caps, confidence, thresholds.
- Rules engine output and severity classification.
- Live sufficiency gate and provisional states.
- Simulation start/stop/restart, run-id minting/propagation, stale cleanup.
- Ingestion idempotency and batch persistence.
- Health monitor selection, run resolution skip, escalation guard.
- Historical analytics across multiple runs and legacy segments.
- Snapshot persistence/immutability and history pagination.
- API authorization/ownership and validation.
- Frontend views: `vehicle-simulation-view.test.tsx`, `vehicle-analytics-view.test.tsx`, `vehicle-health-view.test.tsx`, hooks (`use-vehicle-data.test.tsx`).

---

## 4. Gaps (no executed test found)

- Window **selector → backend** equivalence (selector vs `analysis_window`).
- Historical rows excluded from **current** counts/alerts as a first-class assertion.
- `GET /health/live` **read-only** behavior (no snapshot on GET).
- Subscriber-level **out-of-order** ingestion.
- **DB-failure / MQTT-disconnect** end-to-end.
- **Alert lifecycle** (subsystem absent).
- **Large-window truncation** in `get_recent_telemetry` (ascending + LIMIT).

---

## 5. Proposed regression tests

1. `test_health_view_window_matches_analyze` — selector 60 → analyze → `GET /health` reports `window_minutes == 60`.
2. `test_live_endpoint_is_read_only` — two `GET /health/live` calls leave snapshot count unchanged.
3. `test_windowed_analyze_excludes_other_runs` — seed legacy + 2 runs; assert windowed population confined to its window and current-run assertions hold.
4. `test_recent_telemetry_limit_keeps_newest` — exceed `_window_limit`; assert newest timestamp present in analysis.
5. `test_stale_event_not_replayed_as_current` — stale buffered event → `/workflow/state` degraded, not success.

---

## 6. Limitations

- `mqtt_e2e` excluded; broker-dependent paths not exercised.
- No browser/E2E UI run; UI verified via unit tests + source + API/DB.
- ESLint not re-run this session.
- Tests run against the **current uncommitted working tree**.
