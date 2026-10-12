from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow_event import WorkflowEventRecord
from app.schemas.workflow import WorkflowEvent, WorkflowType, sanitize_metadata


class WorkflowEventRepository:
    """Data access for the durable workflow-event audit store."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_many(self, events: Sequence[WorkflowEvent]) -> int:
        """Persist events, ignoring duplicates by ``event_id``.

        Returns the number of rows actually inserted. Metadata is sanitized
        again on the way in (defence in depth: the bus already sanitizes at the
        source, but the durable store must never hold a secret).
        """
        if not events:
            return 0
        rows = [
            {
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "workflow": event.workflow.value,
                "stage": event.stage.value,
                "status": event.status.value,
                "message": event.message,
                "vehicle_id": event.vehicle_id,
                "document_id": event.document_id,
                "correlation_id": event.correlation_id,
                "duration_ms": event.duration_ms,
                "metadata": sanitize_metadata(event.metadata),
            }
            for event in events
        ]
        statement = (
            pg_insert(WorkflowEventRecord.__table__)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        result = await self._session.execute(statement)
        return result.rowcount or 0

    async def prune_before(self, cutoff: datetime) -> int:
        """Delete events older than ``cutoff``; returns the rows removed."""
        result = await self._session.execute(
            delete(WorkflowEventRecord).where(WorkflowEventRecord.timestamp < cutoff)
        )
        return result.rowcount or 0

    async def count(self) -> int:
        """Total number of retained events."""
        total = await self._session.scalar(select(func.count()).select_from(WorkflowEventRecord))
        return int(total or 0)

    async def list_recent(
        self,
        *,
        workflow: str | None = None,
        stage: str | None = None,
        status: str | None = None,
        vehicle_id: UUID | None = None,
        document_id: UUID | None = None,
        correlation_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        owned_vehicle_ids: set[UUID] | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[WorkflowEventRecord], int]:
        """Filtered, newest-first page of persisted events.

        ``owned_vehicle_ids`` mirrors the live-buffer visibility rule: ``None``
        means an unrestricted admin; otherwise only global events and events for
        the given vehicles are returned, and ``rag_ingestion`` is never exposed.
        """
        filters = []
        if workflow is not None:
            filters.append(WorkflowEventRecord.workflow == workflow)
        if stage is not None:
            filters.append(WorkflowEventRecord.stage == stage)
        if status is not None:
            filters.append(WorkflowEventRecord.status == status)
        if vehicle_id is not None:
            filters.append(WorkflowEventRecord.vehicle_id == vehicle_id)
        if document_id is not None:
            filters.append(WorkflowEventRecord.document_id == document_id)
        if correlation_id is not None:
            filters.append(WorkflowEventRecord.correlation_id == correlation_id)
        if since is not None:
            filters.append(WorkflowEventRecord.timestamp >= since)
        if until is not None:
            filters.append(WorkflowEventRecord.timestamp <= until)
        if owned_vehicle_ids is not None:
            filters.append(
                or_(
                    WorkflowEventRecord.vehicle_id.is_(None),
                    WorkflowEventRecord.vehicle_id.in_(owned_vehicle_ids),
                )
            )
            filters.append(WorkflowEventRecord.workflow != WorkflowType.RAG_INGESTION.value)

        total = int(
            await self._session.scalar(
                select(func.count()).select_from(WorkflowEventRecord).where(*filters)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(WorkflowEventRecord)
            .where(*filters)
            .order_by(WorkflowEventRecord.timestamp.desc(), WorkflowEventRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows.all()), total
