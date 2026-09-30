"""Graph nodes implementing the Phase 4 supervisor reasoning workflow.

Executing a diagnosis always ends in a persisted record. When no Vehicle
Health Context exists the supervisor short-circuits the LLM with a canned,
fully grounded reasoning object so the validate/persist path stays uniform.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.agent.determinism import SEVERITY_RANK
from app.agent.errors import GraphExecutionError, StructuredOutputError
from app.agent.grounding import ground_evidence
from app.agent.llm_service import LLMService
from app.agent.prompts import build_query_messages
from app.agent.schemas import (
    DiagnosisContent,
    DiagnosisResponse,
    ExecutionMetadata,
)
from app.agent.state import AgentState
from app.agent.tools.vehicle_context import VehicleContextTool
from app.agent.triggers import TriggerType
from app.models.agent_diagnosis import AgentDiagnosis

logger = logging.getLogger(__name__)


async def supervisor_node(
    state: AgentState, *, tool: VehicleContextTool, rag_tool: Any
) -> dict[str, Any]:
    """Gather the Vehicle Health Context and decide whether LLM/RAG is needed."""
    result = await tool.get_context(state["vehicle_id"])
    has_context = result.context is not None
    return {
        "agent_run_id": state.get("agent_run_id") or str(uuid4()),
        "vehicle_context": result.context.model_dump(mode="json") if has_context else None,
        "serialized_context": result.serialized_context,
        "context_note": result.context_note,
        "needs_llm": has_context,
        "needs_rag": _needs_rag(rag_tool, state.get("user_query") or ""),
        "severity": result.severity,
        "confidence": result.confidence,
        "context_timestamp": result.context_timestamp,
        "manufacturer_guidance": None,
        "reasoning": None if has_context else _canned_reasoning(),
    }


def _needs_rag(tool: Any, query: str) -> bool:
    from app.agent.rag_dispatch import should_use_rag

    return should_use_rag(tool=tool, query=query)


def should_reason_or_rag(state: AgentState) -> str:
    """Conditional edge from the supervisor: rag -> reason -> validate."""
    if state.get("needs_rag", False):
        return "rag"
    return should_reason(state)


async def rag_node(state: AgentState, *, rag_tool: Any) -> dict[str, Any]:
    """Run the Manufacturer Guidance Tool and merge its evidence into the state.

    RAG evidence alone is enough to route to the reasoning step, even when no
    Vehicle Health Context exists (``needs_llm`` is upgraded to ``True``).
    """
    if rag_tool is None:
        return {"needs_rag": False, "manufacturer_guidance": None}
    result = await rag_tool.get_guidance(state["vehicle_id"], state.get("user_query") or "")
    payload = _guidance_payload(result)
    return {
        "manufacturer_guidance": payload,
        "needs_llm": bool(state.get("needs_llm", False)) or bool(payload.get("evidence")),
    }


def should_reason(state: AgentState) -> str:
    """Conditional edge: call the LLM only when context data exists."""
    return "reason" if state.get("needs_llm", False) else "validate"


async def reason_node(state: AgentState, *, llm_service: LLMService) -> dict[str, Any]:
    """Invoke the LLM over the bounded context and capture execution metadata."""
    pre_set = state.get("execution_metadata") or {}
    mg = state.get("manufacturer_guidance") or {}
    rag_available = bool(mg.get("available")) and bool(mg.get("evidence"))
    guidance_text = (mg.get("guidance") or "") if rag_available else ""
    evidence = (mg.get("evidence") or []) if rag_available else []
    rag_metrics = (mg.get("metrics") or {}) if isinstance(mg.get("metrics"), dict) else {}

    result = await llm_service.invoke_structured(
        build_query_messages(
            context_json=state.get("serialized_context") or "",
            user_query=state.get("user_query") or "",
            context_note=state.get("context_note") or "",
            manufacturer_guidance=guidance_text,
            manufacturer_sources=_format_sources(evidence),
        )
    )
    return {
        "reasoning": json.loads(result.content),
        "execution_metadata": {
            "latency_ms": result.latency_ms,
            "provider": result.provider,
            "model": result.model,
            "fallback_used": result.fallback_used,
            "fallback_reason": result.fallback_reason,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "attempts": result.attempts,
            "rule_ids": list(pre_set.get("rule_ids") or []),
            "rag_used": bool(evidence),
            "rag_evidence_count": len(evidence),
            "rag_embedding_model": rag_metrics.get("embedding_model"),
            "rag_reranker_model": rag_metrics.get("reranker_model"),
            "rag_scope": (mg.get("scope") or {}) if isinstance(mg.get("scope"), dict) else {},
            "rag_reason": mg.get("reason") or "",
        },
    }


def _format_sources(evidence: list[dict[str, Any]]) -> str:
    """Numbered source list handed to the LLM (mirrors the [n] markers)."""
    parts: list[str] = []
    for item in evidence:
        title = item.get("title") or item.get("source_filename") or "source"
        section = f" ({item.get('section_title')})" if item.get("section_title") else ""
        pages = ""
        page_start = item.get("page_start")
        page_end = item.get("page_end")
        if page_start and page_end:
            pages = f", pages {page_start}-{page_end}"
        elif page_start:
            pages = f", page {page_start}"
        parts.append(f"{item.get('index', 0)}. {title}{section}{pages}")
    return "\n".join(parts)


async def validate_node(state: AgentState) -> dict[str, Any]:
    """Validate the reasoning payload, ground its evidence, clamp severity/confidence."""
    reasoning = state.get("reasoning")
    if not isinstance(reasoning, dict):
        raise GraphExecutionError("Agent workflow produced no reasoning content")

    content = _validated_content(reasoning, state)
    final = DiagnosisResponse(
        id=None,
        vehicle_id=state["vehicle_id"],
        trigger_type=_trigger_value(state),
        user_query=state.get("user_query") or "",
        diagnosis=content,
        severity=state.get("severity") or "info",
        confidence=state.get("confidence") or 0.0,
        context_timestamp=state.get("context_timestamp"),
        generated_at=datetime.now(UTC),
        execution=ExecutionMetadata(**_execution_metadata(state)),
    )
    return {"final_response": final.model_dump(mode="json"), "reasoning": None}


async def persist_node(state: AgentState, *, repository: Any, session: Any) -> dict[str, Any]:
    """Persist the validated diagnosis and attach its record id to the response."""
    final: dict[str, Any] = state["final_response"]
    meta: dict[str, Any] = state.get("execution_metadata") or {}

    record = AgentDiagnosis(
        vehicle_id=state["vehicle_id"],
        user_id=state.get("user_id"),
        agent_run_id=state.get("agent_run_id"),
        trigger_type=final.get("trigger_type") or _trigger_value(state),
        user_query=state.get("user_query") or final.get("user_query") or "",
        diagnosis=final,
        severity=final.get("severity") or "info",
        confidence=final.get("confidence"),
        status="completed",
        error_code=None,
        provider=meta.get("provider"),
        model=meta.get("model"),
        fallback_used=bool(meta.get("fallback_used")),
        latency_ms=meta.get("latency_ms"),
        input_tokens=int(meta.get("input_tokens") or 0),
        output_tokens=int(meta.get("output_tokens") or 0),
        context_timestamp=state.get("context_timestamp"),
        rag_used=bool(meta.get("rag_used")),
        rag_evidence_count=int(meta.get("rag_evidence_count") or 0),
        rag_embedding_model=meta.get("rag_embedding_model"),
        rag_reranker_model=meta.get("rag_reranker_model"),
        rag_scope=(
            (meta.get("rag_scope") or {}) if isinstance(meta.get("rag_scope"), dict) else {}
        ),
    )
    created = await repository.create(record)

    final_with_id = dict(record.diagnosis)
    final_with_id["id"] = str(created.id)
    record.diagnosis = final_with_id
    await session.commit()
    return {"final_response": final_with_id}


def _validated_content(reasoning: dict[str, Any], state: AgentState) -> DiagnosisContent:
    try:
        content = DiagnosisContent.model_validate(_normalize_literals(reasoning))
    except ValidationError as exc:
        raise StructuredOutputError(f"Model output failed schema validation: {exc}") from exc

    context = _context_from_state(state)
    grounded, ground_warnings = ground_evidence(content.evidence, context)
    warnings = list(content.confidence_analysis.validation_warnings) + ground_warnings

    manufacturer_guidance, citations, cited_sources, manufacturer_evidence = _validate_manufacturer(
        content, state, warnings
    )

    rule_severity = content.severity_analysis.rule_severity
    assessed_severity = content.severity_analysis.assessed_severity
    deterministic_severity = state.get("severity") or "info"
    if SEVERITY_RANK[assessed_severity] > SEVERITY_RANK[rule_severity]:
        assessed_severity = rule_severity
        warnings.append("assessed_severity clamped to deterministic rule severity")
    if SEVERITY_RANK[assessed_severity] > SEVERITY_RANK[deterministic_severity]:
        assessed_severity = deterministic_severity
        warnings.append("assessed_severity clamped to deterministic vehicle severity")

    deterministic_confidence = float(state.get("confidence") or 0.0)
    assessed_confidence = content.confidence_analysis.assessed_confidence
    if not 0.0 <= assessed_confidence <= 1.0:
        assessed_confidence = max(0.0, min(1.0, assessed_confidence))
        warnings.append("assessed_confidence clamped to [0, 1]")
    if abs(assessed_confidence - deterministic_confidence) > 0.2:
        lower = max(0.0, deterministic_confidence - 0.2)
        upper = min(1.0, deterministic_confidence + 0.2)
        assessed_confidence = max(lower, min(upper, assessed_confidence))
        warnings.append(
            "assessed_confidence adjusted to stay within 0.2 of deterministic confidence"
        )

    return content.model_copy(
        update={
            "evidence": grounded,
            "severity_analysis": content.severity_analysis.model_copy(
                update={"assessed_severity": assessed_severity}
            ),
            "confidence_analysis": content.confidence_analysis.model_copy(
                update={
                    "assessed_confidence": round(assessed_confidence, 3),
                    "validation_warnings": warnings,
                }
            ),
            "manufacturer_guidance": manufacturer_guidance,
            "cited_sources": cited_sources,
            "citations": citations,
            "manufacturer_evidence": manufacturer_evidence,
        }
    )


def _validate_manufacturer(
    content: DiagnosisContent,
    state: AgentState,
    warnings: list[str],
) -> tuple[str, list[Any], list[int], list[Any]]:
    """Validate manufacturer guidance, enforcing citation integrity.

    Negative-grounding gate: when the RAG tool retrieved no evidence, no
    manufacturer claim may survive validation. When evidence exists, citations
    are rebuilt app-side from the model's source references and any synthesized
    guidance without a grounded citation is dropped.
    """
    from app.agent.citations import build_citations_from_sources
    from app.rag.config import get_rag_settings

    mg = state.get("manufacturer_guidance") or {}
    evidence = (mg.get("evidence") or []) if isinstance(mg.get("evidence"), list) else []
    rag_available = bool(mg.get("available")) and bool(evidence)

    citations: list[Any] = []
    cited_sources: list[int]
    manufacturer_evidence: list[Any] = []

    if not rag_available:
        if content.manufacturer_guidance or content.cited_sources:
            warnings.append("manufacturer guidance dropped: no RAG evidence was retrieved")
        return "", [], [], []

    citations, cite_warnings = build_citations_from_sources(content.cited_sources, evidence)
    warnings.extend(cite_warnings)

    indexes = {item.get("index") for item in evidence}
    cited_sources = list(dict.fromkeys(r for r in content.cited_sources if r in indexes))

    if content.manufacturer_guidance and not citations:
        warnings.append("manufacturer guidance dropped: no grounded citation was supplied")
        manufacturer_guidance = ""
    else:
        manufacturer_guidance = content.manufacturer_guidance

    max_chars = get_rag_settings().rag_evidence_max_chars
    manufacturer_evidence = [_to_manufacturer_evidence(item, max_chars) for item in evidence]
    return manufacturer_guidance, citations, cited_sources, manufacturer_evidence


def _to_manufacturer_evidence(item: dict[str, Any], max_chars: int) -> Any:
    from app.agent.schemas import ManufacturerEvidence

    content = item.get("content") or ""
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "…"
    return ManufacturerEvidence(
        index=item.get("index") or 0,
        source_filename=item.get("source_filename"),
        title=item.get("title") or "",
        section_title=item.get("section_title") or "",
        page_start=item.get("page_start"),
        page_end=item.get("page_end"),
        scope=item.get("scope"),
        dense_score=item.get("dense_score"),
        lexical_score=item.get("lexical_score"),
        hybrid_score=item.get("hybrid_score"),
        rerank_score=item.get("rerank_score"),
        excerpt=content,
    )


def _normalize_literals(payload: dict[str, Any]) -> dict[str, Any]:
    """Lowercase literal fields that the model may have echoed in mixed case."""
    normalized = dict(payload)
    for cause in normalized.get("possible_causes") or []:
        if isinstance(cause, dict) and isinstance(cause.get("likelihood"), str):
            cause["likelihood"] = cause["likelihood"].lower()
    for action in normalized.get("recommended_actions") or []:
        if isinstance(action, dict):
            if isinstance(action.get("priority"), str):
                action["priority"] = action["priority"].lower()
            if isinstance(action.get("category"), str):
                action["category"] = action["category"].lower()
    for item in normalized.get("evidence") or []:
        if isinstance(item, dict) and isinstance(item.get("severity"), str):
            item["severity"] = item["severity"].lower()

    severity_analysis = normalized.get("severity_analysis")
    if isinstance(severity_analysis, dict):
        for key in ("assessed_severity", "rule_severity"):
            if isinstance(severity_analysis.get(key), str):
                severity_analysis[key] = severity_analysis[key].lower()

    confidence_analysis = normalized.get("confidence_analysis")
    if isinstance(confidence_analysis, dict):
        for key in ("score_quality", "data_quality"):
            if isinstance(confidence_analysis.get(key), str):
                confidence_analysis[key] = confidence_analysis[key].lower()
    return normalized


def _execution_metadata(state: AgentState) -> dict[str, Any]:
    meta = state.get("execution_metadata") or {}
    return {
        "latency_ms": float(meta.get("latency_ms") or 0.0),
        "provider": meta.get("provider") or "",
        "model": meta.get("model") or "",
        "fallback_used": bool(meta.get("fallback_used")),
        "fallback_reason": meta.get("fallback_reason"),
        "input_tokens": int(meta.get("input_tokens") or 0),
        "output_tokens": int(meta.get("output_tokens") or 0),
        "attempts": int(meta.get("attempts") or 0),
        "rule_ids": list(meta.get("rule_ids") or []),
        "rag_used": bool(meta.get("rag_used")),
        "rag_evidence_count": int(meta.get("rag_evidence_count") or 0),
        "rag_embedding_model": meta.get("rag_embedding_model"),
        "rag_reranker_model": meta.get("rag_reranker_model"),
        "rag_scope": (meta.get("rag_scope") or {})
        if isinstance(meta.get("rag_scope"), dict)
        else {},
        "rag_reason": meta.get("rag_reason") or "",
    }


def _context_from_state(state: AgentState):
    raw = state.get("vehicle_context")
    if not raw:
        return None
    from app.intelligence.models import HealthContext

    try:
        return HealthContext.model_validate(raw)
    except ValidationError:
        return None


def _trigger_value(state: AgentState) -> str:
    trigger = state.get("trigger_type")
    return trigger.value if isinstance(trigger, TriggerType) else str(trigger or "")


def _guidance_payload(result) -> dict[str, Any]:
    """Shape the tool result into a JSON-serializable agent-state payload."""
    scope = getattr(result, "scope", None)
    return {
        "vehicle_id": str(getattr(result, "vehicle_id", "")),
        "scope": scope.model_dump(mode="json") if scope is not None else None,
        "guidance": getattr(result, "guidance", "") or "",
        "citations": [c.model_dump(mode="json") for c in getattr(result, "citations", []) or []],
        "evidence": getattr(result, "evidence", []) or [],
        "available": bool(getattr(result, "available", False)),
        "reason": getattr(result, "reason", "") or "",
        "metrics": getattr(result, "metrics", None) or {},
    }


def _canned_reasoning() -> dict[str, Any]:
    """Fully grounded reasoning used when no context exists (NO LLM call)."""
    context_note = (
        "No Vehicle Health Context is available yet, so no data-driven diagnosis can be provided."
    )
    return {
        "summary": context_note,
        "possible_causes": [],
        "recommended_actions": [
            {
                "action": "Generate a health analysis for this vehicle first",
                "priority": "high",
                "category": "inspection",
            }
        ],
        "evidence": [],
        "severity_analysis": {
            "assessed_severity": "info",
            "rule_severity": "info",
            "rationale": "No health data available.",
        },
        "confidence_analysis": {
            "assessed_confidence": 0.0,
            "deterministic_confidence": 0.0,
            "score_quality": "low",
            "data_quality": "low",
            "rationale": "No health data available.",
            "validation_warnings": [],
        },
        "context_note": context_note,
    }
