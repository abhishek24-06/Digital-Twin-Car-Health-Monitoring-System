# Digital Twin — Deployment, Migration & Operations

Companion to `docs/IMPLEMENTATION_ROADMAP.md` and
`docs/audits/DIGITAL_TWIN_SYSTEM_AUDIT_2026-10-11.md`.

Scope: how to build, verify, migrate and operate the backend **without ever
touching a hosted database destructively**. It is written so an operator can
run the exact steps; it does not assert that any hosted environment has been
migrated.

> **Never** run `alembic downgrade`, schema resets, `DROP`/`TRUNCATE`, or the
> destructive dev tooling against the hosted/Supabase database. Those tools
> already refuse a non-local target via `backend/app/core/db_target.py`; do not
> try to bypass that guard.

---

## 1. Build identity

The running process reports what it *is*:

| Setting | Env var | Meaning |
|---|---|---|
| `app_version` | `APP_VERSION` | Source version (`pyproject` / `APP_VERSION`). |
| `build_id` | `BUILD_ID` | Deployment stamp (git SHA, image tag, CI run id). Defaults to `unknown`. |
| `app_env` | `APP_ENV` | `development` \| `test` \| `production` (…). |
| `expected_schema_revision` | `EXPECTED_SCHEMA_REVISION` | The Alembic revision this build targets. |

Stamp `BUILD_ID` and `EXPECTED_SCHEMA_REVISION` at deploy time so a running
server can be matched to the artifact and schema it came from.

---

## 2. Verify a deployment (read-only)

`GET /api/v1/health/deployment` (admin-only) returns:

- `app_version`, `build_id`, `environment`;
- `database_reachable`;
- `database_schema_revision` (the database's recorded Alembic revision);
- `expected_schema_revision` and `migration_in_sync` (true/false/null);
- `features` — which notable API surfaces this process actually registered
  (`alerts_api`, `live_health_api`, `historical_analytics_api`), read from the
  generated OpenAPI schema;
- `diagnostics` — a secret-free explanation (schema drift, unmigrated DB,
  expected revision not configured, …).

It never applies a migration and never prints a connection string. A stale
server that predates a feature reports `features.<name> == false`, which is the
signal that the process must be restarted onto current code.

Quick checks:

```powershell
# Liveness (no DB) and reachability (SELECT 1)
curl.exe http://127.0.0.1:8000/api/v1/health
curl.exe http://127.0.0.1:8000/api/v1/health/db

# Which routes the running server actually exposes
curl.exe http://127.0.0.1:8000/openapi.json   # count/verify paths (e.g. /alerts)

# Admin-only deployment verification (needs a bearer token)
curl.exe -H "Authorization: Bearer <ACCESS_TOKEN>" ^
  http://127.0.0.1:8000/api/v1/health/deployment
```

The single Alembic head must stay single:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic heads      # expect exactly one head
.\.venv\Scripts\python.exe -m alembic history    # review the chain
```

---

## 3. Required secrets

The app **fails closed** outside explicitly opted-in local/test development:

- `JWT_SECRET` (aliases: `JSON_WEB_TOKEN_SECRET`) must be ≥ 32 random
  characters and not a known placeholder. A weak/empty value makes the app (and
  Alembic) refuse to start unless `APP_ENV` is one of `development`/`local`/`test`
  **and** `AUTH_ALLOW_INSECURE_DEV_SECRET=true`.
- `CORS_ORIGINS` must be set explicitly outside permissive environments; the
  built-in `http://localhost:3000` default is refused there.

Do not paste secrets into chat, tickets, logs or commits. Set them through the
deployment's secret store or the uncommitted `backend/.env`.

---

## 4. Applying a reviewed migration (hosted / production)

Preconditions:

1. The migration is reviewed and its head is the single expected head.
2. A **backup / point-in-time snapshot** exists on the provider (see §9). Do not
  proceed otherwise.
3. You have explicit authorization to migrate this environment.

Procedure:

```powershell
cd backend

# 1. Confirm what will run (no writes).
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic history --verbose

# 2. Back up out-of-band (provider snapshot / pg_dump --schema-only review).
#    Do NOT proceed without a restorable backup.

# 3. Apply reviewed, additive migrations.
.\.venv\Scripts\python.exe -m alembic upgrade head

# 4. Confirm the DB revision now matches the build.
.\.venv\Scripts\python.exe -m alembic current
```

Rollback is **only** for a migration you just applied and only on a disposable
target. For a hosted database, prefer a forward fix or restore-from-backup; the
schema must not be downgraded in place. A downgrade that drops a column or table
destroys historical telemetry/snapshots/alerts and is forbidden by policy.

### Migration-from-base caveat

The full chain **from an empty database** fails at `4f9d3c2b1a8e` on a local
Postgres without pgvector (the pgvector `DO $$ … EXCEPTION` block under
asyncpg) — pre-existing and unrelated. The single head is `e5f6a7b8c9d0`.
Migrations against an already-populated environment are unaffected.

---

## 5. Local migration upgrade/downgrade drill (disposable only)

Never point this at the hosted DB. Use a throwaway local database:

```powershell
# Create a throwaway DB, never the runtime one.
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE dtwin_migration_drill;"

$env:DATABASE_URL = "postgresql+asyncpg://postgres:root@127.0.0.1:5432/dtwin_migration_drill"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade -1
.\.venv\Scripts\python.exe -m alembic upgrade head

# Tear down the throwaway database afterwards.
```

---

## 6. Restarting the backend onto current code

The running server must be restarted to pick up code/migrations. It is started
without `--reload` (see `scripts/dt-status.ps1`), so a restart is explicit:

```powershell
# 1. Confirm the running server is stale (missing routes / old revision).
curl.exe http://127.0.0.1:8000/openapi.json | Select-String "/alerts"

# 2. Apply reviewed migrations (section 4) with a backup in place.

# 3. Restart via the project launcher / process manager, then re-verify:
curl.exe http://127.0.0.1:8000/api/v1/health/db
#    and GET /api/v1/health/deployment (admin) -> migration_in_sync == true
```

---

## 7. Worker model

The simulation manager keeps active-run state **in memory** and performs
stale-process cleanup at startup, and the rate limiters are process-local. The
supported deployment is therefore a **single backend worker** (one Uvicorn
process driving the API, MQTT subscriber and health monitor). Running multiple
API workers against shared databases/processes is not supported and would allow
duplicate simulation processes / conflicting monitors / per-worker rate limits.
Enforce (or clearly document) single-worker operation for the intended
deployment; do not assume the in-memory locks span workers.

---

## 8. Observability quick reference

- Workflow event persistence: see `docs/workflow-observability.md`.
- `GET /api/v1/health` (liveness, no DB), `GET /api/v1/health/db`
  (reachability), `GET /api/v1/health/deployment` (build/schema verification).
- Logs are structured; they must never contain passwords, JWTs, API keys or
  connection strings. Treat a log line that leaks a secret as a defect.

---

## 9. Backup & recovery assumptions

- **Authoritative/append-only:** telemetry rows, health snapshots, alerts and
  `alert_events`, workflow events, users, vehicles. None of these may be deleted
  or rewritten by tooling.
- **Where backups live:** managed by the database provider (Supabase). The exact
  backup schedule, PITR window and restore procedure must be confirmed in the
  provider console — this repository cannot attest that a backup was taken.
- **Local recovery drill:** perform restores only into a throwaway local
  database (create → restore → verify row counts → drop). Never test restore by
  dropping production objects.
- **After a database or backend restart:** run the deployment verification
  endpoint; reconcile active simulation state from `SimulationManager` status
  (startup cleanup reaps orphaned children by verified PID, never by stale PID
  alone).
