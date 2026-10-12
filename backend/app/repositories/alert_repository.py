from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import ALERT_ACTIVE_STATUSES, Alert, AlertEvent


class AlertRepository:
    """Data access for persistent alerts and their audit history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, alert: Alert) -> Alert:
        self._session.add(alert)
        await self._session.flush()
        await self._session.refresh(alert)
        return alert

    async def get_by_id(self, alert_id: UUID) -> Alert | None:
        statement = select(Alert).where(Alert.id == alert_id)
        return await self._session.scalar(statement)

    async def get_active_by_dedup_key(self, vehicle_id: UUID, dedup_key: str) -> Alert | None:
        statement = (
            select(Alert)
            .where(
                Alert.vehicle_id == vehicle_id,
                Alert.dedup_key == dedup_key,
                Alert.status.in_(ALERT_ACTIVE_STATUSES),
            )
            .order_by(Alert.last_seen_at.desc(), Alert.id.desc())
            .limit(1)
        )
        return await self._session.scalar(statement)

    async def list_active_by_vehicle(self, vehicle_id: UUID) -> list[Alert]:
        statement = select(Alert).where(
            Alert.vehicle_id == vehicle_id,
            Alert.status.in_(ALERT_ACTIVE_STATUSES),
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def list_by_vehicle(
        self,
        vehicle_id: UUID,
        *,
        statuses: list[str] | None = None,
        severity: str | None = None,
        page: int,
        page_size: int,
    ) -> tuple[list[Alert], int]:
        filters = [Alert.vehicle_id == vehicle_id]
        if statuses:
            filters.append(Alert.status.in_(statuses))
        if severity is not None:
            filters.append(Alert.severity == severity)

        total = await self._session.scalar(select(func.count()).select_from(Alert).where(*filters))

        # Most severe first (critical, then warning), newest observation
        # breaking ties, so an operator sees the actionable alerts at the top.
        severity_rank = case(
            (Alert.severity == "critical", 0),
            (Alert.severity == "warning", 1),
            else_=2,
        )
        statement = (
            select(Alert)
            .where(*filters)
            .order_by(severity_rank, Alert.last_seen_at.desc(), Alert.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.scalars(statement)
        return list(result.all()), int(total or 0)

    async def add_event(self, event: AlertEvent) -> AlertEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_events(self, alert_id: UUID) -> list[AlertEvent]:
        statement = (
            select(AlertEvent)
            .where(AlertEvent.alert_id == alert_id)
            .order_by(AlertEvent.created_at.asc(), AlertEvent.id.asc())
        )
        result = await self._session.scalars(statement)
        return list(result.all())
