"""Unit tests for the Phase A concurrent-analysis coordinator.

The coordinator coalesces *identical, concurrent* analyses and never merges
requests that differ in key or arrive sequentially.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.analysis_coordinator import AnalysisCoordinator


async def test_identical_concurrent_requests_run_once() -> None:
    coord = AnalysisCoordinator()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "report"

    leader = asyncio.create_task(coord.run("k", factory))
    await started.wait()

    follower = asyncio.create_task(coord.run("k", factory))
    # Let the follower reach the coordinator and register as a waiter.
    await asyncio.sleep(0)

    assert coord.inflight_count == 1
    release.set()

    results = await asyncio.gather(leader, follower)
    assert results == ["report", "report"]
    assert calls == 1
    assert coord.inflight_count == 0


async def test_distinct_keys_run_independently() -> None:
    coord = AnalysisCoordinator()
    calls: list[str] = []

    def factory(name: str):
        async def _run() -> str:
            calls.append(name)
            await asyncio.sleep(0.01)
            return name

        return _run

    a, b = await asyncio.gather(
        coord.run("a", factory("a")),
        coord.run("b", factory("b")),
    )
    assert {a, b} == {"a", "b"}
    assert sorted(calls) == ["a", "b"]


async def test_sequential_requests_are_not_coalesced() -> None:
    coord = AnalysisCoordinator()
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        return calls

    first = await coord.run("k", factory)
    second = await coord.run("k", factory)
    assert (first, second) == (1, 2)
    assert calls == 2


async def test_leader_failure_propagates_to_followers_and_clears_state() -> None:
    coord = AnalysisCoordinator()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def failing() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        raise ValueError("no such vehicle")

    leader = asyncio.create_task(coord.run("k", failing))
    await started.wait()
    follower = asyncio.create_task(coord.run("k", failing))
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(ValueError, match="no such vehicle"):
        await leader
    with pytest.raises(ValueError, match="no such vehicle"):
        await follower
    assert calls == 1
    assert coord.inflight_count == 0

    # A later request is unaffected by the failed one.
    async def ok() -> str:
        return "report"

    assert await coord.run("k", ok) == "report"


async def test_leader_cancellation_releases_followers_and_state() -> None:
    """A cancelled leader must not strand followers or leak in-flight state."""
    coord = AnalysisCoordinator()
    started = asyncio.Event()

    async def never_returns() -> str:
        started.set()
        await asyncio.Event().wait()  # only a cancellation can end this
        return "unreachable"

    leader = asyncio.create_task(coord.run("k", never_returns))
    await started.wait()
    follower = asyncio.create_task(coord.run("k", never_returns))
    await asyncio.sleep(0)
    assert coord.inflight_count == 1

    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    # The follower observes the leader's cancellation rather than hanging.
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(follower, timeout=2.0)

    assert coord.inflight_count == 0
    assert coord.waiter_count == 0

    async def ok() -> str:
        return "report"

    # The cancelled leader must not poison the key for later callers.
    assert await coord.run("k", ok) == "report"
    assert coord.inflight_count == 0


async def test_many_concurrent_identical_requests_never_hang() -> None:
    coord = AnalysisCoordinator()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return calls

    leader = asyncio.create_task(coord.run("k", factory))
    await started.wait()
    followers = [asyncio.create_task(coord.run("k", factory)) for _ in range(20)]
    await asyncio.sleep(0)

    release.set()
    results = await asyncio.gather(leader, *followers)
    assert results == [1] * 21
    assert calls == 1
    assert coord.inflight_count == 0
    assert coord.waiter_count == 0


async def test_follower_cancellation_does_not_cancel_leader() -> None:
    coord = AnalysisCoordinator()
    started = asyncio.Event()
    release = asyncio.Event()

    async def factory() -> str:
        started.set()
        await release.wait()
        return "report"

    leader = asyncio.create_task(coord.run("k", factory))
    await started.wait()
    follower = asyncio.create_task(coord.run("k", factory))
    await asyncio.sleep(0)

    follower.cancel()
    with pytest.raises(asyncio.CancelledError):
        await follower

    release.set()
    assert await leader == "report"
    assert coord.inflight_count == 0
