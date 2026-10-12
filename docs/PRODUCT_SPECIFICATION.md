# Digital Twin — Product Specification

Status: approved product decisions captured for the phased implementation.
This document is the agreed scope; the current code is the system of record and
this spec does not override it.

## 1. Product goal

Extend the existing Digital Twin car-health monitoring application so that
current ("live") health is honestly separated from historical analysis, alerts
become persistent first-class records, and the vehicle workspace exposes eight
tabs. Correctness and data isolation ship before new features.

## 2. Approved decisions (authoritative)

1. Correct live-health behavior and live-vs-historical isolation **before**
   adding new features.
2. Implement persistent alerts with acknowledgment, resolution, deduplication,
   and audit history.
3. Preserve existing telemetry, snapshots, and historical reports. Never delete
   historical data to make new behavior look correct.
4. Retain the seven existing vehicle tabs and add an Alerts tab (eight total):
   Overview, Live Health, Simulation, Analytics, Telemetry, AI Diagnosis,
   History, Alerts.
5. Preserve the existing deterministic scoring formulas and thresholds during
   the correctness phase.
6. Do not commit changes unless explicitly requested.

## 3. Concepts and vocabulary

- **Current session / current run** — the telemetry belonging to the active
  simulator run id, spanning only that run.
- **Live Health** — an assessment of the current session that only exists when
  the active run is fresh and clears the sufficiency gate.
- **Historical analysis** — a bounded, explicitly labelled range analysis over
  data that may span several runs and legacy (run-less) rows.
- **Finding** — deterministic evidence emitted by the rule engine inside an
  assessment. A finding is *not* an alert.
- **Alert** — a persistent lifecycle record (Phase 3) that can be
  acknowledged and resolved, distinct from a transient finding.
- **Legacy row** — a telemetry/snapshot row with no run provenance
  (`simulation_run_id IS NULL`). It is never assigned an invented run id.

## 4. Phases (gated)

| Phase | Scope | Gate |
| --- | --- | --- |
| 0 | Baseline inspection + implementation plan | no code change |
| 1 | Correctness + run isolation + window selector | 8 acceptance criteria |
| 2 | Persistence hygiene, workflow observability, security | 5 acceptance criteria |
| 3 | Persistent alerts (model, API, auth, UI) | model/API/UI criteria |
| 4 | Finalize the eight-tab product | per-tab criteria |
| 5 | Full-system acceptance | non-destructive runtime checks |

Each phase stops with a report: what changed, files, migrations, tests executed
with exact results, criteria passed/failed, risks, and the next phase.

## 5. Non-negotiable working rules

- Inspect the working tree (status, branch, uncommitted work) before editing;
  treat uncommitted work as user-owned.
- Use the live OpenAPI schema when available.
- Never expose secrets, tokens, passwords, or connection strings.
- Never reset the database, drop tables, delete telemetry/snapshots, or rewrite
  old reports; never invent simulation run ids for legacy rows.
- Do not change thresholds/formulas to hide a data-isolation defect.
- Do not fabricate alerts, telemetry, or success states.
- Keep backend and frontend types/schemas/contracts aligned.
- Add regression tests with every behavioral change; report real results.
