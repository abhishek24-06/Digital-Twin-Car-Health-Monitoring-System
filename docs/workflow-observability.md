# Workflow Observability — context & architecture

This document describes the live workflow observability model implemented for the
Digital Twin platform: the backend event model, the hybrid derivation of
high-frequency telemetry state, the server-side ownership rules, and the
frontend rendering conventions. It supersedes any ad-hoc notes in older plans.

## 1. Hybrid architecture (what is bridged, what is derived)

The observability layer is deliberately **hybrid**:

- **Bridged lifecycle events** — low-frequency, meaningful transitions are
  published onto a bounded, process-local event bus:
  - simulation start/stop/restart (one correlation id shared by the route and
    the manager),
  - RAG document ingestion phases and outcomes (each post-resolution event
    carries `document_id`; the upload response carries `correlation_id`),
  - RAG query phases (one `correlation_id` per `search_evidence()` call),
  - agent runs (the `AGENT_ERROR` boundary is published exactly once at the
    `AgentService._run` boundary),
  - health pipeline lifecycle stages,
  - subscriber lifecycle (`SUBSCRIBER_STARTED`, `SUBSCRIBER_STOPPED`,
    `SUBSCRIBER_ERROR`).
- **Derived telemetry flow** — the high-frequency per-message work inside the
  subscriber subprocess (parse/validate each message) is **never** bridged onto
  the bus. Instead `GET /workflow/state` derives each vehicle's pipeline stages
  from **real** process and database signals (subscriber process alive, recent
  persisted rows). There is no per-message telemetry bridge, no `LISTEN/NOTIFY`,
  and no second event system.

The bus is bounded (500 events) and process-local (max 50 SSE subscribers).
There is no workflow database table or migration; derived state is recomputed
from existing state.

## 2. Status vocabulary

The persisted backend vocabulary is exactly:

`started | running | success | warning | degraded | error | skipped`

`WAITING` is **frontend-only** and is never persisted or emitted. A stage with
no signal is either omitted from derived state or rendered as `WAITING` by the
UI.

Every derived/rendered stage carries explicit provenance:

- `observed` — from a real bus event,
- `derived` — from `/workflow/state` (real process/DB signals),
- `none-yet` — waiting, no signal.

Derived state is never presented as observed.

## 3. Honest wording

- A derived parser stage means “a confirmed healthy telemetry flow is
  observed”, never “this exact message was parsed”. Labels avoid the word
  “processed”.
- The broker stage is derived from observed flow; a degraded broker renders the
  derived detail (e.g. “No recent telemetry flow observed”).
- A stopped subscriber is reported as `SUBSCRIBER_STOPPED`; it does **not**
  automatically classify Mosquitto as `ERROR`.

## 4. Ownership & visibility

- Non-admins only ever see events for vehicles they own, enforced **server
  side** (never by frontend filtering).
- `rag_ingestion` events are hidden from non-admins entirely, even though the
  pipeline stages render inside the admin console.
- SSE resolves visible vehicle ids through a short-lived session.

## 5. Endpoints

- `GET /api/v1/workflow/events/recent` — paginated, newest first.
- `GET /api/v1/workflow/events/stream` — SSE with heartbeat/reconnect; server
  side visibility filtering.
- `GET /api/v1/workflow/status` — high-level system status.
- `GET /api/v1/workflow/state` — read-only derived telemetry pipeline state per
  vehicle (`TelemetryStage`/`StageState`/`VehicleTelemetryState`), with the
  `observation` field.

## 6. Frontend conventions

- One shared `EventSource` (`WorkflowStreamProvider`) feeds an external store;
  `useWorkflowSlice(scope)` caches per-scope slices so a scoped consumer does
  not re-render on unrelated events. Connection states:
  `connecting | live | reconnecting | disconnected`; pause/resume/clear are
  view-local in the Monitor and never break the shared stream.
- `ContextualPipeline` renders a registry-defined pipeline for a feature page,
  scoped by `vehicle_id`, `document_id` and `correlation_id`, and (telemetry
  only) overlays derived state from `/workflow/state`. Pipelines are hidden
  until a real signal exists; pages never show fabricated progress.
- Status badges always render icon + text with an accessible name — meaning is
  never carried by colour alone.
- Per-page mounts: Simulation Control (telemetry pipeline per vehicle), Vehicle
  Health (health pipeline), AI Diagnosis (agent pipeline scoped by run
  `correlation_id`), RAG Query (retrieval pipeline scoped by result
  `correlation_id`), Admin RAG (ingestion pipeline scoped by `document_id` +
  `correlation_id`). `/workflow` remains the global Monitor with
  overview/telemetry/rag-ingestion/rag-query/health/agent/simulation/system
  tabs and functional filters (workflow, status, vehicle, document,
  correlation id).