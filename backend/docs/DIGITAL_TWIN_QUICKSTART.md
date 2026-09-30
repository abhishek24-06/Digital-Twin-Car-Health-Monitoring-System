# Digital Twin — Quickstart

Fast way to run the Digital Twin Car Health Monitoring backend (Phases 1–6)
locally, ingest telemetry, and see a health assessment + agent diagnosis.
Fuller reference: `docs/DIGITAL_TWIN_COMPLETE_SYSTEM_GUIDE.md`.

## 1. Prerequisites

- Python 3.12+
- PostgreSQL 16+ (or Supabase connection string)
- Mosquitto (local dev) **or** Docker

## 2. Install & configure

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -e ".[dev]"       # or: make install

copy .env.example .env        # then edit .env (DATABASE_URL, MQTT_*, JWT_SECRET, keys)

# Phase 6 requires a JWT_SECRET (>= 32 chars); generate one with:
python -c "import secrets; print(secrets.token_urlsafe(48))"

alembic upgrade head          # or: make migrate
```

Everything can also be set as real environment variables. `.env` is
git-ignored — never commit secrets.

## 3. Run the full stack (no Docker)

```bash
# Terminal A — broker
mosquitto -c infrastructure/mosquitto/mosquitto.local.conf

# Terminal B — API
make dev                      # uvicorn app.main:app --reload  (port 8000)

# Terminal C — subscriber
make mqtt-subscriber          # python -m app.mqtt.subscriber

# Terminal D — seed vehicle + simulator
make seed-demo-vehicle        # python -m scripts.seed_demo_vehicle
make simulator                # python -m simulator.main
```

Check it works:

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/db
curl "http://localhost:8000/api/v1/vehicles/11111111-2222-4333-8444-555555555555/telemetry?page_size=3"
```

## 4. Or run with Docker

```bash
make up                       # docker compose up --build -d
make logs                     # follow logs
make down                     # stop
```

Services: `postgres` (5432), `backend` (8000, runs migrations first),
`mosquitto` (1883, dev creds `mqtt`/`mqtt`), `mqtt-subscriber`, `simulator`.

## 5. One API tour

> Phase 6 locked down the vehicle endpoints: every call below needs
> `-H "Authorization: Bearer $ACCESS_TOKEN"`, and non-admin users only see
> their own vehicles (404 otherwise). Register/login first:

```bash
# Create an account + get tokens (Phase 6)
curl -X POST http://localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"Sup3rSecret!","full_name":"Ada"}'
# capture access_token + refresh_token from the JSON response

export ACCESS_TOKEN=<access_token>    # then use -H "Authorization: Bearer $ACCESS_TOKEN"

# Register a vehicle (201) — becomes owned by you
curl -X POST http://localhost:8000/api/v1/vehicles -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"vin":"TESTVIN123456789","make":"Toyota","model":"Camry","year":2024,"engine_type":"2.5L Petrol"}'

# Ingest a telemetry sample (201; idempotent with source_event_id)
curl -X POST http://localhost:8000/api/v1/vehicles/<vehicle_id>/telemetry \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"timestamp":"2026-09-20T08:30:12Z","rpm":3200,"speed":74.0,"engine_load":82.4,
       "coolant_temperature":104.2,"oil_temperature":97.0,"battery_voltage":12.1,
       "fuel_level":64.0,"intake_air_temperature":32.0,"throttle_position":41.0,
       "engine_runtime":1820,"odometer":42150.2,"source_event_id":"sample-1"}'

# Analyze + read health context
curl -X POST http://localhost:8000/api/v1/vehicles/<vehicle_id>/health/analyze \
  -H "Authorization: Bearer $ACCESS_TOKEN"
curl http://localhost:8000/api/v1/vehicles/<vehicle_id>/health \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# Agent diagnosis (set OPENROUTER_API_KEY/GROQ_API_KEY in .env first)
curl -X POST http://localhost:8000/api/v1/vehicles/<vehicle_id>/agent/query \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"Should I worry about the coolant temperature?"}'

# No-LLM dashboard snapshot
curl http://localhost:8000/api/v1/vehicles/<vehicle_id>/agent/dashboard \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Samples: open the simulator alive → send >10 samples → score stops being
`unknown`. Rotate/revoke access with `/api/v1/auth/refresh` and
`/api/v1/auth/logout`; get your profile with `GET /api/v1/users/me`.

## 6. RAG (Phase 5) — quick

Requires pgvector in the DB (Supabase has it; local must
`CREATE EXTENSION vector`).

```bash
# Ingest a manual
python scripts/ingest_documents.py "data/my_manual.md" --make Toyota --model Camry --year 2024

# Search it
python scripts/query_rag.py "coolant level" --make Toyota --model Camry --year 2024 --top-k 3

# Status (admin-only in the API; needs an admin bearer token)
curl http://localhost:8000/api/v1/rag/health -H "Authorization: Bearer $ADMIN_TOKEN"

# Live E2E guardrail verification
python scripts/phase5_agent_rag_verify.py
```

`/api/v1/rag/search` needs any authenticated user; `/api/v1/rag/health`
requires the `admin` role (403 otherwise).

## 7. Test & lint

```bash
set TEST_DATABASE_URL=postgresql+asyncpg://postgres:root@localhost:5432/digital_twin_test
make test                # 342 passed / 7 skipped / 0 failed (broker e2e excluded)
make lint                # ruff check .
make format              # ruff check --fix + ruff format .
```

Test DB safety rail: the harness refuses to run against hosted DBs
(`supabase`/`pooler`).

## 8. Troubleshooting cheat-sheet

| Problem | Fix |
| ------- | --- |
| `/health/db` degraded | `DATABASE_URL` unreachable → `make db-check` |
| Subscriber reconnects forever | Broker down / wrong creds (`MQTT_USERNAME`/`MQTT_PASSWORD`) |
| Windows subscriber crashes | Remove shared `MQTT_CLIENT_ID` (default is per-process unique) |
| Score is `unknown` | Not enough samples in window — let the simulator run longer |
| RAG 503 | `RAG_ENABLED=false` or no pgvector on the DB |
| Agent 502/503/504 | Provider key missing/invalid/rate-limited — `RUN_LLM_SMOKE_TEST=true python -m scripts.smoke_agent_llm` |
| Supabase times out | Prefer direct connection; add `?ssl=require`; never Transaction-mode pooling |
| API won't start: JWT_SECRET error | Missing/short secret — set `JWT_SECRET` (>= 32 chars) in `.env` |
| Vehicle/telemetry calls 401 | No (or expired) `Authorization: Bearer <token>` header; re-login or refresh |
| Vehicle/telemetry calls 404 on your own car | Token belongs to a different account, or the route requires ownership; login as the owner or use an admin token |

## 9. Migration chain (head)

`e01c2724f67b → 7e38f4f3d70b → a1b2c3d4e5f6 → c7f2e8a1b3d4 → 4f9d3c2b1a8e → b8c3e1d4a9f7 → d6a9b1c2e3f4`

`make migrate` to reach head; verify with `make db-current*`. Head is
`d6a9b1c2e3f4` (Phase 6: `users`, `refresh_tokens`, vehicle ownership).