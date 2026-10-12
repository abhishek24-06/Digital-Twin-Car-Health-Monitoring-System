"""Tests for durable workflow-event persistence (P2-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.workflow_event_repository import WorkflowEventRepository
from app.schemas.workflow import (
    WorkflowEvent,
    WorkflowStage,
    WorkflowStatus,
    WorkflowType,
)
from app.services.workflow_event_persistence import WorkflowEventPersister


def _event(**kwargs) -> WorkflowEvent:
    base = dict(
        workflow=WorkflowType.SIMULATION,
        stage=WorkflowStage.SIMULATION_STARTED,
        status=WorkflowStatus.SUCCESS,
        message="m",
    )
    base.update(kwargs)
    return WorkflowEvent(**base)


async def test_persist_stores_events(
    clean_db, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    persister = WorkflowEventPersister(session_factory, retention_hours=72)

    inserted = await persister.persist([_event(message="a"), _event(message="b")])

    assert inserted == 2
    async with session_factory() as session:
        assert await WorkflowEventRepository(session).count() == 2


async def test_persist_is_idempotent_on_event_id(
    clean_db, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event = _event(message="once")
    persister = WorkflowEventPersister(session_factory, retention_hours=72)

    assert await persister.persist([event]) == 1
    # Re-persisting the same event_id is a no-op, never a duplicate.
    assert await persister.persist([event]) == 0

    async with session_factory() as session:
        assert await WorkflowEventRepository(session).count() == 1


async def test_persist_sanitizes_metadata(
    clean_db, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    persister = WorkflowEventPersister(session_factory, retention_hours=72)
    await persister.persist([_event(metadata={"password": "hunter2", "note": "keep"})])

    async with session_factory() as session:
        rows, total = await WorkflowEventRepository(session).list_recent(limit=10, offset=0)

    assert total == 1
    assert rows[0].metadata_json == {"password": "[REDACTED]", "note": "keep"}


async def test_persist_prunes_events_older_than_retention(
    clean_db, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # prune_interval_seconds=0 forces a prune on the next flush.
    persister = WorkflowEventPersister(session_factory, retention_hours=1, prune_interval_seconds=0)
    old = _event(message="old", timestamp=datetime.now(UTC) - timedelta(hours=5))

    await persister.persist([old])
    await persister.persist([_event(message="fresh")])

    async with session_factory() as session:
        rows, total = await WorkflowEventRepository(session).list_recent(limit=10, offset=0)

    assert total == 1
    assert rows[0].message == "fresh"


async def test_persist_swallows_store_failure() -> None:
    """A persistence failure must never surface to the caller."""

    class _BrokenFactory:
        def __call__(self):
            raise RuntimeError("database unavailable")

    persister = WorkflowEventPersister(_BrokenFactory(), retention_hours=72)  # type: ignore[arg-type]

    assert await persister.persist([_event()]) == 0


async def test_persist_ignores_empty_batch(
    clean_db, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    persister = WorkflowEventPersister(session_factory, retention_hours=72)
    assert await persister.persist([]) == 0
