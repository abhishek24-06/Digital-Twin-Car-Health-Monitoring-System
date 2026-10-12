"""Durable, bounded persistence for workflow observability events.

The process-local :class:`~app.services.workflow_event_bus.WorkflowEventBus` is
the real-time feed; this module adds a restart-surviving audit copy so an
incident can be reviewed after the fact. It is deliberately best-effort: a
persistence failure is logged and swallowed so observability can never affect a
business operation, and retention is enforced so the store stays bounded.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.workflow_event_repository import WorkflowEventRepository
from app.schemas.workflow import WorkflowEvent

logger = logging.getLogger(__name__)


class WorkflowEventPersister:
    """Best-effort, retention-bounded persistence of workflow events.

    Never raises into the caller. Events older than ``retention_hours`` are
    pruned; pruning is rate-limited so a DELETE does not run on every flush.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retention_hours: float,
        prune_interval_seconds: float | None = None,
    ) -> None:
        if retention_hours <= 0:
            raise ValueError("retention_hours must be positive")
        self._session_factory = session_factory
        self._retention = timedelta(hours=retention_hours)
        # Prune a few times per retention window, but never more than once a
        # minute.
        self._prune_interval = (
            prune_interval_seconds
            if prune_interval_seconds is not None
            else max(60.0, retention_hours * 3600.0 / 4.0)
        )
        self._last_prune: float | None = None

    async def persist(self, events: Sequence[WorkflowEvent]) -> int:
        """Insert events and opportunistically prune old ones.

        Returns the number of rows inserted. Failures are logged, never raised.
        """
        if not events:
            return 0
        inserted = 0
        try:
            async with self._session_factory() as session:
                repository = WorkflowEventRepository(session)
                inserted = await repository.insert_many(events)
                if self._should_prune():
                    cutoff = datetime.now(UTC) - self._retention
                    deleted = await repository.prune_before(cutoff)
                    if deleted:
                        logger.info(
                            "pruned %s workflow event(s) older than %s",
                            deleted,
                            cutoff,
                        )
                await session.commit()
        except Exception:  # noqa: BLE001 - observability must never break callers
            logger.warning(
                "workflow event persistence failed (observability only)",
                exc_info=True,
            )
        return inserted

    def _should_prune(self) -> bool:
        now = time.monotonic()
        if self._last_prune is not None and (now - self._last_prune) < self._prune_interval:
            return False
        self._last_prune = now
        return True
