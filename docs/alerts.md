# Persistent alerts

This document is the contract for the vehicle alert subsystem (Phase 3). It
covers what an alert is, how it is produced, its lifecycle, deduplication, the
audit trail, and the API. The Alerts tab (see “UI” below) consumes it.

## What an alert is

Findings inside a `vehicle_health_snapshots` row (`context_json.findings`) are
**immutable evidence**: they are never edited. An **alert** is the mutable,
human-manageable counterpart:

- an alert is created from one **current-session** finding,
- it is deduplicated while active,
- it is acknowledged and resolved by a user (or auto-resolved when the condition
  clears),
- every transition is recorded permanently in `alert_events`.

Alerts are **not** produced by historical (windowed) analyses. They always
represent the vehicle's current session, mirroring the live-vs-historical split.

## What becomes an alert

A finding is **alert-worthy** iff:

- `severity ∈ {warning, critical}`, and
- it is not a data-quality / meta rule (`TELEMETRY_GAP`, `LOW_DATA_COVERAGE`,
  `INSUFFICIENT_DATA`, `LIMITED_DATA`, `LIVE_DATA_SUFFICIENCY`).

So "not enough data" notices never become alerts; only actionable telemetry
evidence does.

## Lifecycle

```
            ┌───────────── acknowledge ─────────────┐
            ▼                                       │
   open ─────────────────────────────────▶ acknowledged
     │                                            │
     └──────────── resolve ───────────────────────▶ resolved (terminal)
```

- `open` — created from a current-session finding; not yet seen by a user.
- `acknowledged` — a user has seen it and is working on it
  (`acknowledged_at` / `acknowledged_by` / `acknowledge_note`).
- `resolved` — the condition is considered closed
  (`resolved_at` / `resolved_by` / `resolution_note`). Terminal.

Acknowledge and resolve are **idempotent**. Acknowledging a `resolved` alert is a
`409 Conflict`. `resolved` is never reopened in place: a recurrence creates a
**new** alert so the resolved record and its history survive.

## Deduplication

The stable identity of a condition is `dedup_key = "{vehicle_id}:{rule_id}"`.

- A repeated finding **folds into the existing active** (open/acknowledged)
  alert: it updates `last_seen_at`, increments `occurrence_count`, refreshes
  severity/observed value/threshold/evidence, and appends a `recurred` audit row
  (noting any severity change).
- Once an alert is resolved, it is no longer a dedup target, so the next
  occurrence creates a fresh alert.

This yields **at most one active alert per (vehicle, rule)** while preserving the
full history of past occurrences.

## Auto-resolution

The producer is the background health monitor. After each **live** evaluation it
calls `AlertService.sync_from_snapshot()`:

- every alert-worthy finding creates or refreshes its alert;
- any active alert whose rule is **no longer observed** is auto-resolved — but
  **only when the evaluation is definitive (not provisional)**. A provisional
  (insufficient-fresh-data) evaluation is not evidence that a condition cleared,
  so it never auto-resolves or silently closes an alert.

Auto-resolution is attributed to the system (`actor_user_id = null`) and recorded
in the audit trail. An alert-store failure is isolated: it degrades alerts only,
never the snapshot or the monitor pass.

## Audit history (`alert_events`)

Append-only. Each row has `event_type` (`created`, `recurred`, `acknowledged`,
`resolved`), `from_status`/`to_status`, nullable `actor_user_id` (null =
automated) and an optional `note`. History is never rewritten or deleted while
the alert exists.

## API

All routes are under `/api/v1/vehicles/{vehicle_id}/alerts` and require an
authenticated user who can access the vehicle. Cross-vehicle ids and vehicles the
caller does not own both return `404` (existence is never leaked).

| Method & path | Purpose |
|---|---|
| `GET /` | Paginated list. Filters: `status` (repeatable: `open`/`acknowledged`/`resolved`), `severity` (`info`/`warning`/`critical`), `page`, `page_size`. Order: most severe first, newest observation breaking ties. The list view omits raw evidence. |
| `GET /{alert_id}` | One alert including raw `evidence` and the full `events` audit history. |
| `POST /{alert_id}/acknowledge` | `open → acknowledged`. Optional body `{"note": "..."}`. |
| `POST /{alert_id}/resolve` | `open\|acknowledged → resolved`. Optional body `{"note": "..."}`. |

## Data model

- `alerts` — vehicle-scoped (`ON DELETE CASCADE`), with `simulation_run_id` and
  `snapshot_id` recorded as provenance (no FK: the alert outlives run/snapshot
  bookkeeping), `provisional`, `occurrence_count`, `first_seen_at`/`last_seen_at`,
  the acknowledge/resolve fields, and created/updated timestamps.
  `severity`/`status` are pinned by check constraints.
- `alert_events` — FK to `alerts` (`ON DELETE CASCADE`); optional FK to `users`
  (`ON DELETE SET NULL`).

Migration: `e5f6a7b8c9d0_create_alerts` (additive — new tables only).

## UI (Alerts tab)

The eighth vehicle-workspace tab (`/vehicles/{id}/alerts`), delivered in Phase 4.
It is a thin route (`app/(app)/vehicles/[id]/alerts/page.tsx`) over
`components/vehicles/vehicle-alerts-view.tsx`, backed by
`services/alerts.ts` and the `useVehicleAlerts` / `useAlertDetail` /
`useAcknowledgeAlert` / `useResolveAlert` hooks.

- Lists persisted alerts with severity, lifecycle status, occurrence count and a
  `provisional` flag; filters by status and severity; paginates 20 per page.
- Opens a detail dialog with the raw evidence and the append-only audit timeline,
  where an alert can be acknowledged or resolved with an optional note.
- Lifecycle-honest: a `resolved` alert is terminal and shows no action, and
  automated transitions are attributed to “System”.

The tab never invents alerts or states: before the backend is migrated and
restarted it renders its loading/error states, not placeholder data.
