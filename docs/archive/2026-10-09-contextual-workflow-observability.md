# Contextual Workflow Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the existing workflow event stream as honest, contextual pipelines inside the five feature pages, while `/workflow` stays the global observability view.

**Architecture:** HYBRID — bridge low-frequency lifecycle events onto the existing in-process event bus (subscriber lifecycle, simulation, health, RAG, agent, stream), and derive high-frequency telemetry flow from real process/DB state exposed by a read-only `GET /workflow/state`. One shared frontend SSE provider feeds scoped selectors and reusable pipeline components. No per-message bridge, no LISTEN/NOTIFY, no second event system, no fake progress.

**Tech Stack:** Python 3.12+ / FastAPI / asyncio / Pydantic v2 / SQLAlchemy async / pytest (`asyncio_mode=auto`); Next.js (App Router) / React / TypeScript / Zustand + React Query / Vitest + Testing Library; Ruff; ESLint.

**Spec:** `docs/superpowers/specs/2026-10-09-contextual-workflow-observability-design.md`

## Global Constraints

- Backend `WorkflowStatus` vocabulary is exactly `STARTED, RUNNING, SUCCESS, WARNING, DEGRADED, ERROR, SKIPPED`. `WAITING` is **frontend-only** and must never be persisted; derived stages with no signal are *omitted* from `/workflow/state` and rendered `WAITING` by the frontend.
- No new DB tables, no migrations, no schema changes to telemetry/health/RAG. Reuse the existing bus (capacity 500, max subscribers 50) and the existing `publish_workflow_event(...)` (fire-and-forget).
- Do not modify: health scoring/thresholds/baselines, RAG ranking, BGE-M3/reranker config, LangGraph logic, LLM fallback, auth/ownership semantics, MQTT client IDs, process-supervision architecture. Instrumentation is emit-only.
- All new response fields are additive and optional (`correlation_id: str | None = None`). `sanitize_metadata` behaviour is unchanged.
- Honest wording: the `parser` stage means *confirmed healthy telemetry flow* (never "processed this message"); the `mqtt_broker` stage means *flow observed* (never "Mosquitto healthy"), and a stopped subscriber never asserts broker `ERROR` without direct evidence.
- Reuse the existing design system (`Badge`, `Card`, `Button`, `InlineAlert`, `EmptyState`, `ErrorState`, `Skeleton`, `Tooltip`). No new UI library. Not colour-only; responsive.
- Windows/PowerShell workflow: no `make`; use venv + `python -m ...`. Do not run broad process kills.
- Commands: backend `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`; frontend `npm test`, `npm run typecheck`, `npm run lint`.
- Source of truth: the Spec above. If this plan and the spec disagree, the spec wins — stop and reconcile.

## Review Focus

The spec implies these inputs/conditions that no single task's happy-path test may exercise; each is pinned to the owning task's tests. Most likely to bite first:

1. **Running simulator + offline subscriber** — the pipeline must show subscriber `ERROR` + downstream `WAITING`, never hollow success (Task 11/19).
2. **Cross-user leak** — a non-admin must never receive another user's `vehicle_id` events, nor any `rag_ingestion` event, on either `/events/recent` or `/events/stream` (Task 5/6).
3. **Subscriber alive, no telemetry** — `mqtt_broker` is `DEGRADED` with a flow-based reason; `parser` wording stays "flow observed" (Task 11/17).
4. **Reconnect with a `correlation_id` scope** — the filter survives reconnects and no `EventSource` leaks (Task 14).
5. **Unknown/absent stage** — the frontend renders `WAITING` and the backend never emits `WAITING` (Task 17/18).

---

## File Structure

**Backend (modify unless noted):**
- `app/schemas/workflow.py` — status/stage enums, derived-state models, `new_correlation_id`.
- `app/api/routes/workflow.py` — SSE fix, filters, `/workflow/state`, ownership.
- `app/services/telemetry_pipeline_state.py` — **new**, derived telemetry stages.
- `app/services/subscriber_manager.py` — lifecycle events.
- `app/services/simulation_manager.py`, `app/api/routes/simulation.py` — share one correlation id.
- `app/rag/ingestion.py` — `document_id` on all events + `correlation_id` on report.
- `app/rag/rag_service.py` — instrument `search_evidence`/`_retrieve`, `RAG_QUERY_ERROR`.
- `app/agent/nodes.py`, `app/agent/service.py`, `app/agent/schemas.py` — `AGENT_ERROR`, response `correlation_id`.
- `app/rag/admin_documents.py`, `app/schemas/rag.py` — thread `correlation_id` into `AdminRagUploadResponse`.
- `app/repositories/vehicle_repository.py` — `list_ids_by_owner`.
- `app/rag/schemas.py` — `RAGSearchResult.correlation_id`.

**Frontend (create unless noted):**
- `src/app/api/workflow/events/stream/route.ts` — forward `correlation_id`.
- `src/types/api.ts` — enums, derived-state types, response `correlation_id`.
- `src/services/workflow.ts` — `getState`.
- `src/components/workflow/workflow-stream-provider.tsx` — **new**, single SSE + scoped selectors. (Replaces per-instance `useWorkflowEvents` for contextual use; `use-workflow.ts` stays for the Monitor's REST paging.)
- `src/components/workflow/status.tsx` — status meta + `WorkflowStatusBadge`.
- `src/components/workflow/pipeline.tsx` — `WorkflowPipeline` + `WorkflowPipelineStep` + `WorkflowConnectionIndicator`.
- `src/components/workflow/pipelines.ts` — `PIPELINES` registry + `deriveStageStates`.
- `src/components/workflow/contextual-pipeline.tsx` — thin page-facing wrapper.
- Refactor: the five `pipeline-*.tsx` + `workflow-view.tsx`.
- Page views: `src/components/simulations/simulations-view.tsx`, `src/components/admin/admin-rag-view.tsx`, `src/components/rag/rag-search-view.tsx`, `src/components/vehicles/vehicle-health-view.tsx`, `src/components/vehicles/vehicle-diagnosis-view.tsx`.
- `src/components/layout/app-shell.tsx` — mount the provider.

---

## Phase 1 — Backend foundations

### Task 1: Extend workflow status/stage enums

**Files:**
- Modify: `backend/app/schemas/workflow.py` (enum defs near lines 17–125)
- Test: `backend/tests/schemas/test_workflow_schemas.py` (new)

**Interfaces:**
- Consumes: existing `WorkflowStatus`, `WorkflowStage` StrEnums.
- Produces: `WorkflowStatus.DEGRADED = "degraded"`, `WorkflowStatus.SKIPPED = "skipped"`; `WorkflowStage.STREAM_CONNECTED = "stream_connected"`, `WorkflowStage.STREAM_DISCONNECTED = "stream_disconnected"`.

- [ ] **Step 1: Write the failing test**

```python
def test_status_vocabulary_is_exact():
    assert {s.value for s in WorkflowStatus} == {
        "started", "running", "success", "warning", "degraded", "error", "skipped",
    }

def test_stream_stages_exist():
    assert WorkflowStage.STREAM_CONNECTED.value == "stream_connected"
    assert WorkflowStage.STREAM_DISCONNECTED.value == "stream_disconnected"

def test_workflow_event_accepts_degraded():
    ev = WorkflowEvent(workflow=WorkflowType.SYSTEM, stage=WorkflowStage.STREAM_CONNECTED,
                       status=WorkflowStatus.DEGRADED, message="x")
    assert ev.status is WorkflowStatus.DEGRADED
```

- [ ] **Step 2: Run test to verify it fails** — `python -m pytest tests/schemas/test_workflow_schemas.py -v` → FAIL (`degraded` not in enum / no `STREAM_CONNECTED`).
- [ ] **Step 3: Add the enum members** in `workflow.py`; keep existing members and values unchanged.
- [ ] **Step 4: Run test to verify it passes** — same command → PASS.
- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/workflow.py backend/tests/schemas/test_workflow_schemas.py
git commit -m "feat(workflow): add degraded/skipped statuses and stream stages"
```

### Task 2: One correlation-id helper shared by route + manager

**Files:**
- Modify: `backend/app/schemas/workflow.py` (add helper), `backend/app/services/simulation_manager.py:252,301,357,562`, `backend/app/api/routes/simulation.py:154,222,261`
- Test: `backend/tests/core/test_correlation.py` (new)

**Interfaces:**
- Produces: `new_correlation_id(prefix: str) -> str` returning `f"{prefix}-{uuid4().hex[:12]}"` (non-empty, unique). `SimulationManager.start/stop/restart` gain an optional `correlation_id: str | None = None` keyword; when supplied they publish all stages under that id, otherwise they generate one via `new_correlation_id("sim")`.
- Consumes: `SimulationStatus` returned by the manager gains `correlation_id: str | None = None` so the route can echo it.

- [ ] **Step 1: Write failing tests** — test 1: `new_correlation_id("sim")` starts with `"sim-"` and two calls differ. Test 2 (`tests/services/test_simulation_manager.py`): start with `correlation_id="sim-shared-1"` and assert every `SIMULATION_*` event captured from a fake bus carries `"sim-shared-1"`.
- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/core/test_correlation.py tests/services/test_simulation_manager.py -v`.
- [ ] **Step 3: Implement** `new_correlation_id`; thread the kwarg through the manager and have the route compute it once (`new_correlation_id("sim-api")`) and pass it in. Do not change supervision behaviour.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "refactor(workflow): single correlation id per simulation operation"`

### Task 3: Derived telemetry-state schemas

**Files:**
- Modify: `backend/app/schemas/workflow.py`
- Test: `backend/tests/schemas/test_workflow_schemas.py`

**Interfaces:**
- Produces:
```python
class TelemetryStage(StrEnum):  # simulator|mqtt_publish|mqtt_broker|mqtt_subscriber|parser|postgres|health_engine|health_snapshot
class StageState(BaseModel):    # stage: TelemetryStage; status: WorkflowStatus; observation: Literal["observed","derived"]; at: datetime|None; detail: str|None
class VehicleTelemetryState(BaseModel):  # vehicle_id: UUID; simulation_status: str; stages: list[StageState]; last_telemetry_at: datetime|None; messages_received: int; snapshot_at: datetime|None; degraded_reason: str|None; updated_at: datetime
class WorkflowStateResponse(BaseModel):  # items: list[VehicleTelemetryState]
```

- [ ] **Step 1: Write failing test** — construct a `StageState(stage=TelemetryStage.parser, status=WorkflowStatus.SUCCESS, observation="derived", at=None, detail="flow observed")` and assert it round-trips; assert `TelemetryStage` has exactly the 8 members; assert `StageState(status=WorkflowStatus(...))` rejects `"waiting"`.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement the models.** `observation` is a `Literal["observed","derived"]`; it is `"derived"` for every stage `/workflow/state` produces.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow): derived telemetry state schemas"`

---

## Phase 2 — Backend routes: fix + filter

### Task 4: Fix the SSE connection event and add `correlation_id` filtering

**Files:**
- Modify: `backend/app/api/routes/workflow.py:128-199`
- Test: `backend/tests/api/test_workflow_routes.py` (new)

**Interfaces:**
- Consumes: `new_correlation_id`, `WorkflowType.SYSTEM`, `WorkflowStage.STREAM_CONNECTED/DISCONNECTED`.
- Produces: `GET /workflow/events/stream` accepts `correlation_id: str | None`; first frame is a `SYSTEM`/`STREAM_CONNECTED`/`SUCCESS` event; a best-effort `STREAM_DISCONNECTED` event is published on teardown.

- [ ] **Step 1: Write the failing test** — mirror `tests/api/test_telemetry_stream.py`: open a real HTTP stream, assert the first `data:` frame decodes to `workflow=="system"`, `stage=="stream_connected"`, `status=="success"` (this fails today with a 500/AttributeError). Add a second test: publish two events with different `correlation_id`, open the stream with `?correlation_id=<A>`, assert only A's frame arrives.
- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/api/test_workflow_routes.py -v`.
- [ ] **Step 3: Implement** — replace the lowercase enum attributes with `WorkflowType.SYSTEM` / `WorkflowStage.STREAM_CONNECTED` / `WorkflowStatus.SUCCESS`; add the `correlation_id` query param and matching filter branch; publish `STREAM_DISCONNECTED` (fire-and-forget) in the generator's `finally`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "fix(workflow): repair SSE connection event and add correlation filter"`

### Task 5: Server-side ownership + `rag_ingestion` filtering on `/events/recent`

**Files:**
- Modify: `backend/app/repositories/vehicle_repository.py`, `backend/app/api/routes/workflow.py:70-109`
- Test: `backend/tests/api/test_workflow_routes.py`

**Interfaces:**
- Produces: `VehicleRepository.list_ids_by_owner(owner_user_id: UUID) -> list[UUID]` (unpaginated id-only query).
- Produces: `_visible_events(events, user, owned_ids)` helper in `workflow.py`.

- [ ] **Step 1: Write failing tests** — register two users A and B over real HTTP; A creates vehicle V. Publish one event with `vehicle_id=V`, one with B's vehicle, one `rag_ingestion` with no vehicle. As A: `/events/recent` returns V's event + the global one, never B's; the `rag_ingestion` event is absent. As an admin: all three appear.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** — inject `AsyncSession`; for non-admins compute `owned = set(await VehicleRepository(session).list_ids_by_owner(user.id))` once, then keep an event only if `(event.vehicle_id is None or event.vehicle_id in owned) and event.workflow != WorkflowType.RAG_INGESTION`. Admins skip filtering. Filtering happens before pagination.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow): ownership + admin-only filtering for recent events"`

### Task 6: Ownership filtering on `/events/stream`

**Files:**
- Modify: `backend/app/api/routes/workflow.py:128-199`
- Test: `backend/tests/api/test_workflow_routes.py`

**Interfaces:**
- Consumes: `_visible_events` / `list_ids_by_owner` from Task 5.

- [ ] **Step 1: Write the failing test** — open A's stream; publish A's vehicle event (arrives), B's vehicle event (does not), and a `rag_ingestion` event (does not). Assert with a bounded `asyncio.wait_for` read (never hang).
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** — resolve the owned-id set once at stream start (route is `async`, session available via `Depends(get_db)`); drop non-visible frames inside the loop before yielding.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow): ownership filtering for the SSE stream"`

---

## Phase 3 — Backend instrumentation

### Task 7: Subscriber lifecycle events

**Files:**
- Modify: `backend/app/services/subscriber_manager.py:147-189`
- Test: `backend/tests/services/test_subscriber_manager.py`

**Interfaces:**
- Produces: on successful `_spawn_locked` → `publish_workflow_event(SYSTEM, SUBSCRIBER_STARTED, SUCCESS, vehicle_id=None)`; on unexpected exit in `_supervise` → `SUBSCRIBER_ERROR, ERROR`; on `shutdown`/intentional stop → `SUBSCRIBER_STOPPED, SUCCESS`. Idempotent lifecycle only — never block supervision.

- [ ] **Step 1: Write failing tests** — with the fake `ProcessRunner`, `ensure_running()` emits exactly one `SUBSCRIBER_STARTED`; a simulated unexpected exit emits `SUBSCRIBER_ERROR`; `shutdown()` emits `SUBSCRIBER_STOPPED`.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** the three `publish_workflow_event` calls; no event on `ensure_running` when already alive; auto-restart backoff/counting unchanged.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow): subscriber lifecycle events"`

### Task 8: Ingestion `document_id` on all events + `correlation_id` in the upload response

**Files:**
- Modify: `backend/app/rag/ingestion.py:49-65,128,150-451`, `backend/app/schemas/rag.py:63-83`, `backend/app/rag/admin_documents.py:264-281`
- Test: `backend/tests/rag/test_ingestion_workflow.py` (new)

**Interfaces:**
- Produces: `IngestionReport.correlation_id: str | None = None`; every ingestion event after the document row resolves carries `document_id`; `AdminRagUploadResponse.correlation_id: str | None = None`.
- Consumes: existing `correlation_id = f"ingest-{canonical_source}-{int(time.time())}"` (keep it; set it on the report).

- [ ] **Step 1: Write failing tests** — ingest a small text fixture with a captured bus; assert: the `document_id` is present on every event emitted after `DOCUMENT_RECEIVED`; `report.correlation_id` equals the events' `correlation_id`; the response model exposes it.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** — set `report.correlation_id` once, pass `document_id=doc_id` to every subsequent emit (they currently omit it), and map `report.correlation_id` in `_to_upload_response`. No parsing/chunking/embedding changes.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(rag): correlate ingestion events and expose correlation id"`

### Task 9: Instrument the RAG query page path (`search_evidence`) and add `RAG_QUERY_ERROR`

**Files:**
- Modify: `backend/app/rag/rag_service.py:365-455`, `backend/app/rag/schemas.py:70-78`
- Test: `backend/tests/rag/test_rag_query_workflow.py` (new)

**Interfaces:**
- Produces: `RAGSearchResult.correlation_id: str | None = None`.
- Produces: `RAGService._retrieve(..., correlation_id: str | None = None)` emits `QUERY_EMBEDDING_STARTED/COMPLETED`, `VECTOR_SEARCH_STARTED/COMPLETED`, `CANDIDATES_RETRIEVED`, and (when a reranker is used) `RERANKING_STARTED/COMPLETED`, all under one id. `search_evidence()` emits `QUERY_RECEIVED` first, `CONTEXT_ASSEMBLED` + `RAG_QUERY_COMPLETED` last, and `RAG_QUERY_ERROR` (then re-raises) on failure.

> Rationale (do not "fix"): the RAG Query page calls `GET /rag/search` → `search_evidence()`, which currently emits **no** events; `search()` (used by the agent tool) already emits its own and is left untouched.

- [ ] **Step 1: Write failing tests** — call `search_evidence` with a stub connection and captured bus; assert the ordered stages above and that `result.correlation_id` matches; a raised exception emits `RAG_QUERY_ERROR` and propagates.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** with `correlation_id = new_correlation_id("rag-query")`; emit-only (no ranking/scoring changes). Pass `correlation_id` into `_retrieve`; leave `search()` as-is.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(rag): instrument the RAG query pipeline"`

### Task 10: Agent error coverage + `correlation_id` in the response

**Files:**
- Modify: `backend/app/agent/nodes.py`, `backend/app/agent/service.py:176-206`, `backend/app/agent/schemas.py:145-157`
- Test: `backend/tests/agent/test_agent_workflow.py` (new)

**Interfaces:**
- Produces: `DiagnosisResponse.correlation_id: str | None = None`, populated from the run's `agent_run_id`.
- Produces: `AGENT_ERROR` emitted (then re-raised) when the graph/LLM/persist fails, not only for missing reasoning.

- [ ] **Step 1: Write failing tests** — (a) `_run` returns a response whose `correlation_id` equals the `agent_run_id` used in emitted events; (b) an LLM/graph failure emits `AGENT_ERROR` and propagates.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** — add the optional field; in `_run` do `response.model_copy(update={"correlation_id": state["agent_run_id"]})`; wrap the failing node/`_run` boundary with `try/except` that publishes `AGENT_ERROR` and re-raises. No reasoning/fallback changes.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(agent): error event coverage and correlation id"`

---

## Phase 4 — Derived telemetry state endpoint

### Task 11: `telemetry_pipeline_state` service

**Files:**
- Create: `backend/app/services/telemetry_pipeline_state.py`
- Test: `backend/tests/services/test_telemetry_pipeline_state.py` (new)

**Interfaces:**
- Produces: `async def build_vehicle_state(session, manager, subscriber, *, vehicle_id, now=None) -> VehicleTelemetryState`.
- Reuses: `TelemetryStatus`/staleness constants from `api/routes/simulation.py` (`_STALE_AFTER_SECONDS=30`, `_STARTUP_BUFFER_SECONDS=25`) — **import the constants, do not redefine or change them**.

**Per-stage rules (real signals only):**
| Stage | Emit when | Status |
|---|---|---|
| `simulator` | lifecycle `starting`/`running` | `STARTED`/`SUCCESS`; `DEGRADED` if manager error → else omit |
| `mqtt_publish` | simulator running | `SUCCESS` if telemetry fresh else `DEGRADED`; omit if not running |
| `mqtt_broker` | always when any flow datapoint exists | `SUCCESS` if telemetry fresh, `DEGRADED` if subscriber alive but stale, **omit** if subscriber stopped |
| `mqtt_subscriber` | subscriber health known | `SUCCESS` if running else `ERROR` |
| `parser` | rows exist | `SUCCESS`, `detail="Receiving valid telemetry"` (derived flow) |
| `postgres` | rows exist | `SUCCESS` if fresh else `DEGRADED` |
| `health_engine` | monitor enabled | `SUCCESS` if recent snapshot else `RUNNING`; omit if disabled |
| `health_snapshot` | snapshot exists | `SUCCESS` if fresh else `DEGRADED` |

All stages: `observation="derived"`, `at` from the real timestamp used, `detail` truthful. **Never** emit `WAITING`; omit stages with no signal.

- [ ] **Step 1: Write failing tests** covering the matrix: (a) running+fresh → `broker=SUCCESS`, `parser=SUCCESS` with flow wording; (b) running+stale+subscriber alive → `broker=DEGRADED` with "no recent telemetry flow" detail; (c) subscriber stopped → `mqtt_subscriber=ERROR`, `broker` **omitted** (not `ERROR`); (d) 0 samples → `parser`/`postgres` omitted; (e) no `WorkflowStatus.WAITING` anywhere.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** using `SimulationManager.statuses_for`, `SubscriberSupervisor.health()`, `TelemetryRepository.get_latest_timestamps`/`count`-style reads, and the latest health snapshot lookup. Keep it read-only.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow): derive telemetry pipeline state from real signals"`

### Task 12: `GET /workflow/state` route

**Files:**
- Modify: `backend/app/api/routes/workflow.py` (add route near `/status`)
- Test: `backend/tests/api/test_workflow_routes.py`

**Interfaces:**
- Consumes: `build_vehicle_state`; `VehicleService.list_vehicles_for_user`.
- Produces: `GET /workflow/state?vehicle_id=<uuid>` → `WorkflowStateResponse`; with `vehicle_id`, filter to it (empty if not owned); without, one item per accessible vehicle. Non-admins never see other users' vehicles.

- [ ] **Step 1: Write failing tests** — owned vehicle returns one item with derived stages; another user's `vehicle_id` returns an empty `items` list (not a leaky 404 body); admin lists all.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** the route; reuse `ensure_vehicle_access` semantics for the single-vehicle case.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow): read-only derived telemetry state endpoint"`

---

## Phase 5 — Frontend stream and types

### Task 13: Frontend types + API client + proxy forwarding

**Files:**
- Modify: `frontend/src/types/api.ts`, `frontend/src/services/workflow.ts`, `frontend/src/app/api/workflow/events/stream/route.ts`
- Test: `frontend/src/services/__tests__/workflow.test.ts` (new)

**Interfaces:**
- Produces (types): `WorkflowStatus` adds `"degraded" | "skipped"`; `WorkflowStage` adds `"stream_connected" | "stream_disconnected"`; new `TelemetryStage`, `StageState`, `VehicleTelemetryState`, `WorkflowStateResponse`; `RAGSearchResult`, `AdminRagUploadResponse`, `DiagnosisResponse` each add `correlation_id?: string | null`.
- Produces (client): `workflowApi.getState(params?: { vehicle_id?: string }) => Promise<WorkflowStateResponse>` hitting `/workflow/state`; `createWorkflowEventSource` accepts `correlation_id`.
- Proxy: forwards `correlation_id`.

- [ ] **Step 1: Write failing test** — `workflowApi.getState({ vehicle_id: "v1" })` calls `api.get("/workflow/state", { query: { vehicle_id: "v1" }})`.
- [ ] **Step 2: Run to verify fail** — `npm test -- workflow`.
- [ ] **Step 3: Implement** types, client method, `correlation_id` in `createWorkflowEventSource`, and add `correlation_id` to the proxy's whitelist (`route.ts:14-28`).
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow-ui): types, state client, and proxy correlation forwarding"`

### Task 14: `WorkflowStreamProvider` (one SSE, reconnect ladder, scoped selectors)

**Files:**
- Create: `frontend/src/components/workflow/workflow-stream-provider.tsx`
- Modify: `frontend/src/components/layout/app-shell.tsx` (wrap `{children}` inside the authenticated shell), `frontend/src/app/(app)/layout.tsx` if needed
- Test: `frontend/src/components/workflow/__tests__/workflow-stream-provider.test.tsx` (new)

**Interfaces:**
- Produces: `WorkflowStreamProvider({ children, eventSourceFactory? })`; `useWorkflowConnection(): "connecting" | "live" | "reconnecting" | "disconnected"`; `useWorkflowSlice(scope?: { workflow?; vehicleId?; documentId?; correlationId?; since? }): { events: WorkflowEventResponse[] }`.
- Behavior: exactly one `EventSource`; reconnect ladder `[1000,2500,5000,10000,15000]` (reuse `DEFAULT_RECONNECT_DELAYS` from `use-telemetry-stream`); clears timers on unmount; bounded buffer 500; dedup by `event_id`; pause/resume tears down/re-arms the single source; scope filtering happens in the consumer (so unrelated events don't re-render a scoped consumer).

- [ ] **Step 1: Write failing tests** (inject `FakeEventSource`, mirror `use-telemetry-stream.test.tsx`): (a) mounts exactly one `EventSource`; (b) two consumers do not create a second; (c) a dropped connection schedules one reconnect and status transitions `connecting→live→reconnecting→live`; (d) unmount closes the source and cancels the timer; (e) `useWorkflowSlice({ vehicleId })` returns only matching events.
- [ ] **Step 2: Run to verify fail** — `npm test -- workflow-stream-provider`.
- [ ] **Step 3: Implement** the provider + context + selectors. `useWorkflowSlice` must select with a memoized comparator so a consumer scoped to one vehicle does not re-render on unrelated events.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow-ui): shared workflow stream provider with scoped selectors"`

---

## Phase 6 — Reusable contextual components

### Task 15: Status meta + `WorkflowStatusBadge`

**Files:**
- Create: `frontend/src/components/workflow/status.tsx`
- Test: `frontend/src/components/workflow/__tests__/status.test.tsx` (new)

**Interfaces:**
- Produces: `type StageStatus = WorkflowStatus | "waiting"`; `WORKFLOW_STATUS_META: Record<StageStatus, { label; icon; tone; aria }>`; `WorkflowStatusBadge({ status }: { status: StageStatus })`.
- Requirement: not colour-only — every badge shows an icon **and** text; `aria-label` equals `"{label}"`.

- [ ] **Step 1: Write failing tests** — every key including `"waiting"` renders its label and an accessible name; `degraded` renders "Degraded"; `skipped` renders "Skipped".
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** using the existing `Badge` tones; `waiting` uses a neutral tone.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow-ui): status badges with accessible, non-colour cues"`

### Task 16: `WorkflowPipeline` + `WorkflowPipelineStep` + connection indicator

**Files:**
- Create: `frontend/src/components/workflow/pipeline.tsx`
- Test: `frontend/src/components/workflow/__tests__/pipeline.test.tsx` (new)

**Interfaces:**
- Produces: `WorkflowPipelineStep({ label, status, detail?, lastEvent?, icon? })`; `WorkflowPipeline({ title?, steps: ReactNode[]; orientation?: "horizontal"|"vertical" })`; `WorkflowConnectionIndicator({ status })`.
- Focus behaviour: horizontal on wide, vertical on narrow (CSS only); each step has `role="listitem"` inside a `role="list"`.

- [ ] **Step 1: Write failing tests** — renders N steps; a `waiting` step is present when passed; orientation class swaps at the responsive breakpoint class; connection indicator renders text for each connection state.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** the three components with the existing primitives.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow-ui): reusable pipeline components"`

### Task 17: `PIPELINES` registry + `deriveStageStates`

**Files:**
- Create: `frontend/src/components/workflow/pipelines.ts`
- Test: `frontend/src/components/workflow/__tests__/pipelines.test.ts` (new)

**Interfaces:**
- Produces: `PIPELINES: Record<PipelineId, { title: string; stages: StageDef[] }>` for `telemetry | rag_ingestion | rag_query | health | agent`; `StageState`-aware `deriveStageStates(events: WorkflowEventResponse[], stages: StageDef[], scope): { stage: string; status: StageStatus; lastEvent: WorkflowEventResponse | null; detail?: string }[]`.
- Rule: an event-derived stage with no matching event is `"waiting"`; a derived `/workflow/state` stage overrides the matching node; parser/broker stage labels use honest wording ("Receiving valid telemetry", "Flow observed").

- [ ] **Step 1: Write failing tests** — (a) empty events → all stages `waiting`; (b) a `TELEMETRY_PERSISTED` success event marks its mapped stage `success`; (c) a derived `DEGRADED` broker state renders `degraded` with the flow detail; (d) the parser stage label text never contains "processed".
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow-ui): pipeline registry and stage derivation"`

### Task 18: Contextual wrapper + refactor the five pipeline panels

**Files:**
- Create: `frontend/src/components/workflow/contextual-pipeline.tsx`
- Modify: `frontend/src/components/workflow/pipeline-telemetry.tsx`, `pipeline-rag-query.tsx`, `pipeline-rag-ingestion.tsx`, `pipeline-health.tsx`, `pipeline-agent.tsx`, `workflow-view.tsx`
- Test: `frontend/src/components/workflow/__tests__/contextual-pipeline.test.tsx` (new)

**Interfaces:**
- Produces: `ContextualPipeline({ id, vehicleId?, documentId?, correlationId?, derivedState? })` — reads `useWorkflowSlice(scope)` + `useWorkflowConnection()`, renders `WorkflowPipeline` via the registry, and (telemetry only) overlays `derivedState` stages.
- The five panels become thin presentational wrappers over `WorkflowPipeline`; each keeps its existing export name and prop signature so `workflow-view.tsx` is unaffected.

- [ ] **Step 1: Write failing tests** — `ContextualPipeline` renders the registry stages and updates when a matching event is pushed; an out-of-scope event does not change it.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** the wrapper; delete the duplicated `PipelineNode`/`getNodeStatus`/`formatRelative`/status maps from the five panels and delegate to the shared components. Keep `workflow-view.tsx` behaviour identical.
- [ ] **Step 4: Run to verify pass** + run the full frontend suite.
- [ ] **Step 5: Commit** — `git commit -m "refactor(workflow-ui): single reusable pipeline, remove 5x duplication"`

---

## Phase 7 — Contextual page integration

> Each task mounts `<ContextualPipeline id=... />` at the location the exploration identified, scoped to the page's entity. Every task includes a test that proves the pipeline is hidden before an operation and appears/updates only from real events.

### Task 19: Simulation Control — telemetry pipeline (per vehicle)

**Files:**
- Modify: `frontend/src/components/simulations/simulations-view.tsx` (mount inside `SimulationCard`, or once under `<PageHeader>` scoped by the card's vehicle), `frontend/src/components/workflow/contextual-pipeline.tsx` (telemetry overlay)
- Test: `frontend/src/components/simulations/__tests__/simulations-view.test.tsx`

**Interfaces:**
- Consumes: `useWorkflowSlice({ vehicleId })`, `workflowApi.getState({ vehicle_id })` (initial/derived state), `WorkflowConnectionIndicator`.
- Scope key: `vehicle_id`. Auto-expand the card pipeline on Start/Restart; collapsed until active.

- [ ] **Step 1: Write failing tests** — before start: no running pipeline (a "Ready" afforance only); after a `SIMULATION_STARTED` event for V: pipeline visible; a `DEGRADED` broker derived state shows degraded; per-vehicle isolation (two cards).
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** the mount + derived-state fetch. Do not alter start/stop/restart wiring.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(simulations): contextual telemetry pipeline"`

### Task 20: Vehicle Health — health pipeline

**Files:**
- Modify: `frontend/src/components/vehicles/vehicle-health-view.tsx`
- Test: `frontend/src/components/vehicles/__tests__/vehicle-health-view.test.tsx`

**Interfaces:**
- Consumes: `useWorkflowSlice({ workflow: "health", vehicleId })`.
- Scope key: `vehicle_id`.

- [ ] **Step 1: Write failing tests** — no events → waiting stages; a `HEALTH_SCORE_CALCULATED` event updates the score stage; the existing score/confidence/provisional rendering is unchanged.
- [ ] **Step 2–4:** fail → implement (mount after `HealthSummaryPanel`) → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(health): contextual health pipeline"`

### Task 21: AI Diagnosis — agent pipeline

**Files:**
- Modify: `frontend/src/components/vehicles/vehicle-diagnosis-view.tsx` (wrap the existing `<DiagnosisPanel/>` in a fragment/container)
- Test: `frontend/src/components/vehicles/__tests__/vehicle-diagnosis-view.test.tsx`

**Interfaces:**
- Consumes: `useWorkflowSlice({ workflow: "agent", vehicleId, correlationId: latestRunId ?? undefined })`; the run id comes from the latest `DiagnosisResponse.correlation_id`.
- Scope key: `vehicle_id` (+ run id when available). High-level stages only — never CoT/prompts/secrets.

- [ ] **Step 1: Write failing tests** — asking the agent shows the pipeline; a `REASONING_STARTED`/`AGENT_COMPLETED` pair updates stages; the `AGENT_ERROR` state renders an error; the diagnosis panel still renders.
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(diagnosis): contextual agent pipeline"`

### Task 22: RAG Query — retrieval pipeline

**Files:**
- Modify: `frontend/src/components/rag/rag-search-view.tsx`
- Test: `frontend/src/components/rag/__tests__/rag-search-view.test.tsx`

**Interfaces:**
- Consumes: `useWorkflowSlice({ workflow: "rag_query", correlationId: result?.correlation_id ?? undefined })`.
- Scope key: operation `correlation_id` (fallback: recent window).

- [ ] **Step 1: Write failing tests** — a search shows the retrieval pipeline; the returned `correlation_id` scopes it (`QUERY_EMBEDDING_*`/`VECTOR_SEARCH_*` update stages); results remain visible; an empty result still shows real stages.
- [ ] **Step 2–4:** fail → implement (mount after the search card) → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(rag): contextual retrieval pipeline"`

### Task 23: Admin RAG — ingestion pipeline (per document)

**Files:**
- Modify: `frontend/src/components/admin/admin-rag-view.tsx`
- Test: `frontend/src/components/admin/__tests__/admin-rag-view.test.tsx`

**Interfaces:**
- Consumes: `useWorkflowSlice({ workflow: "rag_ingestion", documentId: upload?.id ?? undefined, correlationId: upload?.correlation_id ?? undefined })` (`UploadOutcome` gains `correlation_id`).
- Scope key: `document_id` (+ ingestion correlation).

- [ ] **Step 1: Write failing tests** — before upload: no active pipeline; after upload: `DOCUMENT_*`/`EMBEDDING_*`/`INDEX_READY` update stages; two sequential uploads are isolated; an `INGESTION_ERROR` renders an error.
- [ ] **Step 2–4:** fail → implement (mount after `AdminRagDocuments`) → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(admin-rag): contextual ingestion pipeline"`

---

## Phase 8 — Workflow Monitor, test maintenance, docs

### Task 24: Wire the Monitor filter bar, controls, and add Simulation/System tabs

**Files:**
- Modify: `frontend/src/components/workflow/workflow-view.tsx:18-121`, `frontend/src/components/workflow/filters.tsx`
- Test: `frontend/src/components/workflow/__tests__/workflow-view.test.tsx` (new)

**Interfaces:**
- Extends `Tab = ... | "simulation" | "system"`.
- `Filters.onFilterChange` now sets real filters; pause/resume/clear/export operate on the shared stream; add a `correlation_id` filter input.

- [ ] **Step 1: Write failing tests** — changing a workflow filter narrows `filteredEvents`; pause stops updates; clear empties; the new tabs render; a correlation id filters the timeline.
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow-ui): functional monitor filters, controls, and tabs"`

### Task 25: Fix the stale health-monitor default test

**Files:**
- Modify: `backend/tests/core/test_config.py:26-37`
- Test: the same test

**Interfaces:**
- The implementation default is already `health_monitor_interval_seconds = 10.0` (`backend/app/core/config.py:52`). Update only the expectation.

- [ ] **Step 1: Change the assertion** `settings.health_monitor_interval_seconds == 30.0` → `== 10.0`. Do **not** touch `app/core/config.py` or any health-engine logic.
- [ ] **Step 2: Run** — `python -m pytest tests/core/test_config.py::test_health_monitor_defaults -v` → PASS.
- [ ] **Step 3: Run the backend suite** — `python -m pytest` → no knowingly-stale failure.
- [ ] **Step 4: Run ruff** — `python -m ruff check .` and `python -m ruff format --check .`.
- [ ] **Step 5: Commit** — `git commit -m "test(config): align health-monitor default expectation with 10s"`

### Task 26: Documentation + final verification

**Files:**
- Modify: repo docs describing the Workflow Monitor / observability (e.g. the existing architecture/README sections); update `tasks/todo.md` checkboxes only if accurate.
- Test: full suites.

- [ ] **Step 1: Document** the hybrid model, the 7 statuses (+ frontend `WAITING`), the derived-state endpoint, ownership filtering, and the honest parser/broker wording.
- [ ] **Step 2: Backend verification** — `python -m pytest`; `python -m ruff check .`; `python -m ruff format --check .`.
- [ ] **Step 3: Frontend verification** — `npm test`; `npm run typecheck`; `npm run lint`.
- [ ] **Step 4: Live smoke (best effort, report honestly)** — start Mosquitto + API + Next; run a simulation and watch the Simulation Control pipeline; stop the subscriber and confirm `DEGRADED`; upload a document; run a RAG query; ask the agent; confirm the Monitor sees the same events. Record exactly what ran and what did not.
- [ ] **Step 5: Commit** — `git commit -m "docs: contextual workflow observability"`

---

## Self-Review

**Spec coverage:**
- §3 hybrid architecture → Tasks 4, 7, 11; no per-message bridge / no LISTEN-NOTIFY anywhere.
- §4 vocabulary (`DEGRADED`/`SKIPPED`, `WAITING` frontend-only) → Tasks 1, 17; no backend `WAITING` (Task 11 asserts).
- §5 contract + `TelemetryStage`/`StageState` → Task 3.
- §6.1 SSE fix + correlation filter → Task 4; §6.2 subscriber lifecycle → Task 7; §6.3 ingestion `document_id` → Task 8; §6.4 `RAG_QUERY_ERROR`/`AGENT_ERROR` → Tasks 9/10; §6.5 correlation helper → Task 2; §6.6 response ids → Tasks 8/9/10/13; §6.7 `/workflow/state` → Tasks 11/12.
- §7 parser/broker honesty → Tasks 11, 17.
- §8 server-side ownership → Tasks 5, 6, 12.
- §9 single stream + components → Tasks 14–18.
- §9.4 initial/historical state → Task 19 (derived fetch) + Task 18 (`Correlation`/window scope).
- §10 per-page → Tasks 19–23; rail deferred (recorded in spec §16).
- §11 no-fake guarantees → Tasks 11/17 (assert absence of `WAITING`), 15/16 (status vocabulary), 18/19 (isolation).
- §12.2 health test → Task 25.
- §13 risks → reflected in Global Constraints and Task 26 live-smoke honesty.

**Step scan:** every step names an action and a checkable result (a test that fails then passes, or a command with expected output). No "handle edge cases"/"TBD" lines. Bodies are omitted except where the algorithm is not determined by the signature/test (Tasks 11, 14, 17 include the rule tables/behaviour).

**Type consistency:** `new_correlation_id` (Tasks 2, 9) is defined once. `StageStatus`, `StageDef`, `TelemetryStage`, `StageState`, `VehicleTelemetryState`, `WorkflowStateResponse`, `deriveStageStates`, `useWorkflowSlice`, `ContextualPipeline` are each defined before first use and referenced with the same names. `WorkflowStatus` extension is consistent across backend (Task 1) and frontend (Task 13).

**Review Focus:** (1) simulator-degraded-with-dead-subscriber → Task 11/19 tests; (2) cross-user leak → Tasks 5/6/12 tests; (3) subscriber-alive-no-flow → Tasks 11/17; (4) reconnect with correlation scope + leak-free EventSource → Task 14; (5) unknown stage → `WAITING`, never persisted → Tasks 11/17/18.
