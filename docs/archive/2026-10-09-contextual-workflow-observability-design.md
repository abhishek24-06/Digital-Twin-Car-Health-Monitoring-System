# Contextual Workflow Observability — Design Specification

- **Date:** 2026-10-09
- **Status:** Draft for review (spec only — no implementation authorized yet)
- **Scope:** Refactor of the existing Workflow Monitor observability into contextual, embedded pipelines, reusing the existing workflow event infrastructure.
- **Repository:** `C:\Users\Abhishek\Desktop\Digital Twin`
- **Baseline:** `main` @ `3c630c2` plus the uncommitted Workflow Monitor feature already present in the working tree.

---

## 1. Context and problem

The application currently exposes a single standalone `Workflow Monitor` page at `/workflow` with tabs (Overview, Telemetry, RAG Ingestion, RAG Query, Health, Agent), filters, live SSE connection state, an in-memory event buffer, uWSGI-independent pipeline panels, and a global event timeline.

This is useful as global observability, but the UX forces the user to leave the feature they are operating and navigate to `/workflow` to see what that feature is doing. The objective is to move the relevant pipeline view **into** the feature page where the operation happens, while keeping `/workflow` as the global system-wide observability/debugging/history view.

Target experience (feature page + its own live workflow):

| Feature page | Contextual pipeline |
|---|---|
| Simulation Control | Live telemetry pipeline (per vehicle) |
| Admin RAG | Live RAG ingestion pipeline (per document) |
| RAG Query / Manufacturer Guidance | Live RAG query pipeline |
| Vehicle Health | Live health analysis pipeline |
| AI Diagnosis | Live agent pipeline |
| Workflow Monitor | Global cross-system observability/debugging/history |

---

## 2. Goals and non-goals

### 2.1 Goals

1. One canonical workflow event source. The same real event feeds both the contextual page and the global Monitor. No second event infrastructure.
2. Reusable, typed, accessible contextual pipeline components replacing the current five copy-pasted pipeline panels.
3. A single shared frontend realtime stream (one SSE connection) with scoped, efficient subscriptions.
4. Real, honest state only. Every displayed stage originates from a real event **or** real process/database state. No fake timers, no fabricated progress.
5. Preserve all existing business logic, schema, and process supervision.

### 2.2 Non-goals / explicitly unchanged

- Health scoring rules, thresholds, baseline calculations.
- RAG ranking algorithm, BGE-M3 embedding configuration, reranker configuration.
- LangGraph reasoning logic and LLM provider fallback logic.
- Authentication and vehicle ownership semantics (only additive authorization on the observability endpoints, see §8).
- MQTT client IDs, MQTT behaviour, process-supervision architecture.
- Database schema: **no new tables, no migrations** for workflow events.
- Multi-worker/multi-process event fan-out (the bus remains process-local, as it is today).

---

## 3. Approved architecture — HYBRID: bridge lifecycle, derive flow

**Low-frequency lifecycle events** are published onto the API-resident workflow event bus (and therefore reach SSE):

- Simulation start/stop/restart (`simulation.*`) — already emitted by the API process (route + manager).
- Subscriber process lifecycle (`subscriber_started` / `subscriber_stopped` / `subscriber_error`) — **newly emitted by the in-process `SubscriberSupervisor`**.
- Health (`health.*`), RAG ingestion (`rag_ingestion.*`), RAG query (`rag_query.*`), and agent (`agent.*`) events — already emitted by in-process code.
- Stream lifecycle (`stream_connected` / `stream_disconnected`).

**High-frequency telemetry flow** is **derived** from real signals the API already holds:

- simulation process state (in-process simulation manager),
- subscriber supervision state (in-process `SubscriberSupervisor.health()`),
- telemetry freshness and counts (PostgreSQL),
- health snapshot freshness (PostgreSQL).

### 3.1 Explicit architectural constraints

- **Do NOT** bridge subscriber-internal per-message telemetry events across processes.
- **Do NOT** use PostgreSQL `LISTEN/NOTIFY`.
- **Do NOT** create a second workflow/event system.
- **Do NOT** create fake timers or fake progress.
- Do not modify the protected business logic listed in §2.2 unless strictly required to emit the approved observability instrumentation.

### 3.2 Why no cross-process bridge is required

The MQTT subscriber (`python -m app.mqtt.subscriber`) and the simulator (`python -m simulator.main`) run as separate OS processes; their `publish_workflow_event(...)` calls land on a **different process-local bus** and never reach the API. The hybrid design therefore:

- emits subscriber **lifecycle** from the supervisor that runs **inside** the API process, and
- **derives** telemetry flow from PostgreSQL/supervision state that the API can read directly.

The existing `publish_workflow_event(...)` calls inside `app/mqtt/subscriber.py` are left **untouched**; they are real but process-local, and this specification does not rely on them.

---

## 4. Workflow status vocabulary (Clarification 1)

### 4.1 Backend event/status vocabulary — authoritative

`WorkflowStatus` (backend enum) contains exactly:

| Value | Meaning |
|---|---|
| `STARTED` | The operation/stage has begun. |
| `RUNNING` | The operation/stage is actively executing. |
| `SUCCESS` | The operation/stage completed successfully. |
| `WARNING` | The operation completed but produced a non-fatal warning. |
| `DEGRADED` | The operation/process is functioning but its data flow or freshness is degraded. |
| `ERROR` | The operation/stage failed. |
| `SKIPPED` | The stage was intentionally not executed. |

This is **additive** to the current backend enum (`STARTED`, `RUNNING`, `SUCCESS`, `WARNING`, `ERROR`): it adds `DEGRADED` and `SKIPPED`. Existing values and their existing emit sites are preserved.

### 4.2 Frontend-only state

`WAITING` **is a frontend-only representation** meaning: *no real event/state has indicated that this stage has started yet.* It is **not** added to the backend `WorkflowStatus` enum and must never be persisted in an event.

`WAITING` must **not** be used to disguise a missing backend signal. If the backend should have produced a signal and did not, the honest representation is `ERROR` or `DEGRADED` (with an explanation), not `WAITING`.

### 4.3 Status vs observation provenance (honesty)

A stage's **status** (`WorkflowStatus`) is separate from its **observation provenance** — how we know it:

- `observed` — the status comes from a real, specific event for that stage/operation.
- `derived` — the status is inferred from real process/database state (see §7).
- none yet — no real signal exists for the stage; the UI renders it as the frontend-only `WAITING` state.

`WAITING` always means "no signal yet", never "assumed success". Backend-derived state never uses `WAITING`: a stage with no signal is **omitted** from the derived response (see §5, §7.2) and the frontend fills it as `WAITING`. The UI wording must accurately describe whether a state was directly observed or derived (see §7.3, §7.4, §10).

---

## 5. Canonical event contract (backend)

`WorkflowEvent` is extended only where noted; all fields remain lightweight and secret-free. `sanitize_metadata()` already redacts secrets/chain-of-thought and is reused unchanged.

**Existing fields (kept):** `event_id`, `timestamp`, `workflow`, `stage`, `status`, `message`, `vehicle_id`, `document_id`, `correlation_id`, `duration_ms`, `metadata`.

**Enums:**
- `WorkflowType`: `telemetry | rag_ingestion | rag_query | health | agent | simulation | system` (unchanged).
- `WorkflowStatus`: see §4.1 (adds `DEGRADED`, `SKIPPED`).
- `WorkflowStage`: existing ~73 stages preserved. Additive SYSTEM stages for stream lifecycle: `STREAM_CONNECTED`, `STREAM_DISCONNECTED`. (The current code's misuse of `SUBSCRIBER_STARTED` for the stream "connected" event is replaced.)

**Derived-state (presentation) stage identity.** Derived telemetry pipeline nodes use a dedicated enum because they represent *inferred* flow, not emitted events:

```
TelemetryStage:
  simulator | mqtt_publish | mqtt_broker | mqtt_subscriber
  | parser | postgres | health_engine | health_snapshot
```

This is a presentation/derivation concept only; it does **not** create a new event type or a second event infrastructure.

**New response models:**

```
StageState:
  stage: TelemetryStage
  status: WorkflowStatus
  observation: "observed" | "derived"
  at: datetime | null
  detail: str | null

VehicleTelemetryState:
  vehicle_id: UUID
  simulation_status: str            # manager lifecycle status
  stages: list[StageState]
  last_telemetry_at: datetime | null
  messages_received: int
  snapshot_at: datetime | null
  degraded_reason: str | null
  updated_at: datetime

WorkflowStateResponse:
  items: list[VehicleTelemetryState]
```

The derived builder emits a `StageState` only for stages that have a real signal (process running, rows present, snapshot present, etc.). Stages with no signal are **omitted**, and the frontend renders them as the frontend-only `WAITING` state. `WorkflowStatus.SKIPPED` is emitted only for stages that were intentionally not executed (with a truthful `detail`), never to hide a missing signal. `observation` is `"derived"` for every stage produced by `/workflow/state` (it is an inference); `"observed"` is reserved for event-based pipelines.

---

## 6. Backend changes

All changes are minimal and preserve existing behavior; the only new persisted concept is inferred telemetry state, which is **not** stored.

### 6.1 Bug fixes (required)

1. **Fix the broken SSE connection event.** `api/routes/workflow.py` currently constructs the first stream event with non-existent lowercase enum attributes (`WorkflowType.system`, `WorkflowStage.subscriber_started`, `WorkflowStatus.success`), which raises `AttributeError` on the generator's first yield. Replace with `WorkflowType.SYSTEM` / `WorkflowStage.STREAM_CONNECTED` / `WorkflowStatus.SUCCESS`.
2. **Add `correlation_id` filtering to the SSE endpoint** (the REST endpoint already supports it) so a contextual pipeline can bind to one operation.
3. **Emit `stream_disconnected`** on stream teardown (best-effort, non-blocking).

### 6.2 Subscriber lifecycle instrumentation (`services/subscriber_manager.py`)

The supervisor is in-process; it publishes (fire-and-forget, never blocking supervision):

- `SUBSCRIBER_STARTED` (workflow `system`, no `vehicle_id` — the subscriber is a single global process) on successful spawn,
- `SUBSCRIBER_ERROR` on unexpected exit during `_supervise`,
- `SUBSCRIBER_STOPPED` on intentional shutdown.

This is the only "bridged lifecycle" for the subscriber. Process supervision semantics, ownership tagging, backoff, and orphan handling are unchanged.

### 6.3 Correct the processed `document_id` on ingestion events (`rag/ingestion.py`)

Today only the terminal `ingestion_completed` events carry `document_id`; intermediate events omit it even after the document/version row exists. Attach `document_id` to every ingestion event from the point the document is resolved, enabling per-document scoping and concurrent-document isolation. No ingestion logic changes.

### 6.4 Error-event instrumentation (emit then re-raise; no behavior change)

- `rag/rag_service.py`: emit `RAG_QUERY_ERROR` when `search()` fails (currently silent).
- `agent/nodes.py`: emit `AGENT_ERROR` on LLM/graph/persist failure (currently only emitted for missing reasoning content).

### 6.5 Correlation-ID standardization

Introduce one helper `new_correlation_id(prefix: str) -> str` and use it consistently. The simulation API route and the simulation manager must share **one** correlation ID for a single operation (today they generate different IDs). Health analysis, RAG ingestion, RAG query, and agent runs carry a single correlation per operation.

### 6.6 Operation identity in responses (additive, optional)

To let the UI bind a pipeline to exactly one execution, the relevant mutation responses expose the operation identifier where it is not already present (additive optional fields): RAG search response → `correlation_id`; admin RAG upload response → ingestion `correlation_id`; agent diagnosis → run id. Health analysis already correlates via vehicle + snapshot. If any field is infeasible, the UI falls back to `vehicle_id`/`document_id` + operation-window scoping (see §10).

### 6.7 Derived telemetry state endpoint

`GET /workflow/state?vehicle_id=<uuid>` (auth required). Returns `WorkflowStateResponse`:

- with `vehicle_id`: the `VehicleTelemetryState` for that vehicle (404/empty if unknown or not owned),
- without `vehicle_id`: `items` for all vehicles visible to the caller (own vehicles; admin sees all).

A new service `services/telemetry_pipeline_state.py` builds the state. It reuses the existing staleness semantics from `api/routes/simulation.py` (`_STALE_AFTER_SECONDS = 30`, `_STARTUP_BUFFER_SECONDS = 25`) and must not introduce new thresholds.

**Minimal API principle:** no `/workflow/operations/{operation_id}` endpoint is added; correlation-ID filtering on `/workflow/events/*` already provides operation retrieval.

---

## 7. Derived telemetry pipeline (Clarifications 2 and 3)

### 7.1 Inputs (all real)

- Simulation lifecycle status (in-process manager).
- Subscriber supervision health (`SubscriberSupervisor.health().running`).
- Telemetry freshness/counts and latest timestamp per vehicle (PostgreSQL).
- Latest health snapshot per vehicle (PostgreSQL).
- Health monitor enabled/running (in-process).

### 7.2 Mapping

| Stage | success | degraded | error / no-signal |
|---|---|---|---|
| `simulator` | lifecycle `starting`/`running` | lifecycle `degraded` | `error`→error; `stopped`→omitted (frontend `WAITING`) |
| `mqtt_publish` | simulator running **and** telemetry fresh | simulator running but stale | omitted (frontend `WAITING`) |
| `mqtt_broker` | telemetry flowing (flow observed) | subscriber alive but no flow | subscriber stopped → omitted, never broker `ERROR` |
| `mqtt_subscriber` | supervisor `running` | running but no telemetry | not running → error |
| `parser` | valid telemetry confirmed (rows exist) | — | omitted (frontend `WAITING`) |
| `postgres` | latest telemetry fresh | rows exist but stale | omitted (frontend `WAITING`) |
| `health_engine` | monitor running **and** recent analysis | monitor disabled → `SKIPPED` (with detail) | omitted (frontend `WAITING`) |
| `health_snapshot` | fresh snapshot | stale snapshot | omitted (frontend `WAITING`) |

**Note on `WAITING` and omission.** Rows marked "omitted" produce **no** `StageState`; the frontend registry renders those stages as the frontend-only `WAITING` state. The backend never emits `WAITING`. `SKIPPED` is used only for a stage deliberately not executed (for example the health engine being disabled), with a truthful `detail` — never to mask a missing signal.

### 7.3 Parser wording must be honest (Clarification 2)

Subscriber-internal high-frequency parser activity is **not individually bridged** into the API event bus. The derived `parser` stage represents **confirmed healthy telemetry flow**, not message-level parser instrumentation.

- The API must **not** claim "Parser successfully processed this exact telemetry message" unless a real parser event exists for that message.
- Permitted UI wording: **"Receiving valid telemetry"** or **"Parser / Validator — flow observed (derived)"**.
- `observation = "derived"` for this stage. Do **not** add a per-message cross-process bridge to make the visualisation appear more granular.

### 7.4 Broker wording must be honest (Clarification 3)

The architecture does **not** directly query Mosquitto for broker health. The pipeline must not claim "Mosquitto connected" or "Mosquitto healthy" absent a real broker health signal.

- Derive the `mqtt_broker` stage from **observed telemetry flow**: actual telemetry successfully published and received demonstrates the MQTT path (through Mosquitto) is working.
- Permitted UI wording: **"MQTT Broker — Telemetry flowing"** or **"MQTT Broker — Flow observed (derived)"**.
- If the subscriber is alive but no telemetry is arriving → `DEGRADED` with a truthful explanation such as: *"Subscriber is running but no recent telemetry flow has been observed."*
- If the subscriber is stopped → do **not** assert `MQTT Broker = error` unless there is direct evidence Mosquitto itself is unavailable. Keep the distinction between **broker/process state** and **observed telemetry flow**.

### 7.5 Freshness / no-data semantics (unchanged)

0 samples → NO DATA; 1+ samples → LIMITED DATA / provisional where applicable; sufficient samples → sufficient data. These existing rules are preserved and only surfaced, never changed.

---

## 8. Authorization (security)

`/workflow/events/*` and `/workflow/state` require authentication (as today). For **non-admin** callers:

- events with a `vehicle_id` that the caller does not own are dropped;
- `rag_ingestion` events (an admin-only capability) are dropped;
- events with no `vehicle_id` and no admin-only workflow are treated as global/system and allowed.

Admins see all events. This prevents leaking another user's vehicle workflow events. The exact non-admin policy is in scope for spec review.

---

## 9. Frontend architecture

### 9.1 Single shared stream

- **`WorkflowStreamProvider`** mounted once in the authenticated layout owns a **single** `EventSource`.
- Reconnect uses the proven backoff ladder already in `use-telemetry-stream.ts` (cleared timers, injectable factory for tests).
- Handles heartbeat, pause/resume, dedup against the recent-events REST endpoint, bounded buffer (≤500), and cleanup on unmount.
- **No** per-page or per-card SSE connections.

### 9.2 Scoped, efficient subscriptions

- A small **workflow stream store** (Zustand, consistent with existing stores) holds the bounded event buffer and connection state.
- **`useWorkflowSlice(scope)`** subscribes to only the events matching `{ workflow?, vehicleId?, documentId?, correlationId?, since? }`, so a page scoped to one vehicle/document does not re-render on unrelated global events.
- **`useWorkflowConnection()`** exposes `connecting | live | reconnecting | disconnected`.

### 9.3 Reusable components (replace 5× duplication)

`components/workflow/`:

- `WorkflowPipeline` — renders a stage list (compact/expanded; horizontal wide / vertical narrow).
- `WorkflowPipelineStep` — one stage: glyph + label + status text + `aria-label` (e.g., "MQTT Subscriber — running").
- `WorkflowStatusBadge` — maps `WorkflowStatus` (+ frontend `waiting`) to the existing `Badge` tones and an icon.
- `WorkflowConnectionIndicator` — small, non-intrusive connection pill.
- `WorkflowMetrics` — real key/value chips only.
- `WorkflowError` — safe error display via existing `InlineAlert`.
- `PIPELINES` registry — the single source of stage lists, shared by contextual pages and the Monitor.
- `deriveStageStates(events, stageDefs, scope)` — shared mapping (replaces the duplicated `getNodeStatus`).
- Status glyphs: `✓ success` · `● running` · `○ waiting` · `⚠ degraded` · `✕ error` · `– skipped`, always with text and a non-colour cue.

Reuse the existing design system (`Badge`, `Card`, `Button`, `InlineAlert`, `EmptyState`, `ErrorState`, `Skeleton`, `Tooltip`). No new UI library.

### 9.4 Initial / historical state

- Before an operation: pipelines show **"Ready — no active operation"** (never a fake running pipeline).
- On reload/return: the pipeline reconstructs current state from `GET /workflow/state` (telemetry) plus recent events and the relevant existing status endpoints, so the user need not have been present when the operation started.

---

## 10. Per-page integration and scoping

| Page | Pipeline | Scope key | Real metrics shown | Notes |
|---|---|---|---|---|
| Simulation Control (per vehicle card, collapsed until active; auto-expand on Start/Restart) | telemetry | `vehicle_id` | last telemetry age, messages received, last observed stage, snapshot age | derived flow + simulation/subscriber lifecycle events |
| Admin RAG | rag_ingestion | `document_id` (+ ingestion correlation) | chunks, embeddings, dimension, duration | concurrent documents isolated |
| RAG Query | rag_query | `vehicle_id` (if scoped) + operation window | candidates, reranked, final evidence, duration | |
| Vehicle Health | health | `vehicle_id` | samples, window, sufficiency, score, confidence, provisional | existing rules preserved |
| AI Diagnosis | agent | `vehicle_id` (+ run id) | high-level stages only | never CoT/prompts/secrets |
| Vehicle workspace | (optional telemetry rail) | `vehicle_id` | — | proposed **deferred** unless requested |
| Workflow Monitor | all tabs | global | unchanged | keep tabs; fix filter bar; wire pause/resume/clear/export; add Simulation + System tabs; correlation filter |

Multiple vehicles remain isolated (each `vehicle_id` renders independently); multiple documents remain isolated (each `document_id` renders independently).

---

## 11. No-fake guarantees

- Every stage state originates from a real event or real process/database state.
- No `setTimeout`/`setInterval` advances a stage or synthesises an event.
- A running simulator with a dead subscriber renders `mqtt_subscriber ✕` and downstream `waiting`, never hollow `success`.
- `derived` vs `observed` provenance is displayed so the UI does not overstate what was directly measured.

---

## 12. Testing plan

### 12.1 Backend

- `/workflow/events/recent`: filtering (workflow/stage/status/vehicle/document/**correlation**/time), pagination, auth, non-admin ownership filtering.
- `/workflow/events/stream`: SSE frames, heartbeat, filters, disconnect/unsubscribe (mirroring the existing telemetry live-server test).
- `/workflow/state`: the derived-state matrix (running / stale / no-subscriber / degraded / no-data), ownership scoping.
- Subscriber lifecycle event emission (`subscriber_manager`).
- `WorkflowStatus` extension (`DEGRADED`, `SKIPPED`) and rejection of invalid values.
- `RAG_QUERY_ERROR` and `AGENT_ERROR` emission (emit-then-raise; no behavior change).
- Ingestion `document_id` attached to all events.
- `sanitize_metadata` unchanged behaviour.

### 12.2 Test maintenance (Clarification 4)

Update `backend/tests/core/test_config.py::test_health_monitor_defaults` to expect the intended **10-second** health-monitor default (currently the stale expectation is `30.0`). This is **test maintenance**, not a health-engine behavior change: the implementation keeps its intended 10-second default. The final backend suite must not knowingly retain the stale 30-second expectation.

### 12.3 Frontend (Vitest)

- `WorkflowStreamProvider`/`useWorkflowSlice`: reconnect/backoff, pause/resume, cleanup, dedup, single connection, scope isolation.
- `WorkflowPipeline`/`WorkflowPipelineStep`/`WorkflowStatusBadge`: all statuses render; accessibility labels; no fake timers.
- Simulation Control: pipeline hidden before start; appears on start; updates from real events; per-vehicle isolation; degraded on stale; error rendering.
- Admin RAG: upload starts pipeline; stage updates; per-document isolation; error rendering.
- RAG Query: pipeline appears; retrieval stages update; results remain visible.
- Health: pipeline appears; score/confidence unchanged; status updates.
- Agent: pipeline appears; stages update; diagnosis remains visible; safe metadata only.
- Workflow Monitor: global events render; existing filters/tabs continue to work.
- Use the existing injectable `FakeEventSource` pattern.

### 12.4 Live checks (subject to environment availability)

Start Mosquitto + API + Next; run one simulation and observe the pipeline; upload a document; run a query; ask the agent; confirm the Monitor sees the same events; then a failure case (stop the subscriber → `degraded`). Report honestly what the environment allowed; do not claim unrun verification.

---

## 13. Risks and limitations

- The event bus remains process-local (single backend worker), exactly as today.
- Per-message telemetry events are intentionally **not** surfaced (hybrid): telemetry is derived + lifecycle events only.
- Live end-to-end checks may be partially gated by broker / database / LLM-key availability.
- Non-admin visibility filtering changes what the Monitor shows to non-admin users (by design, §8).

---

## 14. Files affected (high level)

**Backend:** `app/schemas/workflow.py`, `app/api/routes/workflow.py`, `app/services/subscriber_manager.py`, `app/services/simulation_manager.py`, `app/api/routes/simulation.py`, `app/rag/ingestion.py`, `app/rag/rag_service.py`, `app/agent/nodes.py`, new `app/services/telemetry_pipeline_state.py`, tests. (`app/services/workflow_event_bus.py` is reused **as-is** — bounded buffer 500/50, fire-and-forget publish — with no functional change expected.)

**Frontend:** `hooks/use-workflow.ts` (→ provider/selectors), `services/workflow.ts`, `types/api.ts`, new `components/workflow/*`, `app/(app)/layout.tsx` (provider mount), the five feature page components, `components/workflow/workflow-view.tsx`, navigation, tests, docs.

**Test maintenance:** `tests/core/test_config.py`.

**Not touched:** database schema/migrations; health/RAG/agent business logic (beyond the emit-only instrumentation above).

---

## 15. Acceptance criteria (Definition of Done)

- [ ] Existing Workflow Monitor still works and remains the global observability page.
- [ ] Workflow events have one canonical source; no duplicate infrastructure.
- [ ] Contextual workflow components are reusable.
- [ ] Simulation Control shows its live telemetry pipeline, scoped per vehicle.
- [ ] Admin RAG shows live ingestion pipeline, scoped per document/operation.
- [ ] RAG Query shows the live retrieval pipeline.
- [ ] Health page shows the live health analysis pipeline.
- [ ] Diagnosis page shows the live agent pipeline.
- [ ] No fake progress; no fake events; all states real or honestly derived and labelled.
- [ ] SSE/realtime updates and reconnection work; cleanup works.
- [ ] Correlation IDs work end to end.
- [ ] Multiple vehicles isolated; multiple documents isolated.
- [ ] Stale telemetry represented correctly; subscriber process state distinguished from telemetry health.
- [ ] Broker/parser wording is honest (derived, not overstated).
- [ ] Existing simulation supervision, MQTT behaviour, health logic, RAG logic, agent logic, auth/ownership preserved.
- [ ] Backend tests pass (including the corrected health-monitor default test).
- [ ] Frontend tests pass; TypeScript passes; ESLint passes; Ruff passes.
- [ ] Real MQTT flow, RAG ingestion, RAG query, and agent workflow verified (or explicitly reported as not run, with reason).
- [ ] Documentation updated.

---

## 16. Resolved decisions

1. **Vehicle workspace rail — DEFERRED.** No persistent workflow rail on the vehicle workspace in this implementation. Workflow visualization stays contextual to the relevant pages: Simulation Control (telemetry), Health (health), AI Diagnosis (agent), Admin RAG (ingestion), RAG Query (retrieval). Revisit a persistent rail later as a separate UX enhancement.
2. **Optional operation id in responses — APPROVED.** Add an optional `correlation_id` to RAG/agent responses (and to the ingestion upload response), reusing existing identifiers (`rag-query-*`, `agent_run_id`, ingestion `correlation_id`). Additive and backward-compatible. It lets the frontend bind the initiating mutation to the exact live workflow execution. No internal details, prompts, secrets, or chain-of-thought are exposed.
3. **Non-admin visibility — APPROVED.** Apply filtering **server-side, not merely in the frontend**. Non-admin callers receive workflow events only for vehicles they own, never `rag_ingestion` events, and cannot infer another user's vehicle or private RAG ingestion operation. Admins keep the broader view per the existing authorization model; existing ownership/authentication semantics are preserved.
