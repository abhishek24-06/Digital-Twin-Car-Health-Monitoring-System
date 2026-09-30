"""AgentService — orchestration above the LangGraph workflow (Phase 4).

Public operations: natural-language user queries, critical telemetry event
diagnosis (with cooldown deduplication), the no-LLM dashboard hook, and
diagnosis history/latest lookups.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.config import AgentSettings, get_agent_settings
from app.agent.errors import GraphExecutionError
from app.agent.graph import build_agent_graph
from app.agent.grounding import critical_rule_ids
from app.agent.llm_service import LLMService
from app.agent.schemas import DiagnosisResponse
from app.agent.state import AgentState
from app.agent.tools.manufacturer_guidance import ManufacturerGuidanceTool
from app.agent.tools.vehicle_context import VehicleContextTool
from app.agent.triggers import TriggerType
from app.models.agent_diagnosis import AgentDiagnosis
from app.models.user import User
from app.rag.config import get_rag_settings
from app.rag.rag_service import RAGService
from app.repositories.agent_diagnosis_repository import AgentDiagnosisRepository
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.vehicle_access import ensure_vehicle_access
from app.services.vehicle_health_service import VehicleHealthService

logger = logging.getLogger(__name__)


class AgentService:
    """Public agent operations for the Phase 4 reasoning layer."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: AgentSettings | None = None,
        llm_service: LLMService | None = None,
        rag_service: RAGService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_agent_settings()
        self._llm_service = llm_service or LLMService(self._settings)
        self._diagnosis_repository = AgentDiagnosisRepository(session)
        self._vehicle_repository = VehicleRepository(session)
        self._vehicle_health_service = VehicleHealthService(
            session=session,
            vehicle_repository=self._vehicle_repository,
            telemetry_repository=TelemetryRepository(session),
            health_repository=HealthSnapshotRepository(session),
        )
        self._tool = VehicleContextTool(self._vehicle_health_service, self._settings)

        # RAG integration (Phase 5): the Manufacturer Guidance Tool is built only
        # when RAG is enabled — either by construction override or configuration.
        # Building a RAGService never loads models (lazy); retrieval is the first
        # and only place model weights are touched.
        self._rag_service = rag_service
        if self._rag_service is None and get_rag_settings().rag_enabled:
            self._rag_service = RAGService()
        self._rag_tool: ManufacturerGuidanceTool | None = None
        if self._rag_service is not None:
            self._rag_tool = ManufacturerGuidanceTool(
                self._rag_service,
                self._vehicle_repository,
                self._settings,
                session,
            )

    async def run_user_query(
        self, vehicle_id: UUID, query: str, *, user: User | None = None
    ) -> DiagnosisResponse:
        """Answer a natural-language question about a vehicle.

        ``user`` scopes the execution: it both enforces ownership below the
        router and is attributed on the persisted diagnosis. Internal callers
        (MQTT/scripts) may pass ``None``; the vehicle is then only checked for
        existence, exactly as in previous phases.
        """
        cleaned = (query or "").strip()
        if not cleaned:
            raise ValueError("query must not be empty")
        if user is not None:
            await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self._run(
            vehicle_id=vehicle_id,
            trigger_type=TriggerType.USER_QUERY,
            user_query=cleaned,
            user_id=user.id if user is not None else None,
        )

    async def run_critical_event(
        self,
        vehicle_id: UUID,
        rule_ids: list[str] | None = None,
        *,
        user: User | None = None,
    ) -> DiagnosisResponse:
        """Diagnose a critical telemetry rule event, de-duplicating repeats."""
        if user is not None:
            await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        candidate_rules = await self._resolve_rule_ids(vehicle_id, rule_ids)
        prior = await self._deduplicated_prior(vehicle_id, candidate_rules)
        if prior is not None:
            return prior

        user_query = (
            "A critical telemetry rule event was detected on this vehicle. "
            "Interpret the Vehicle Health Context and recommend immediate actions."
        )
        return await self._run(
            vehicle_id=vehicle_id,
            trigger_type=TriggerType.CRITICAL_TELEMETRY_EVENT,
            user_query=user_query,
            rule_ids=sorted(candidate_rules),
            user_id=user.id if user is not None else None,
        )

    async def get_dashboard_context(
        self, vehicle_id: UUID, *, user: User | None = None
    ) -> dict[str, Any]:
        """Dashboard hook — reads data only, never calls the LLM."""
        if user is not None:
            await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        snapshot = await self._vehicle_health_service.get_latest(vehicle_id)
        prior = await self._diagnosis_repository.get_latest_by_vehicle(vehicle_id)
        age_seconds: float | None = None
        if prior is not None:
            age_seconds = (datetime.now(UTC) - _as_utc(prior.created_at)).total_seconds()
        return {
            "vehicle_id": vehicle_id,
            "generated_at": datetime.now(UTC),
            "health_context": snapshot.context_json if snapshot is not None else None,
            "latest_diagnosis": prior.diagnosis if prior is not None else None,
            "diagnosis_age_seconds": age_seconds,
        }

    async def list_diagnoses(
        self,
        vehicle_id: UUID,
        *,
        page: int,
        page_size: int,
        user: User | None = None,
    ) -> tuple[list[AgentDiagnosis], int]:
        if user is not None:
            await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self._diagnosis_repository.list_by_vehicle(
            vehicle_id, page=page, page_size=page_size
        )

    async def get_latest_diagnosis(
        self, vehicle_id: UUID, *, user: User | None = None
    ) -> AgentDiagnosis | None:
        if user is not None:
            await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self._diagnosis_repository.get_latest_by_vehicle(vehicle_id)

    async def _run(
        self,
        *,
        vehicle_id: UUID,
        trigger_type: TriggerType,
        user_query: str,
        rule_ids: list[str] | None = None,
        user_id=None,
    ) -> DiagnosisResponse:
        state: AgentState = {
            "agent_run_id": str(uuid4()),
            "vehicle_id": vehicle_id,
            "trigger_type": trigger_type,
            "user_query": user_query,
            "execution_metadata": {"rule_ids": rule_ids or []},
            "user_id": user_id,
        }
        graph = build_agent_graph(
            tool=self._tool,
            llm_service=self._llm_service,
            repository=self._diagnosis_repository,
            session=self._session,
            rag_tool=self._rag_tool,
        )
        result = await graph.ainvoke(state)
        final = result.get("final_response")
        if final is None:
            raise GraphExecutionError("Agent workflow produced no response")
        return DiagnosisResponse.model_validate(final)

    async def _resolve_rule_ids(self, vehicle_id: UUID, rule_ids: list[str] | None) -> list[str]:
        if rule_ids:
            return list(dict.fromkeys(rule_ids))
        result = await self._tool.get_context(vehicle_id)
        return critical_rule_ids(result.context)

    async def _deduplicated_prior(
        self, vehicle_id: UUID, candidate_rules: list[str]
    ) -> DiagnosisResponse | None:
        prior = await self._diagnosis_repository.get_latest_by_vehicle(
            vehicle_id,
            trigger_type=TriggerType.CRITICAL_TELEMETRY_EVENT,
            status="completed",
        )
        if prior is None:
            return None
        age = (datetime.now(UTC) - _as_utc(prior.created_at)).total_seconds()
        if age > self._settings.agent_critical_event_cooldown_seconds:
            return None

        covered = set((prior.diagnosis.get("execution") or {}).get("rule_ids") or [])
        if not covered or not set(candidate_rules).issubset(covered):
            return None

        response = DiagnosisResponse.model_validate(prior.diagnosis)
        execution = response.execution.model_copy(
            update={"deduplicated": True, "rule_ids": sorted(candidate_rules)}
        )
        return response.model_copy(update={"id": prior.id, "execution": execution})


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
