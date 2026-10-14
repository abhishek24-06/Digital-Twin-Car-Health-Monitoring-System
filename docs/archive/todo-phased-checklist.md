# Task List: System Workflow / Live Observability

Legend: **S** 1-2 files | **M** 3-5 files | **L** 5+ files

---

## Phase 1: Foundation (Backend Event Model & Bus)

### Task 1: Create WorkflowEvent Pydantic models and enums

- [x] Create `backend/app/schemas/workflow.py` with:
  - `WorkflowType` enum: telemetry, rag_ingestion, rag_query, health, agent, simulation, system
  - `WorkflowStage` enum: all stages from spec
  - `WorkflowStatus` enum: started, running, success, warning, error
  - `WorkflowEvent` model with all fields
  - `WorkflowEventResponse` for API
  - `WorkflowRecentResponse` with pagination
  - `WorkflowStatusResponse` for high-level state
- [x] Verify: `python -c "import app.schemas.workflow"` clean
- Files: `backend/app/schemas/workflow.py`
- Size: S

### Task 2: Create bounded async event bus

- [x] Create `backend/app/services/workflow_event_bus.py` with:
  - `WorkflowEventBus` class with ring buffer (max 500)
  - `publish(event)` - non-blocking, fire-and-forget
  - `subscribe()` - async generator for live events
  - `get_recent(limit)` - newest first
  - `clear()` - frontend "clear view" only
  - Thread-safe with asyncio locks
  - Bounded memory, no unbounded accumulation
- [x] Verify: `pytest tests/services/test_workflow_event_bus.py -q` passes
- Files: `backend/app/services/workflow_event_bus.py`, `tests/services/test_workflow_event_bus.py`
- Size: M

### Task 3: Create recent events and SSE endpoints

- [x] Create `backend/app/api/routes/workflow.py` with:
  - `GET /api/v1/workflow/events/recent` - paginated, newest first, max limit
  - `GET /api/v1/workflow/events/stream` - SSE with heartbeat, reconnect support
  - `GET /api/v1/workflow/status` - high-level workflow state
  - Proper error handling, client disconnect handling
  - OpenAPI documentation
- [ ] Verify: `pytest tests/api/test_workflow.py -q` passes (tests need to be created)
- Files: `backend/app/api/routes/workflow.py`, `tests/api/test_workflow.py`
- Size: M

### Task 4: Register workflow routes in router

- [x] Add workflow router to `backend/app/api/router.py`
- [x] Tag: "Workflow"
- Files: `backend/app/api/router.py`
- Size: XS

### Task 5: Add workflow configuration to settings

- [x] Add `workflow_event_buffer_size` (default 500) to `backend/app/core/config.py`
- [x] Add `workflow_max_subscribers` (default 50) to settings
- [x] Add `workflow_sse_heartbeat_seconds` (default 15) to settings
- [x] Verify: config validation works
- Files: `backend/app/core/config.py`, `tests/core/test_config.py`
- Size: S

---

## Phase 2: Telemetry Pipeline Instrumentation

### Task 6: Instrument simulator manager

- [x] Add workflow event emission to `backend/app/services/simulation_manager.py`:
  - `simulation_start_requested` (on start call)
  - `simulation_started` (when process confirmed running)
  - `simulation_stop_requested` (on stop call)
  - `simulation_stopped` (when process terminated)
  - `simulation_restart_requested` / `simulation_restarted`
  - `simulation_process_exit` (unexpected exit with error)
  - Include vehicle_id, scenario, interval, pid where appropriate
  - Use correlation_id = simulation run identifier
- [x] Verify: events emitted during live simulation
- Files: `backend/app/services/simulation_manager.py`
- Size: M

### Task 7: Instrument MQTT subscriber

- [x] Add workflow event emission to `backend/app/mqtt/subscriber.py`:
  - `mqtt_received` (topic, payload size, vehicle_id)
  - `telemetry_parsed` (event_id, signal count)
  - `telemetry_validation_success` / `telemetry_validation_error`
  - `telemetry_persist_started` / `telemetry_persisted` (duration_ms, table)
  - Use existing correlation_id from message if available
- [x] Verify: events flow during live telemetry
- Files: `backend/app/mqtt/subscriber.py`
- Size: M

### Task 8: Instrument health monitor

- [x] Add workflow event emission to `backend/app/services/health_monitor.py`:
  - `health_analysis_started` (vehicle_id, window, sample_count)
  - `telemetry_window_loaded` (coverage, duration)
  - `data_sufficiency_evaluated` (sufficiency level)
  - `baseline_comparison_completed` (baselines count)
  - `rules_evaluated` (findings count)
  - `health_score_calculated` (score, confidence)
  - `provisional_status_assigned` (rating, provisional)
  - `health_snapshot_created` (snapshot_id, health_status, sample_count, confidence)
  - `health_analysis_error` (vehicle_id, error)
- [x] Verify: events during health pass
- Files: `backend/app/services/health_monitor.py`
- Size: M

---

## Phase 3: Simulation & RAG Instrumentation

### Task 9: Instrument Simulation Control API

- [x] Add workflow event emission to `backend/app/api/routes/simulation.py`:
  - `simulation_start_requested` (API entry)
  - `simulation_stop_requested`
  - `simulation_restart_requested`
  - Include user context (user_id), vehicle_id, scenario
- [x] Verify: events on API calls
- Files: `backend/app/api/routes/simulation.py`
- Size: S

### Task 10: Instrument RAG ingestion pipeline

- [x] Add workflow event emission to `backend/app/rag/ingestion.py`:
  - `document_upload_started` / `document_received` (filename, size)
  - `document_parse_started` / `document_parsed` (parser_name, pages)
  - `text_extracted` (char count)
  - `sections_detected` (section count)
  - `chunking_started` / `chunks_created` (chunk_count, chunking_version)
  - `metadata_attached` (scope info)
  - `embedding_started` / `embeddings_generated` (model, dimensions, duration)
  - `vector_storage_started` / `chunks_stored` (version_id)
  - `index_ready` / `ingestion_completed` (document_id, chunk_count)
  - `ingestion_error` (stage, error)
  - Include document_id, correlation_id = ingestion run
- [x] Verify: events during document ingestion
- Files: `backend/app/rag/ingestion.py`
- Size: M

### Task 11: Instrument RAG query pipeline

- [x] Add workflow event emission to `backend/app/rag/rag_service.py`:
  - `query_received` (query length, scope)
  - `query_embedding_started` / `query_embedding_completed` (model, duration)
  - `vector_search_started` / `vector_search_completed` (candidates, duration)
  - `candidates_retrieved` (count, alpha)
  - `reranking_started` / `reranking_completed` (reranker, count, duration)
  - `context_assembled` (evidence count, chars)
  - `answer_generation_started` / `answer_generated` (model, duration)
  - `sources_attached` (source count, pages)
  - `rag_query_completed` / `rag_query_error` (total duration)
  - Include correlation_id = query run
- [x] Verify: events during Manufacturer Guidance search
- Files: `backend/app/rag/rag_service.py`
- Size: M

### Task 12: Instrument Agent/LangGraph workflow

- [x] Add workflow event emission to `backend/app/agent/nodes.py` nodes:
  - `agent_request_received` (trigger_type, vehicle_id)
  - `supervisor_started` / `supervisor_completed` (decision)
  - `vehicle_context_loaded` (has_context)
  - `health_context_loaded` (has_context, status)
  - `manufacturer_context_requested` / `rag_context_received` (evidence count)
  - `reasoning_started` / `tool_completed` (tool_name)
  - `response_generated` / `agent_completed` (duration, has_diagnosis)
  - `agent_error` (stage, error)
  - NO chain-of-thought, NO hidden reasoning
  - Include correlation_id = agent run ID
- [x] Verify: events during agent queries
- Files: `backend/app/agent/nodes.py`
- Size: M

---

## Phase 4: Frontend API & Hooks

### Task 13: Create frontend workflow API service

- [ ] Create `frontend/src/services/workflow.ts`:
  - `getRecentEvents(params)` - pagination, filters
  - `streamEvents()` - EventSource wrapper
  - `getWorkflowStatus()` - high-level state
  - TypeScript types matching backend
- [ ] Verify: TypeScript compiles
- Files: `frontend/src/services/workflow.ts`
- Size: S

### Task 14: Create workflow hooks

- [ ] Create `frontend/src/hooks/use-workflow.ts`:
  - `useWorkflowEvents()` - recent + live via SSE, reconnection
  - `useWorkflowStatus()` - high-level state
  - Connection state: Live / Reconnecting / Offline
  - Filtering by workflow, status, vehicle, document
  - Pause/resume/clear controls
  - Recent events backfill after reconnect
- [ ] Verify: hooks work in isolation
- Files: `frontend/src/hooks/use-workflow.ts`, `frontend/src/components/workflow/__tests__/use-workflow.test.tsx`
- Size: M

### Task 15: Create workflow types

- [ ] Add to `frontend/src/types/api.ts`:
  - `WorkflowType`, `WorkflowStage`, `WorkflowStatus` enums
  - `WorkflowEvent` interface
  - `WorkflowEventResponse`, `WorkflowRecentResponse`, `WorkflowStatusResponse`
  - `WorkflowEventFilters` interface
- [ ] Verify: `npm run typecheck` clean
- Files: `frontend/src/types/api.ts`
- Size: S

---

## Phase 5: Frontend Workflow Page

### Task 16: Add navigation item for Workflow Monitor

- [ ] Add to `frontend/src/components/layout/nav-items.tsx`:
  - `href: "/workflow"`, label: "Workflow Monitor", icon: Activity/GitBranch
  - Description: "Real-time observability of system pipelines"
- [ ] Verify: navigation renders correctly
- Files: `frontend/src/components/layout/nav-items.tsx`
- Size: XS

### Task 17: Create Workflow Monitor page

- [ ] Create `frontend/src/app/(app)/workflow/page.tsx` with:
  - Header: "System Workflow" + "Real-time view of the Digital Twin execution pipeline"
  - Connection indicator: ● Live / ○ Reconnecting
  - Tabs: [Overview] [Telemetry] [RAG Ingestion] [RAG Query] [Health] [Agent]
  - Responsive layout using existing design system
- [ ] Verify: page renders, navigation works
- Files: `frontend/src/app/(app)/workflow/page.tsx`, `frontend/src/components/workflow/workflow-view.tsx`
- Size: M

### Task 18: Create pipeline visualization components

- [ ] Create pipeline cards for each tab:
  - Telemetry: Simulator → MQTT Publish → Mosquitto → MQTT Subscriber → Parser → PostgreSQL → Health Engine → Health Snapshot
  - RAG Ingestion: Document → Parser → Text Extraction → Chunking → Embedding → pgVector → Index → Ready
  - RAG Query: Question → Query Embedding → Vector Search → Candidates → Reranking → Context → Answer
  - Health: Telemetry Window → Data Sufficiency → Rules → Baseline → Score → Confidence → Snapshot
  - Agent: User Question → Supervisor → Vehicle Context / Health Context / Manufacturer Guidance → Response Generated
  - Each node: status badge, latest timestamp, duration, count
  - Only show real data, no fabricated counters
- [ ] Verify: pipelines render with live data
- Files: `frontend/src/components/workflow/pipeline-*.tsx`
- Size: L

### Task 19: Create live event timeline component

- [ ] Create `frontend/src/components/workflow/event-timeline.tsx`:
  - Real-time event stream with timestamps
  - Color-coded by workflow (telemetry=blue, rag=purple, health=green, agent=orange, simulation=gray)
  - Status badges: RUNNING/SUCCESS/WARNING/ERROR
  - Collapsible metadata
  - Pause/Resume/Clear controls
  - Search/filter by stage, message, vehicle, document
  - Virtualized list for performance
- [ ] Verify: events stream live, filters work
- Files: `frontend/src/components/workflow/event-timeline.tsx`
- Size: M

### Task 20: Create filter/search/controls components

- [ ] Create filter bar component:
  - Workflow dropdown (All / Telemetry / RAG Ingestion / RAG Query / Health / Agent / Simulation / System)
  - Status dropdown (All / Running / Success / Warning / Error)
  - Vehicle dropdown (All / specific vehicles)
  - Document dropdown (All / specific documents)
  - Search input (stage, message, vehicle, document)
  - Clear/Pause/Resume buttons
- [ ] Verify: filters apply to timeline and pipelines
- Files: `frontend/src/components/workflow/filters.tsx`
- Size: M

### Task 21: Add demo mode controls

- [ ] Add demo controls to workflow page:
  - "Run Telemetry Demo" - starts simulation, shows full pipeline
  - "Run RAG Demo" - triggers ingestion + query
  - "Run Health Demo" - triggers health analysis
  - "Run Full Demo" - sequence all three
  - DO NOT fake events - must trigger actual system operations
  - Guided manual controls if auto would be invasive
- [ ] Verify: demo triggers real operations
- Files: `frontend/src/components/workflow/demo-controls.tsx`
- Size: M

---

## Phase 6: Testing & Verification

### Task 22: Backend tests

- [x] `tests/services/test_workflow_event_bus.py` - event creation, bus publish/subscribe, bounded buffer, recent events, clear
- [ ] `tests/api/test_workflow.py` - recent endpoint, SSE endpoint, client disconnect, status endpoint
- [x] `tests/services/test_simulation_manager.py` - verify workflow events emitted
- [x] `tests/services/test_health_monitor_service.py` - verify health events
- [ ] `tests/rag/test_ingestion.py` - verify ingestion events
- [ ] `tests/rag/test_rag_service.py` - verify query events
- [ ] `tests/agent/test_graph.py` - verify agent events
- [ ] Full backend suite: `pytest -q` passes
- Files: Multiple test files
- Size: L

### Task 23: Frontend tests

- [ ] `frontend/src/components/workflow/__tests__/workflow-view.test.tsx` - page renders, tabs work, connection state
- [ ] `frontend/src/components/workflow/__tests__/pipeline-*.test.tsx` - nodes render, status badges
- [ ] `frontend/src/components/workflow/__tests__/event-timeline.test.tsx` - events stream, filters, pause/clear
- [ ] `frontend/src/components/workflow/__tests__/demo-controls.test.tsx` - demo buttons trigger API calls
- [ ] `frontend/src/hooks/__tests__/use-workflow.test.tsx` - hook behavior
- [ ] Full frontend suite: `npm run test -- --run` passes
- [ ] `npm run typecheck` clean, `npm run lint` clean
- Files: Multiple test files
- Size: L

### Task 24: Run live telemetry acceptance test

- [ ] Start FastAPI + supervised subscriber
- [ ] Start exactly one simulator
- [ ] Verify workflow events: simulator → mqtt publish → mqtt receive → parse → persistence
- [ ] Verify NEW telemetry_records row exists
- [ ] Verify health analysis occurs
- [ ] Verify NEW health snapshot occurs
- [ ] Verify frontend Workflow Monitor receives events
- [ ] Verify no duplicate simulator process
- Verification: Live timestamps, process counts, DB rows

### Task 25: Run live RAG acceptance test

- [ ] Use existing supported manufacturer document
- [ ] Start ingestion
- [ ] Observe: document received → parsing → extraction → chunking → embeddings → vector storage → index/ready
- [ ] Verify actual chunk count, vector storage
- [ ] Run Manufacturer Guidance question
- [ ] Observe: query → embedding → retrieval → reranking → context → answer
- [ ] Show actual source document/page metadata

### Task 26: Run live health acceptance test

- [ ] Generate telemetry
- [ ] Observe health analysis events
- [ ] Verify: sample count, coverage, score, confidence, status, provisional state
- [ ] Verify health snapshot timestamp is newer than previous

### Task 27: Run lint/typecheck

- [ ] Backend: `ruff check .` + `ruff format --check .` clean
- [ ] Frontend: `npm run typecheck` + `npm run lint` clean
- [ ] Verify OpenAPI has workflow endpoints
- [ ] All tests pass