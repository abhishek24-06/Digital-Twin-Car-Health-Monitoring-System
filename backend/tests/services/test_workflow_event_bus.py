"""Tests for the workflow event bus."""

from __future__ import annotations

import asyncio

import pytest

from app.schemas.workflow import (
    WorkflowEvent,
    WorkflowStage,
    WorkflowStatus,
    WorkflowType,
)
from app.services.workflow_event_bus import WorkflowEventBus, get_workflow_event_bus


@pytest.fixture
def event_bus():
    """Fresh event bus for each test."""
    bus = WorkflowEventBus(capacity=100, max_subscribers=10)
    yield bus
    asyncio.run(bus.close())


@pytest.fixture
def sample_event() -> WorkflowEvent:
    return WorkflowEvent(
        workflow=WorkflowType.TELEMETRY,
        stage=WorkflowStage.TELEMETRY_GENERATED,
        status=WorkflowStatus.SUCCESS,
        message="Telemetry generated",
        vehicle_id="12345678-1234-5678-1234-567812345678",
        metadata={"signals": 12},
    )


async def test_publish_and_get_recent(event_bus: WorkflowEventBus, sample_event: WorkflowEvent):
    """Publishing adds events to the buffer."""
    await event_bus.publish(sample_event)
    events = await event_bus.get_recent(limit=10)
    assert len(events) == 1
    assert events[0].event_id == sample_event.event_id


async def test_ring_buffer_capacity(event_bus: WorkflowEventBus):
    """Buffer respects capacity limit (oldest events dropped)."""
    for i in range(150):
        await event_bus.publish(
            WorkflowEvent(
                workflow=WorkflowType.TELEMETRY,
                stage=WorkflowStage.TELEMETRY_GENERATED,
                status=WorkflowStatus.SUCCESS,
                message=f"Event {i}",
            )
        )
    events = await event_bus.get_recent(limit=200)
    # Should only have 100 (capacity)
    assert len(events) == 100
    # Newest events should be present
    assert events[0].message == "Event 149"
    assert events[-1].message == "Event 50"


async def test_get_recent_with_offset(event_bus: WorkflowEventBus, sample_event: WorkflowEvent):
    """Offset parameter skips newest events."""
    await event_bus.publish(sample_event)
    await event_bus.publish(
        WorkflowEvent(
            workflow=WorkflowType.TELEMETRY,
            stage=WorkflowStage.TELEMETRY_GENERATED,
            status=WorkflowStatus.SUCCESS,
            message="Second",
        )
    )
    # Offset 1 should skip the newest
    events = await event_bus.get_recent(limit=10, offset=1)
    assert len(events) == 1
    assert events[0].message == "Telemetry generated"


async def test_subscribe_receives_events(event_bus: WorkflowEventBus, sample_event: WorkflowEvent):
    """Subscribers receive published events."""
    sub_id, queue = await event_bus.subscribe()
    try:
        await event_bus.publish(sample_event)
        received = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert received.event_id == sample_event.event_id
    finally:
        await event_bus.unsubscribe(sub_id)


async def test_subscribe_multiple_subscribers(
    event_bus: WorkflowEventBus, sample_event: WorkflowEvent
):
    """Multiple subscribers all receive events."""
    sub1_id, q1 = await event_bus.subscribe()
    sub2_id, q2 = await event_bus.subscribe()
    try:
        await event_bus.publish(sample_event)
        e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert e1.event_id == sample_event.event_id
        assert e2.event_id == sample_event.event_id
    finally:
        await event_bus.unsubscribe(sub1_id)
        await event_bus.unsubscribe(sub2_id)


async def test_subscriber_cleanup_on_disconnect(event_bus: WorkflowEventBus):
    """Unsubscribing removes subscriber from bus."""
    sub_id, _ = await event_bus.subscribe()
    assert event_bus.subscriber_count == 1
    await event_bus.unsubscribe(sub_id)
    assert event_bus.subscriber_count == 0


async def test_max_subscribers_limit(event_bus: WorkflowEventBus):
    """Bus enforces max subscriber limit."""
    subs = []
    for _ in range(10):  # max_subscribers=10
        sub_id, _ = await event_bus.subscribe()
        subs.append(sub_id)
    assert event_bus.subscriber_count == 10

    with pytest.raises(RuntimeError, match="Max subscribers"):
        await event_bus.subscribe()

    for sub_id in subs:
        await event_bus.unsubscribe(sub_id)


async def test_clear_buffer(event_bus: WorkflowEventBus, sample_event: WorkflowEvent):
    """Clear removes all events (frontend 'clear view')."""
    await event_bus.publish(sample_event)
    await event_bus.clear()
    events = await event_bus.get_recent(limit=10)
    assert len(events) == 0


async def test_close_shuts_down_subscribers(event_bus: WorkflowEventBus):
    """Closing sends shutdown sentinel to all subscribers."""
    sub_id, queue = await event_bus.subscribe()
    await event_bus.close()
    # Should receive None sentinel
    sentinel = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert sentinel is None


async def test_publish_after_close_noop(event_bus: WorkflowEventBus, sample_event: WorkflowEvent):
    """Publishing after close is a no-op."""
    await event_bus.close()
    await event_bus.publish(sample_event)  # Should not raise
    events = await event_bus.get_recent(limit=10)
    assert len(events) == 0


async def test_get_status(event_bus: WorkflowEventBus, sample_event: WorkflowEvent):
    """Status returns buffer info."""
    await event_bus.publish(sample_event)
    status = await event_bus.get_status()
    assert status["events_in_buffer"] == 1
    assert status["oldest_event_ts"] is not None
    assert status["newest_event_ts"] is not None


async def test_empty_status(event_bus: WorkflowEventBus):
    """Status on empty buffer."""
    status = await event_bus.get_status()
    assert status["events_in_buffer"] == 0
    assert status["oldest_event_ts"] is None
    assert status["newest_event_ts"] is None


async def test_global_bus_singleton():
    """get_workflow_event_bus returns same instance."""
    bus1 = get_workflow_event_bus()
    bus2 = get_workflow_event_bus()
    assert bus1 is bus2
    await bus1.close()


async def test_concurrent_publish_subscribe(event_bus: WorkflowEventBus):
    """Concurrent publish and subscribe work correctly."""

    async def publisher():
        for i in range(20):
            await event_bus.publish(
                WorkflowEvent(
                    workflow=WorkflowType.TELEMETRY,
                    stage=WorkflowStage.TELEMETRY_GENERATED,
                    status=WorkflowStatus.SUCCESS,
                    message=f"Event {i}",
                )
            )
            await asyncio.sleep(0.001)

    async def subscriber():
        sub_id, queue = await event_bus.subscribe()
        count = 0
        try:
            while count < 20:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
                if event is None:
                    break
                count += 1
        finally:
            await event_bus.unsubscribe(sub_id)
        return count

    sub_task = asyncio.create_task(subscriber())
    await asyncio.sleep(0.01)  # Let subscriber start
    await publisher()
    received = await sub_task
    # Should receive all 20
    assert received == 20
