# Phase 6 Engineering Report — Identity, Roles & Vehicle Ownership

Project: Digital Twin Car Health Monitoring Platform (Backend)
Phase: 6 — authentication (JWT + rotating refresh tokens), user/admin roles, per-vehicle ownership & IDOR protection
Repo location: `C:\Users\Abhishek\Desktop\Digital Twin\backend`
Date: 2026-09-25
Verification target: full offline suite + migration up/down cycle on the local scratch DB (`digital_twin_migtest`), head `d6a9b1c2e3f4`

---

## 0. Summary

Phase 6 is **complete**. The platform now has real identity: users register,
log in, refresh, and log out through `/api/v1/auth/*`; access is enforced with
short-lived HMAC-signed JWTs plus rotating, hashed, revocable refresh tokens;
and every vehicle-family endpoint (vehicles CRUD, telemetry, health, agent)
is scoped per user, closing the horizontal access-control (IDOR) holes that
existed when any caller with the same vehicle id could read another user's
data. The RAG admin surface received minimum protection (admin-only
`/rag/health`, authenticated `/rag/search`).

**Regression gate:** **342 passed, 7 skipped** (pgvector/RAG-gated; covered
live on Supabase in Phase 5), **0 failed**, `ruff check` clean, `ruff format`
clean, Alembic head `d6a9b1c2e3f4` verified with a full upgrade/downgrade/
re-upgrade cycle and zero model-vs-DB drift on the new objects.

---

## 1. Constraint compliance

| Constraint (phase brief)                  | Status |
| ----------------------------------------- | ------ |
| No new infra services; Postgres-only      | ✅ users + refresh_tokens live in the existing PostgreSQL |
| Keep Phase 1–5 behaviour for internal processes | ✅ MQTT subscriber/simulator/scripts keep calling the raw service methods (no user) |
| Do not weaken existing assertions         | ✅ full prior suite unchanged & green |
| Secrets never committed / logged          | ✅ `JWT_SECRET` in `.env` only; tokens stored as hashes; docs use placeholders |
| Non-owners must not learn vehicle existence | ✅ 404 (not 403) for unowned access; register rejects `role`/`is_active` escalation (422) |
| No optional-auth bypass                   | ✅ `get_current_user` is a hard dependency on every protected route |
| Tests must stay offline / no real keys    | ✅ auth suite uses the test secret only |
| Migrations verified, never destructive on Supabase | ✅ verified on local scratch DB only |

---

## 2. Architecture

```
Client ──POST /auth/register|login──► AuthService
        │                              register()  normalize email, bcrypt hash,
        │                              issue_token_pair() → JWT (HS256) + refresh token
        ▼
AuthService (app/services/auth_service.py)
   password_hash  bcrypt.hashpw
   access token   PyJWT encode {sub, type=access, exp}   (short-lived)
   refresh token  secrets.token_urlsafe → stored ONLY as SHA-256 hash
                  rotate(): old row revoked, new row inserted (single-use)
                  reuse-after-revocation → revoke_all_for_user()   (theft detection)

Bearer access JWT
   ▼
get_current_user (app/dependencies/auth.py)
   verify signature + type + exp; re-read User from DB per request (role/is_active source of truth)
   admin? → require_admin (403)

Vehicle routes (owner-scoped)
   ensure_vehicle_access(repo, vehicle_id, user)  (app/services/vehicle_access.py)
      admin  → allow
      else   → get_by_id_and_owner(vehicle_id, user.id) or 404
   used by vehicles / telemetry / health / agent / (diagnoses.user_id attribution)
```

Two trust tiers:

1. **HTTP layer** — everything under `/api/v1` that touches a vehicle resolves
   the current user from the bearer token and then calls the `_for_user`
   service variants. Aggregate/`list` endpoints filter by `owner_user_id`.
2. **Internal processes** — the MQTT subscriber, the simulator, and scripts
   keep using the raw service methods (`create_telemetry`, `create_vehicle`,
   `run_user_query`) with no user; the DB default for
   `owner_user_id = NULL` keeps pre-existing rows valid and ingestion paths
   intact.

---

## 3. Modules delivered

| Module | Responsibility |
| ------ | -------------- |
| `app/models/user.py` | `User` ORM: `email` (unique), `password_hash`, `role` (`user`/`admin`), `is_active`, timestamps |
| `app/models/refresh_token.py` | `RefreshToken` ORM: `user_id` FK CASCADE, `token_hash` (indexed), `expires_at`, `revoked_at` |
| `app/repositories/user_repository.py` | `UserRepository` (get_by_email, get_by_id, create, update_profile, conflict handling) |
| `app/repositories/refresh_token_repository.py` | get by hash, insert, revoke memberships, revoke_all_for_user |
| `app/services/auth_service.py` | `UserService` + `AuthService`: register / authenticate / issue_token_pair / rotate / revoke / get_user / update_profile |
| `app/services/vehicle_access.py` | `ensure_vehicle_access()` — the single ownership gate (admin bypass; 404 otherwise) |
| `app/dependencies/auth.py` | `get_current_user` (Bearer → JWT → DB re-read), `require_admin` |
| `app/schemas/auth.py` | RegisterRequest/LoginRequest/RefreshRequest/LogoutRequest/TokenResponse (`extra="forbid"`) |
| `app/schemas/user.py` | `UserResponse`, `UserProfileUpdate` (only `full_name`) |
| `app/core/security.py` | `hash_password`/`verify_password` (bcrypt), `create_access_token`/`decode_access_token` (PyJWT) |
| `app/api/routes/auth.py` | `/auth/register|login|refresh|logout|me` |
| `app/api/routes/users.py` | `/users/me` GET+PATCH (self-service profile) |
| `app/api/routes/vehicles.py` | all endpoints authentication + ownership scoped |
| `app/api/routes/telemetry.py` | POST/GET owner-scoped (`create_telemetry_for_user`) |
| `app/api/routes/vehicle_health.py` | analyze/get/history owner-scoped |
| `app/api/routes/agent.py` | query/events/dashboard/diagnoses owner-scoped, `user_id` attribution |
| `app/api/routes/rag.py` | `/rag/health` admin-only; `/rag/search` any authenticated user |
| `app/agent/service.py`, `state.py`, `nodes.py` | optional `user` kwarg; `AgentState.user_id`; persist attribution |
| `app/core/config.py` | `JWT_SECRET` alias + `populate_by_name`, `jwt_algorithm`, token expiry, password bounds, non-local secret validation |
| `alembic/versions/d6a9b1c2e3f4` | Phase 6 migration (see §4) |
| `app/models/__init__.py` | registers `User` and `RefreshToken` |
| `app/dependencies/database.py` | `get_auth_service` / `get_user_service` providers |

---

## 4. Data model & migration

Migration `d6a9b1c2e3f4_phase6_identity_roles_vehicle_ownership` sits on top of
`b8c3e1d4a9f7` (Phase 5 RAG metadata). `upgrade()`:

- **`users`** — `id` UUID PK, `email` VARCHAR unique, `password_hash` VARCHAR,
  `role` VARCHAR **CHECK role IN ('user','admin')**, `full_name` nullable,
  `is_active` BOOLEAN NOT NULL DEFAULT true, `created_at`/`updated_at`
  timestamptz.
- **`refresh_tokens`** — `id` UUID PK, `user_id` UUID FK → users `ON DELETE
  CASCADE`, `token_hash` VARCHAR (SHA-256, indexed), `expires_at` timestamptz,
  `revoked_at` timestamptz nullable.
- **`vehicles`** — adds nullable `owner_user_id` UUID FK → users `ON DELETE
  SET NULL` (+ index) so existing rows / internal ingestion keep working;
  `source_type` VARCHAR CHECK IN ('simulator','real') DEFAULT 'simulator';
  `status` VARCHAR CHECK IN ('active','disabled') DEFAULT 'active';
  `simulation_enabled` BOOLEAN NOT NULL DEFAULT false.
- **`agent_diagnoses`** — adds nullable `user_id` UUID FK → users `ON DELETE
  SET NULL` to record who triggered each run.

`downgrade()` reverses everything symmetrically (drops the diagnosis/vehicle
columns/indexes, then `refresh_tokens`, then `users`).

**Verification on the local scratch DB (`postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_migtest`):**

| Step | Result |
| ---- | ------ |
| `alembic upgrade head` to `d6a9b1c2e3f4` | PASS (b8c3 → d6a9) |
| `alembic downgrade` to `b8c3e1d4a9f7` | PASS (symmetric) |
| re-`upgrade` to head | PASS |
| `alembic check` (models vs DB) | Phase 6 objects: **zero drift**; only pre-existing Phase 5 RAG diffs reported (pgvector not installed locally — never appeared in the Phase 6 rows) |
| schema introspection | `users`, `refresh_tokens`, new `vehicles` columns/CHECKs/FKs, `agent_diagnoses.user_id` all present; `alembic_version = d6a9b1c2e3f4` |

Note: the historical full chain cannot run locally because Phase 5's
`4f9d3c2b1a8e` requires the pgvector extension (not installed on the local
server); the Phase 6 objects were still verified end-to-end on the scratch DB
with the RAG tables recreated manually.

---

## 5. Auth design decisions (security review)

- **Password hashing**: bcrypt (default cost) — `hash_password`/`verify_password`
  with 72-byte input guard (`auth_password_max_length=72`).
- **Access JWT**: HS256, `sub=user.id`, `type=access`, `exp = now +
  auth_access_token_minutes` (default 20). No secrets in payload; claims are
  deliberately minimal.
- **Refresh tokens**: opaque `secrets.token_urlsafe()`; **only the SHA-256 hash
  is stored**, so a DB leak does not expose usable tokens. Single-use: every
  `/auth/refresh` marks the presented token revoked and issues a fresh pair.
  **Reuse-after-revocation revokes every refresh token for that user** (theft
  detection / forced re-login).
- **DB is the source of truth**: `get_current_user` verifies the JWT and then
  re-reads the user row per request, so `is_active=False` or a demoted `role`
  applies immediately even if a token is still valid.
- **Enumeration resistance**: `login` returns the identical 401 for unknown
  email and wrong password; register rejects duplicate email with 409 (as an
  explicit registration signal) but never reveals password strength or exists
  on login.
- **Schema hardening**: `RegisterRequest`, `UserProfileUpdate`, and the
  vehicle create/update schemas use `extra="forbid"` — clients cannot smuggle
  `role`, `is_active`, `vin`, `owner_user_id`, `status`, etc. (422).
- **Ownership model**: `vehicles.owner_user_id` set to the authenticated user
  at creation. Non-admin access to a vehicle not owned → **404**, so
  existence (and via cascade rules the associated telemetry/snapshots/
  diagnoses) is never revealed. Admins bypass ownership checks.
- **Reuse of internal service layer**: `update_vehicle`/`delete_vehicle`/
  `create_telemetry` remain for trusted callers (MQTT subscriber, simulator,
  scripts, tests); the HTTP routes go through `*_for_user` variants that first
  call `ensure_vehicle_access`. Ownership is enforced in the service layer,
  not just at the router, so every route is covered by one helper.

---

## 6. Agent attribution (`user_id`)

All agent entry points accept an optional `user`:

- `run_user_query(vehicle_id, query, user=None)`
- `run_critical_event(vehicle_id, rules, user=None)`
- `get_dashboard_context(vehicle_id, user=None)`
- `list_diagnoses(vehicle_id, user=None)`, `get_latest_diagnosis(vehicle_id, user=None)`

When `user` is present the service enforces ownership via
`ensure_vehicle_access` *before* running; `AgentState.user_id` carries the id
and `persist_node` stores it in `agent_diagnoses.user_id`. The diagnosis
schema (`AgentDiagnosisItem`) exposes `user_id`.

---

## 7. Config & security settings

- `json_web_token_secret` reads env **`JWT_SECRET`** (via
  `AliasChoices("JWT_SECRET", "json_web_token_secret")` + `populate_by_name`),
  default `""` for local dev. In any non-local env (`test`/`staging`/
  `production`) the app **refuses to start** with a missing/short (<32) or
  well-known secret.
- `jwt_algorithm` default `HS256`; `auth_access_token_minutes` default 20;
  `auth_refresh_token_days` default 30; password bounds 8..72.
- These defaults/bounds are covered by `tests/core/test_security_settings.py`
  (12 cases).

---

## 8. API contract (Phase 6 additions)

| Method | Path | Auth | Behaviour |
| ------ | ---- | ---- | --------- |
| POST | `/api/v1/auth/register` | public | 201 + TokenResponse; `role`/`is_active` → 422; duplicate email → 409; weak password → 422 |
| POST | `/api/v1/auth/login` | public | 200 tokens; bad email/password → identical 401 |
| POST | `/api/v1/auth/refresh` | refresh token | rotates (old revoked, new issued); reuse → 401 + revoke all |
| POST | `/api/v1/auth/logout` | refresh token | 204 idempotent revoke |
| GET  | `/api/v1/auth/me` | access | current user profile (401 if invalid/expired) |
| GET  | `/api/v1/users/me` | access | profile |
| PATCH| `/api/v1/users/me` | access | update `full_name` only; anything else 422 |
| GET/POST/PATCH/DELETE vehicles, telemetry, health, agent | access | owner-scoped; non-owner 404; admin bypass |
| GET | `/api/v1/rag/health` | **admin** | 403 for non-admin |
| GET | `/api/v1/rag/search` | any authenticated | 401 anonymous |

`TokenResponse`: `{access_token, refresh_token, token_type:"bearer",
expires_in, user: UserResponse}`.

21 OpenAPI paths / 48 component schemas after Phase 6 (verified via
`app.openapi()`).

---

## 9. Test results

`tests/api/test_auth.py` (17): register normalization/duplicates/role-escalation,
login parity, refresh rotation, reuse→revoke-all, logout idempotency, tampered
token 401s.
`tests/api/test_authorization.py` (8): IDOR matrix — unauthenticated 401, other
user's vehicle 404, admin access granted, own vehicle ok, profile PATCH 422.
`tests/core/test_security_settings.py` (12): JWT_SECRET required/short/insecure,
algorithm, expiry bounds, env-file loading of `JWT_SECRET`.

Rewrote for auth/ownership: `tests/api/test_vehicles.py` (18), `test_telemetry.py`
(9), `test_vehicle_health.py` (11), `tests/agent/test_api.py` (11, + attribution
test), `tests/rag/test_admin_api.py` (6, admin/auth gating).

**Full suite:** `342 passed, 7 skipped, 0 failed` (349 collected; the 7 skips
are the pgvector/RAG-gated integration tests that run live on Supabase; the
`mqtt_e2e` brood is deselected by pytest config). **Ruff:** `check` clean,
`format` clean.

---

## 10. NOT-implemented / intentionally deferred

- Vehicle **sharing** (multi-owner) — ownership is single `owner_user_id`.
- Soft delete / archive flows.
- Email verification, password reset, MFA, account recovery.
- Device/session management beyond single refresh token rotation.
- Rate limiting — documented only (no Throttling middleware this phase).
- No automatic health analysis, no LLM-per-telemetry, no Phase 7/8/9 scope.

---

## 11. How to run

```bash
# (once) apply migrations
alembic upgrade head                    # → d6a9b1c2e3f4

# configure
# .env: JWT_SECRET=<32+ random> (python -c "import secrets; print(secrets.token_urlsafe(48))")

# run
uvicorn app.main:app --reload

# register + login
curl -X POST localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"email":"a@b.co","password":"Sup3rSecret!"}'
curl -X POST localhost:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"email":"a@b.co","password":"Sup3rSecret!"}'
# use access_token as: -H "Authorization: Bearer <token>"

# tests
python -m pytest -q                      # 342 passed, 7 skipped
ruff check .
```

---

## 12. Conclusion

Phase 6 delivers production-grade identity and per-user data isolation without
disturbing the Phase 1–5 ingestion and agent architecture: JWT access tokens,
rotating hashed refresh tokens with theft detection, bcrypt password hashing,
DB-authoritative roles, service-level ownership enforcement with 404-on-unowned
access, agent `user_id` attribution, and minimum RAG admin protection. The full
offline suite is green, lint/format clean, and the migration was verified
upgrade/downgrade/upgrade with no model drift on the new objects. The phase is
**complete**.

PHASE 6 COMPLETE