"""Per-process coordination for the manual analysis trigger (Phase A).

``POST /vehicles/{id}/health/analyze`` runs two wide telemetry range scans plus
a full deterministic analysis and writes one snapshot per call. Two problems
show up under load:

* a client can fire the same request repeatedly and each call pays the full
  cost (write amplification across snapshots and telemetry reads);
* two *identical* requests that overlap in time do duplicate work and write
  near-identical snapshots.

This module adds a small asyncio-safe coordinator. Requests are keyed by the
caller and their query parameters; the first ("leader") runs the analysis while
any concurrent caller with the same key ("follower") awaits the leader's
outcome and receives the same value (or the same exception). A caller that
arrives after the leader has finished starts a fresh run, so distinct requests
are never merged and a report is never silently served from a stale cache.

The coordinator is process-local, matching the platform's documented
single-worker deployment. Behind multiple workers each process would coalesce
its own callers only (a documented limitation, not a silent fallback).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class AnalysisCoordinator:
    """Coalesce *identical, concurrent* analyses within one process."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._inflight: dict[object, asyncio.Future[tuple[bool, object]]] = {}
        self._waiters: dict[object, int] = {}

    @property
    def inflight_count(self) -> int:
        """Number of analyses currently running (leaders)."""
        return len(self._inflight)

    @property
    def waiter_count(self) -> int:
        """Number of callers currently awaiting a leader's result."""
        return sum(self._waiters.values())

    def reset(self) -> None:
        """Forget all in-flight registrations (used by tests)."""
        self._inflight.clear()
        self._waiters.clear()

    async def run(self, key: object, factory: Callable[[], Awaitable[T]]) -> T:
        """Run ``factory`` once, coalescing concurrent calls that share ``key``.

        The leader awaits ``factory``; any concurrent caller with the same key
        awaits the leader's outcome and receives the same value (or the same
        exception). A caller arriving after the leader finishes starts a fresh
        run, so distinct requests are never merged.
        """
        loop = asyncio.get_running_loop()
        async with self._lock:
            existing = self._inflight.get(key)
            if existing is None:
                future: asyncio.Future[tuple[bool, object]] = loop.create_future()
                self._inflight[key] = future
                leader = True
            else:
                future = existing
                leader = False

        if not leader:
            async with self._lock:
                self._waiters[key] = self._waiters.get(key, 0) + 1
            try:
                ok, payload = await asyncio.shield(future)
            finally:
                async with self._lock:
                    remaining = self._waiters.get(key, 1) - 1
                    if remaining > 0:
                        self._waiters[key] = remaining
                    else:
                        self._waiters.pop(key, None)
            if not ok:
                # Re-raise the leader's exact failure (e.g. a 404) so followers
                # observe the same outcome instead of a fabricated success.
                raise payload  # type: ignore[misc]
            return payload  # type: ignore[return-value]

        try:
            result = await factory()
        except BaseException as exc:  # noqa: BLE001 - propagate the same failure
            self._inflight.pop(key, None)
            if not future.done():
                future.set_result((False, exc))
            raise
        else:
            self._inflight.pop(key, None)
            if not future.done():
                future.set_result((True, result))
            return result
