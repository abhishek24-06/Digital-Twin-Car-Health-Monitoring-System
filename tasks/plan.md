# Implementation Plan: System Workflow / Live Observability

## Overview
Add a faculty-facing "System Workflow / Observability" feature that exposes the actual execution of the Digital Twin pipelines in real time. The feature will show REAL events emitted by the actual system - telemetry flow (simulator → MQTT → subscriber → PostgreSQL → health engine → snapshot), RAG ingestion (document → parse → chunk → embed → pgvector), RAG query (question → embedding → retrieval → rerank → answer), health intelligence (telemetry → window → rules → baselines → score → confidence → snapshot), and agent workflow (user query → supervisor → tools/context → reasoning → response).

## Architecture Decisions

1. **WorkflowEvent Model** - Pydantic model for internal event representation with fields: event_id, timestamp, workflow, stage, status, message, vehicle_id, document_id, correlation_id, duration_ms, metadata
2. **Bounded In-Memory Event Bus** - Ring buffer (max 500 events) with async-safe publish/subscribe, non-blocking, failure of observability never fails core operations
3. **SSE Transport** - GET /api/v1/workflow/events/stream for live events, GET /api/v1/workflow/events/recent for buffered events
4. **Instrumentation Points** - Emit events at actual boundaries in existing pipelines (telemetry, simulation, health, rag_ingestion, rag_query, agent)
5. **Frontend Workflow Page** - /workflow route with tabs (Overview, Telemetry, RAG Ingestion, RAG Query, Health, Agent), pipeline visualizations, live event timeline, filters
6. **No Persistent Storage** - Events are live observability only; PostgreSQL remains source of truth
7. **No Secrets Exposure** - Sanitize all events, never log credentials, chain-of-thought, or huge payloads

## Task List

### Phase 1: Foundation (Backend Event Model & Bus)
- [ ] Task 1: Create WorkflowEvent Pydantic models and enums (schemas/workflow.py)
- [ ] Task 2: Create bounded async event bus (services/workflow_event_bus.py)
- [ ] Task 3: Create recent events and SSE endpoints (api/routes/workflow.py)
- [ ] Task 4: Register workflow routes in router
- [ ] Task 5: Add workflow configuration to settings

### Phase 2: Telemetry Pipeline Instrumentation
- [ ] Task 6: Instrument simulator manager (simulation_started, simulation_stopped, etc.)
- [ ] Task 7: Instrument MQTT subscriber (mqtt_received, telemetry_parsed, telemetry_persisted)
- [ ] Task 8: Instrument health monitor (health_analysis_started, health_snapshot_created)

### Phase 3: Simulation & RAG Instrumentation
- [ ] Task 9: Instrument Simulation Control API (start/stop/restart events)
- [ ] Task 10: Instrument RAG ingestion pipeline (document_upload through index_ready)
- [ ] Task 11: Instrument RAG query pipeline (query_received through answer_generated)
- [ ] Task 12: Instrument Agent/LangGraph workflow (agent_request through agent_completed)

### Phase 4: Frontend API & Hooks
- [ ] Task 13: Create frontend workflow API service (services/workflow.ts)
- [ ] Task 14: Create workflow hooks (hooks/use-workflow.ts)
- [ ] Task 15: Create workflow types (types/api.ts additions)

### Phase 5: Frontend Workflow Page
- [ ] Task 16: Add navigation item for Workflow Monitor
- [ ] Task 17: Create Workflow Monitor page (app/(app)/workflow/page.tsx)
- [ ] Task 18: Create pipeline visualization components
- [ ] Task 19: Create live event timeline component
- [ ] Task 20: Create filter/search/controls components
- [ ] Task 21: Add demo mode controls

### Phase 6: Testing & Verification
- [ ] Task 22: Backend tests (event bus, endpoints, instrumentation)
- [ ] Task 23: Frontend tests (page, components, hooks)
- [ ] Task 24: Run live telemetry acceptance test
- [ ] Task 25: Run live RAG acceptance test
- [ ] Task 26: Run live health acceptance test
- [ ] Task 27: Run lint/typecheck

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Event bus blocks core operations | High | Non-blocking publish, fire-and-forget with bounded buffer |
| Secrets leaked in events | High | Sanitize all metadata, never include raw payloads |
| Chain-of-thought exposed | High | Agent events only show node names and high-level outcomes |
| SSE connection leaks | Medium | Proper cleanup on disconnect, bounded subscriber count |
| Performance impact | Medium | Lightweight event publishing, no await on delivery |

## Open Questions
- Should we add a persistent workflow_events table for historical queries? (Spec says prefer NOT)
- What correlation_id strategy for telemetry (simulation run ID)?
- Demo mode: should it auto-trigger operations or just guide manual steps?