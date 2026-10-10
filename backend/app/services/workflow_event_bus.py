"""Bounded async event bus for workflow observability.

Provides a lightweight in-memory ring buffer with async-safe publish/subscribe.
Failure of the observability stream MUST NOT affect core business operations.

Design:
- Ring buffer with configurable capacity (default 500)
- Non-blocking publish (fire-and-forget)
- Async generator subscription for live SSE streaming
- Bounded memory, no unbounded accumulation
- Thread-safe with asyncio locks
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from app.schemas.workflow import WorkflowEvent, WorkflowStage, WorkflowStatus, WorkflowType

logger = logging.getLogger(__name__)


@dataclass
class _Subscriber:
    """Active subscriber waiting for events."""

    queue: asyncio.Queue[WorkflowEvent]
    created_at: float


class WorkflowEventBus:
    """Bounded in-memory event bus for workflow observability.

    - Capacity limited to prevent unbounded memory growth
    - Non-blocking publish: core operations never await subscribers
    - Subscribers receive events via asyncio.Queue
    - Automatic cleanup of disconnected subscribers
    """

    def __init__(self, *, capacity: int = 500, max_subscribers: int = 50) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if max_subscribers <= 0:
            raise ValueError("max_subscribers must be positive")

        self._capacity = capacity
        self._max_subscribers = max_subscribers
        self._buffer: deque[WorkflowEvent] = deque(maxlen=capacity)
        self._subscribers: dict[int, _Subscriber] = {}
        self._subscriber_counter = 0
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return len(self._buffer)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def is_full(self) -> bool:
        return len(self._buffer) >= self._capacity

    async def publish(self, event: WorkflowEvent) -> None:
        """Publish an event to the bus.

        Non-blocking: adds to ring buffer and notifies subscribers
        without waiting for them to consume. If subscribers are slow,
        they may miss events but core operations continue uninterrupted.
        """
        if self._closed:
            return

        async with self._lock:
            self._buffer.append(event)
            # Notify all current subscribers (non-blocking put_nowait)
            dead_subscribers = []
            for sub_id, subscriber in self._subscribers.items():
                try:
                    subscriber.queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Subscriber too slow - mark for cleanup
                    dead_subscribers.append(sub_id)

            # Clean up dead subscribers
            for sub_id in dead_subscribers:
                self._subscribers.pop(sub_id, None)

    async def subscribe(self) -> tuple[int, asyncio.Queue[WorkflowEvent]]:
        """Create a new subscription.

        Returns (subscriber_id, queue). The caller should consume from
        the queue until it receives None (shutdown signal) or cancels.
        """
        if self._closed:
            raise RuntimeError("Event bus is closed")

        async with self._lock:
            if len(self._subscribers) >= self._max_subscribers:
                raise RuntimeError(f"Max subscribers ({self._max_subscribers}) reached")

            self._subscriber_counter += 1
            sub_id = self._subscriber_counter
            queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue(maxsize=100)
            self._subscribers[sub_id] = _Subscriber(queue=queue, created_at=time.time())
            return sub_id, queue

    async def unsubscribe(self, sub_id: int) -> None:
        """Remove a subscription."""
        async with self._lock:
            self._subscribers.pop(sub_id, None)

    async def get_recent(self, limit: int = 100, offset: int = 0) -> list[WorkflowEvent]:
        """Get recent events, newest first.

        Args:
            limit: Maximum number of events to return
            offset: Number of newest events to skip

        Returns:
            List of events (newest first)
        """
        async with self._lock:
            events = list(self._buffer)
        # Newest first
        events.reverse()
        start = offset
        end = offset + limit
        return events[start:end]

    async def get_status(self) -> dict[str, Any]:
        """Get buffer status for monitoring."""
        async with self._lock:
            events = list(self._buffer)
        if not events:
            return {
                "events_in_buffer": 0,
                "oldest_event_ts": None,
                "newest_event_ts": None,
            }
        return {
            "events_in_buffer": len(events),
            "oldest_event_ts": events[0].timestamp,
            "newest_event_ts": events[-1].timestamp,
        }

    async def clear(self) -> None:
        """Clear the event buffer (frontend 'clear view' only).

        Does NOT affect persisted data (telemetry, health snapshots, etc.).
        """
        async with self._lock:
            self._buffer.clear()

    async def close(self) -> None:
        """Shutdown the bus and notify all subscribers."""
        async with self._lock:
            self._closed = True
            for subscriber in self._subscribers.values():
                try:
                    subscriber.queue.put_nowait(None)  # Shutdown sentinel
                except asyncio.QueueFull:
                    pass
            self._subscribers.clear()
            self._buffer.clear()


# Global event bus instance (process-local)
_EVENT_BUS: WorkflowEventBus | None = None


def get_workflow_event_bus() -> WorkflowEventBus:
    """Get or create the global workflow event bus.

    Used by both instrumentation points and API routes.
    """
    global _EVENT_BUS
    if _EVENT_BUS is None:
        from app.core.config import get_settings

        settings = get_settings()
        _EVENT_BUS = WorkflowEventBus(
            capacity=settings.workflow_event_buffer_size,
            max_subscribers=settings.workflow_max_subscribers,
        )
    return _EVENT_BUS


async def publish_workflow_event(
    workflow: WorkflowType,
    stage: WorkflowStage,
    status: WorkflowStatus,
    message: str,
    *,
    vehicle_id: str | None = None,
    document_id: str | None = None,
    correlation_id: str | None = None,
    duration_ms: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Convenience function to publish a workflow event.

    Fire-and-forget: never blocks the caller. Exceptions are logged
    but never propagated to the caller.
    """
    try:
        bus = get_workflow_event_bus()
        event = WorkflowEvent(
            workflow=workflow,
            stage=stage,
            status=status,
            message=message,
            vehicle_id=vehicle_id,
            document_id=document_id,
            correlation_id=correlation_id,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )
        await bus.publish(event)
    except Exception as exc:  # noqa: BLE001 - observability must not crash core
        logger.debug("Failed to publish workflow event: %s", exc)
