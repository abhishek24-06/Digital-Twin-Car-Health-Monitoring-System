"""Workflow event schemas for system observability.

Defines the canonical event model used by the workflow event bus and
exposed through the Workflow Monitor API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class WorkflowType(StrEnum):
    """High-level workflow categories."""

    TELEMETRY = "telemetry"
    RAG_INGESTION = "rag_ingestion"
    RAG_QUERY = "rag_query"
    HEALTH = "health"
    AGENT = "agent"
    SIMULATION = "simulation"
    SYSTEM = "system"


class WorkflowStage(StrEnum):
    """Granular pipeline stages. Keep in sync with instrumentation points."""

    # Telemetry
    SIMULATOR_STARTED = "simulator_started"
    TELEMETRY_GENERATED = "telemetry_generated"
    MQTT_PUBLISH_STARTED = "mqtt_publish_started"
    MQTT_PUBLISHED = "mqtt_published"
    MQTT_RECEIVED = "mqtt_received"
    TELEMETRY_PARSED = "telemetry_parsed"
    TELEMETRY_VALIDATION_SUCCESS = "telemetry_validation_success"
    TELEMETRY_VALIDATION_ERROR = "telemetry_validation_error"
    TELEMETRY_PERSIST_STARTED = "telemetry_persist_started"
    TELEMETRY_PERSISTED = "telemetry_persisted"
    HEALTH_ANALYSIS_STARTED = "health_analysis_started"
    TELEMETRY_WINDOW_LOADED = "telemetry_window_loaded"
    DATA_SUFFICIENCY_EVALUATED = "data_sufficiency_evaluated"
    BASELINE_COMPARISON_COMPLETED = "baseline_comparison_completed"
    RULES_EVALUATED = "rules_evaluated"
    HEALTH_SCORE_CALCULATED = "health_score_calculated"
    CONFIDENCE_CALCULATED = "confidence_calculated"
    PROVISIONAL_STATUS_ASSIGNED = "provisional_status_assigned"
    HEALTH_SNAPSHOT_CREATED = "health_snapshot_created"
    TELEMETRY_ERROR = "telemetry_error"

    # Simulation
    SIMULATION_START_REQUESTED = "simulation_start_requested"
    SIMULATION_STARTED = "simulation_started"
    SIMULATION_RESTART_REQUESTED = "simulation_restart_requested"
    SIMULATION_RESTARTED = "simulation_restarted"
    SIMULATION_STOP_REQUESTED = "simulation_stop_requested"
    SIMULATION_STOPPED = "simulation_stopped"
    SIMULATION_ERROR = "simulation_error"
    SIMULATION_PROCESS_EXIT = "simulation_process_exit"

    # RAG Ingestion
    DOCUMENT_UPLOAD_STARTED = "document_upload_started"
    DOCUMENT_RECEIVED = "document_received"
    DOCUMENT_PARSE_STARTED = "document_parse_started"
    DOCUMENT_PARSED = "document_parsed"
    TEXT_EXTRACTED = "text_extracted"
    SECTIONS_DETECTED = "sections_detected"
    CHUNKING_STARTED = "chunking_started"
    CHUNKS_CREATED = "chunks_created"
    METADATA_ATTACHED = "metadata_attached"
    EMBEDDING_STARTED = "embedding_started"
    EMBEDDINGS_GENERATED = "embeddings_generated"
    VECTOR_STORAGE_STARTED = "vector_storage_started"
    CHUNKS_STORED = "chunks_stored"
    INDEX_READY = "index_ready"
    INGESTION_COMPLETED = "ingestion_completed"
    INGESTION_ERROR = "ingestion_error"

    # RAG Query
    QUERY_RECEIVED = "query_received"
    QUERY_EMBEDDING_STARTED = "query_embedding_started"
    QUERY_EMBEDDING_COMPLETED = "query_embedding_completed"
    VECTOR_SEARCH_STARTED = "vector_search_started"
    VECTOR_SEARCH_COMPLETED = "vector_search_completed"
    CANDIDATES_RETRIEVED = "candidates_retrieved"
    RERANKING_STARTED = "reranking_started"
    RERANKING_COMPLETED = "reranking_completed"
    CONTEXT_ASSEMBLED = "context_assembled"
    ANSWER_GENERATION_STARTED = "answer_generation_started"
    ANSWER_GENERATED = "answer_generated"
    SOURCES_ATTACHED = "sources_attached"
    RAG_QUERY_COMPLETED = "rag_query_completed"
    RAG_QUERY_ERROR = "rag_query_error"

    # Agent
    AGENT_REQUEST_RECEIVED = "agent_request_received"
    SUPERVISOR_STARTED = "supervisor_started"
    SUPERVISOR_COMPLETED = "supervisor_completed"
    VEHICLE_CONTEXT_LOADED = "vehicle_context_loaded"
    HEALTH_CONTEXT_LOADED = "health_context_loaded"
    MANUFACTURER_CONTEXT_REQUESTED = "manufacturer_context_requested"
    RAG_CONTEXT_RECEIVED = "rag_context_received"
    REASONING_STARTED = "reasoning_started"
    TOOL_COMPLETED = "tool_completed"
    RESPONSE_GENERATED = "response_generated"
    AGENT_COMPLETED = "agent_completed"
    AGENT_ERROR = "agent_error"

    # System
    SUBSCRIBER_STARTED = "subscriber_started"
    SUBSCRIBER_STOPPED = "subscriber_stopped"
    SUBSCRIBER_ERROR = "subscriber_error"
    STREAM_CONNECTED = "stream_connected"
    STREAM_DISCONNECTED = "stream_disconnected"


class WorkflowStatus(StrEnum):
    """Event outcome.

    This is the exact persisted backend vocabulary. ``WAITING`` is a
    frontend-only presentation state and MUST NOT be added here; a stage with
    no backend signal is omitted from derived state, never persisted as
    ``WAITING``.
    """

    STARTED = "started"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    DEGRADED = "degraded"
    ERROR = "error"
    SKIPPED = "skipped"


def new_correlation_id(prefix: str) -> str:
    """Return a fresh, URL-safe correlation id with a subsystem ``prefix``.

    One helper for every producer so a single logical operation (a simulation
    start, a RAG query, an ingestion) is followed end-to-end by one id. This is
    NOT a second identity system: callers that already own a meaningful
    operation id keep using it.
    """
    return f"{prefix}-{uuid4().hex[:12]}"


class WorkflowEvent(BaseModel):
    """A single workflow observability event.

    Every field is intentionally lightweight - no huge payloads, no secrets.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    workflow: WorkflowType
    stage: WorkflowStage
    status: WorkflowStatus
    message: str
    vehicle_id: UUID | None = None
    document_id: UUID | None = None
    correlation_id: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowEventResponse(BaseModel):
    """API response for a single workflow event."""

    event_id: UUID
    timestamp: datetime
    workflow: WorkflowType
    stage: WorkflowStage
    status: WorkflowStatus
    message: str
    vehicle_id: UUID | None = None
    document_id: UUID | None = None
    correlation_id: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRecentResponse(BaseModel):
    """Paginated recent events response."""

    items: list[WorkflowEventResponse]
    total: int
    limit: int
    offset: int


class WorkflowStatusResponse(BaseModel):
    """High-level workflow system status."""

    telemetry_pipeline_active: bool
    rag_pipeline_active: bool
    agent_pipeline_active: bool
    subscriber_running: bool
    active_simulations: int
    events_in_buffer: int
    oldest_event_ts: datetime | None = None
    newest_event_ts: datetime | None = None


class WorkflowEventFilters(BaseModel):
    """Filters for querying recent events."""

    workflow: WorkflowType | None = None
    stage: WorkflowStage | None = None
    status: WorkflowStatus | None = None
    vehicle_id: UUID | None = None
    document_id: UUID | None = None
    correlation_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class TelemetryStage(StrEnum):
    """Presentation-only stages of the telemetry pipeline.

    These are NOT event types. They exist so the read-only ``/workflow/state``
    endpoint can describe how far a vehicle's telemetry has actually flowed,
    derived from real process and database signals. The high-frequency work
    inside the subscriber subprocess (per-message parse/validate) is never
    bridged onto the bus; the ``parser`` stage therefore means "a confirmed
    healthy telemetry flow is observed", not "this exact message was parsed".
    """

    SIMULATOR = "simulator"
    MQTT_PUBLISH = "mqtt_publish"
    MQTT_BROKER = "mqtt_broker"
    MQTT_SUBSCRIBER = "mqtt_subscriber"
    PARSER = "parser"
    POSTGRES = "postgres"
    HEALTH_ENGINE = "health_engine"
    HEALTH_SNAPSHOT = "health_snapshot"


class StageState(BaseModel):
    """One stage in a derived telemetry snapshot.

    ``observation`` is always explicit so a derived state is never presented
    as a directly observed event, and ``status`` is the exact backend
    vocabulary (never ``waiting``; a stage with no signal is omitted).
    """

    model_config = ConfigDict(extra="forbid")

    stage: TelemetryStage
    status: WorkflowStatus
    observation: Literal["observed", "derived"] = "derived"
    at: datetime | None = None
    detail: str | None = None


class VehicleTelemetryState(BaseModel):
    """Derived telemetry pipeline snapshot for one vehicle."""

    model_config = ConfigDict(extra="forbid")

    vehicle_id: UUID
    simulation_status: str
    stages: list[StageState] = Field(default_factory=list)
    last_telemetry_at: datetime | None = None
    messages_received: int = 0
    snapshot_at: datetime | None = None
    degraded_reason: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowStateResponse(BaseModel):
    """Response for ``GET /workflow/state`` (derived, read-only)."""

    items: list[VehicleTelemetryState] = Field(default_factory=list)


def sanitize_metadata(metadata: dict[str, Any], max_size: int = 2048) -> dict[str, Any]:
    """Remove secrets and truncate large values from metadata.

    Never expose:
    - passwords, api_keys, tokens, secrets
    - database URLs
    - full telemetry payloads (> 1KB)
    - chain-of-thought reasoning
    """
    if not metadata:
        return {}

    sensitive_keys = {
        "password",
        "api_key",
        "token",
        "secret",
        "credential",
        "authorization",
        "access_token",
        "refresh_token",
        "database_url",
        "db_password",
        "mqtt_password",
        "llm_api_key",
        "openai_key",
        "provider_key",
        "chain_of_thought",
        "reasoning",
        "thought",
    }

    sanitized: dict[str, Any] = {}
    total_size = 0

    for key, value in metadata.items():
        lower_key = key.lower()
        if any(sensitive in lower_key for sensitive in sensitive_keys):
            sanitized[key] = "[REDACTED]"
            continue

        # Truncate large strings
        if isinstance(value, str) and len(value) > 1000:
            value = value[:1000] + "...[truncated]"

        # Estimate size
        import json

        item_size = len(json.dumps({key: value}, separators=(",", ":")))
        if total_size + item_size > max_size:
            sanitized["_truncated"] = f"metadata exceeds {max_size} bytes"
            break

        sanitized[key] = value
        total_size += item_size

    return sanitized
