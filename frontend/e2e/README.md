# Browser acceptance suite (Phase D)

Real-browser acceptance for the vehicle workspace, driven by Playwright against
the **real** frontend and the **real** backend.

## What it is

- `playwright.config.ts` boots two isolated servers and tears them down:
  1. **backend** — `backend/scripts/run_e2e_backend.py`, which serves the real
     FastAPI app with `LLM_PRIMARY_PROVIDER=mock` / `LLM_FALLBACK_PROVIDER=mock`,
     the background health monitor disabled, and MQTT pointing at a dead port.
  2. **frontend** — `next dev` with `NEXT_PUBLIC_API_URL`/`BACKEND_API_URL`
     forced at that backend.
- `vehicle-acceptance.spec.ts` is the product-level suite; `support.ts` holds the
  shared login/vehicle helpers.

## Isolation guarantees

The backend launcher **fails closed**. It refuses to start unless
`E2E_DATABASE_URL`:

- is loopback (`127.0.0.1` / `localhost` / `::1`), and
- names a database called exactly `digital_twin_browser_test`, and
- contains none of `supabase`, `pooler`, `amazonaws`, `render.com`, `neon.tech`.

It then creates the schema (no `rag_` tables, so no pgvector extension needed),
re-seeds two owners / two vehicles / 90 telemetry rows, and **overwrites** the
process environment (including `DATABASE_URL`, `JWT_SECRET`, `CORS_ORIGINS`) so
nothing from `backend/.env` or the ambient shell can redirect it at real data.

Default database:

```
postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_browser_test
```

Override with `E2E_DATABASE_URL` (must still satisfy the rules above).

## Run it

```powershell
cd frontend
npm run test:e2e
```

Ports default to backend `8010` and frontend `3010`; override with
`E2E_BACKEND_PORT` / `E2E_FRONTEND_PORT`. Set `E2E_REUSE_SERVERS=1` to attach to
servers you started yourself (useful while debugging).

## Coverage

| Spec | Proves |
| --- | --- |
| unauthenticated redirect | protected routes send anonymous visitors to `/login` |
| wrong password | rejection is shown in place, no session is created |
| eight tabs | Overview, Live Health, Simulation, Analytics, Telemetry, AI Diagnosis, History, Alerts each render their own content in the real app |
| agent diagnosis | the real agent graph produces a diagnosis card with the deterministic provider |
| cross-account access | a second account gets a 403/404 (never data) for someone else's vehicle |
| phone layout | the workspace has no horizontal overflow at 375 px |
| console/network | browsing every tab logs no uncaught errors, failed requests or 5xx API responses |

## Not covered yet

These remain open and are tracked in `docs/IMPLEMENTATION_ROADMAP.md`:

- SSE reconnect after the telemetry/workflow stream drops mid-session.
- Provider-failure UI (needs a second backend whose LLM provider is made to
  fail; the mock provider never fails).
- Alerts lifecycle mutations (acknowledge/resolve) in the browser.
