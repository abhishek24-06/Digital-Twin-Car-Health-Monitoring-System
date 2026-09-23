from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.triggers import TriggerType
from app.models.agent_diagnosis import AgentDiagnosis


class AgentDiagnosisRepository:
    """Data access for persisted agent diagnoses (persistence only)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, diagnosis: AgentDiagnosis) -> AgentDiagnosis:
        self._session.add(diagnosis)
        await self._session.flush()
        await self._session.refresh(diagnosis)
        return diagnosis

    async def get_by_id(self, diagnosis_id: UUID) -> AgentDiagnosis | None:
        statement = select(AgentDiagnosis).where(AgentDiagnosis.id == diagnosis_id)
        return await self._session.scalar(statement)

    async def get_latest_by_vehicle(
        self,
        vehicle_id: UUID,
        *,
        trigger_type: TriggerType | str | None = None,
        status: str | None = None,
    ) -> AgentDiagnosis | None:
        filters = [AgentDiagnosis.vehicle_id == vehicle_id]
        if trigger_type is not None:
            filters.append(AgentDiagnosis.trigger_type == _trigger_string(trigger_type))
        if status is not None:
            filters.append(AgentDiagnosis.status == status)
        statement = (
            select(AgentDiagnosis)
            .where(*filters)
            .order_by(AgentDiagnosis.created_at.desc(), AgentDiagnosis.id.desc())
            .limit(1)
        )
        return await self._session.scalar(statement)

    async def list_by_vehicle(
        self,
        vehicle_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[AgentDiagnosis], int]:
        filters = [AgentDiagnosis.vehicle_id == vehicle_id]
        total = await self._session.scalar(
            select(func.count()).select_from(AgentDiagnosis).where(*filters)
        )
        statement = (
            select(AgentDiagnosis)
            .where(*filters)
            .order_by(AgentDiagnosis.created_at.desc(), AgentDiagnosis.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.scalars(statement)
        return list(result.all()), int(total or 0)


def _trigger_string(trigger: TriggerType | str) -> str:
    return trigger.value if isinstance(trigger, TriggerType) else trigger
