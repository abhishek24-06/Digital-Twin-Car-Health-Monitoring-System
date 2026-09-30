"""Pydantic schemas for agent diagnosis responses (Phase 4).

These models define the structured ``DiagnosisResponse`` contract consumed by
the API layer. They are deliberately decoupled from the deterministic Phase 3
context models (only the ``Severity`` literal is shared), so the agent layer
never mutates the engine output it interprets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.intelligence.models import Severity
from app.rag.schemas import Citation

Likelihood = Literal["high", "medium", "low"]
ActionPriority = Literal["immediate", "high", "medium", "low"]
ActionCategory = Literal["mechanical", "inspection", "logistics", "operator", "other"]


class EvidenceItem(BaseModel):
    """One grounded piece of evidence the diagnosis is based on.

    Every item must trace to a real rule finding or metric statistic present
    in the Vehicle Health Context; anything else is dropped during grounding.
    """

    rule_id: str | None = None
    metric: str | None = None
    observed_value: float | None = None
    threshold: float | None = None
    unit: str | None = None
    message: str = ""
    severity: Severity | None = None


class Hypothesis(BaseModel):
    """A possible cause. Wording must treat it as a hypothesis, not a verdict."""

    cause: str
    likelihood: Likelihood = "medium"
    matching_evidence: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class RecommendedAction(BaseModel):
    """A recommended next action, categorized for downstream handling."""

    action: str
    priority: ActionPriority = "medium"
    category: ActionCategory = "other"


class SeverityAnalysis(BaseModel):
    """How the assessed severity relates to the deterministic rule severity."""

    assessed_severity: Severity = "info"
    rule_severity: Severity = "info"
    rationale: str = ""


class ConfidenceAnalysis(BaseModel):
    """Confidence assessment anchored to deterministic context quality."""

    assessed_confidence: float = 0.0
    deterministic_confidence: float = 0.0
    score_quality: str = "low"
    data_quality: str = "low"
    rationale: str = ""
    validation_warnings: list[str] = Field(default_factory=list)


class ManufacturerEvidence(BaseModel):
    """Bounded metadata for one retrieved manufacturer source shown to the LLM.

    Full chunk text is never copied into the diagnosis; only provenance,
    scores and a short excerpt are persisted so the record stays auditable and
    JSON-serializable.
    """

    index: int
    source_filename: str | None = None
    title: str = ""
    section_title: str = ""
    page_start: int | None = None
    page_end: int | None = None
    scope: str | None = None
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    rerank_score: float | None = None
    excerpt: str = ""


class DiagnosisContent(BaseModel):
    """The interpreted diagnosis produced by the reasoning layer.

    Content is anchored to the Vehicle Health Context; anything that cannot be
    grounded in that context is removed during validation.

    When the Manufacturer Guidance Tool supplied evidence, the model may add a
    ``manufacturer_guidance`` note and ``cited_sources`` references. Only refs
    that resolve to *actually retrieved* evidence survive validation; titles,
    page ranges and document ids are rebuilt app-side from the tool result.
    """

    summary: str = ""
    possible_causes: list[Hypothesis] = Field(default_factory=list)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    severity_analysis: SeverityAnalysis = Field(default_factory=SeverityAnalysis)
    confidence_analysis: ConfidenceAnalysis = Field(default_factory=ConfidenceAnalysis)
    context_note: str = ""
    manufacturer_guidance: str = ""
    cited_sources: list[int] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    manufacturer_evidence: list[ManufacturerEvidence] = Field(default_factory=list)


class ExecutionMetadata(BaseModel):
    """Provider execution details for the call that produced the diagnosis."""

    latency_ms: float = 0.0
    provider: str = ""
    model: str = ""
    fallback_used: bool = False
    fallback_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 1
    deduplicated: bool = False
    rule_ids: list[str] = Field(default_factory=list)
    rag_used: bool = False
    rag_evidence_count: int = 0
    rag_embedding_model: str | None = None
    rag_reranker_model: str | None = None
    rag_scope: dict[str, Any] = Field(default_factory=dict)
    rag_reason: str = ""


class DiagnosisResponse(BaseModel):
    """The full agent response returned by the API."""

    id: UUID | None = None
    vehicle_id: UUID
    trigger_type: str
    user_query: str = ""
    diagnosis: DiagnosisContent
    severity: Severity
    confidence: float
    context_timestamp: datetime | None = None
    generated_at: datetime
    execution: ExecutionMetadata = Field(default_factory=ExecutionMetadata)
