"""Typed LangGraph state for the Phase 4 reasoning workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict
from uuid import UUID

from app.agent.triggers import TriggerType


class AgentState(TypedDict, total=False):
    """State flowing through the supervisor -> reason -> validate -> persist graph."""

    agent_run_id: str
    vehicle_id: UUID
    trigger_type: TriggerType
    user_query: str

    # User who initiated this run (attribution only). NULL for system-triggered
    # and internal-process executions (e.g. MQTT critical events before the
    # Phase 7 event pipeline).
    user_id: UUID | None

    # Context gathered by the Vehicle Context Tool (deterministic layer).
    vehicle_context: dict[str, Any] | None
    serialized_context: str
    context_note: str
    needs_llm: bool
    severity: str
    confidence: float
    context_timestamp: datetime | None

    # Reasoning produced either by the LLM or (when no context exists) canned.
    reasoning: dict[str, Any] | None

    # RAG dispatch decisions + results from the Manufacturer Guidance Tool.
    needs_rag: bool
    manufacturer_guidance: dict[str, Any] | None

    # Provider/execution metadata from the LLM call.
    execution_metadata: dict[str, Any] | None

    # Final validated DiagnosisResponse shape (JSON-serializable dict).
    final_response: dict[str, Any] | None
