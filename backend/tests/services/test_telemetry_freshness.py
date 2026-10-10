"""Freshness-threshold tests.

The shared helpers are the single source of truth for "how old is too old", so a
drift here silently reintroduces the stale/contradictory UI. These tests pin the
cadence-derived snapshot window deterministically (no wall clock).
"""

from __future__ import annotations

from app.services.telemetry_freshness import (
    STALE_AFTER_SECONDS,
    STARTUP_BUFFER_SECONDS,
    snapshot_stale_after_seconds,
)


def test_telemetry_constants_are_stable() -> None:
    assert STARTUP_BUFFER_SECONDS == 25.0
    assert STALE_AFTER_SECONDS == 30.0


def test_snapshot_window_follows_monitor_cadence() -> None:
    # 60s minimum between evaluations + 10s interval + 30s tolerance.
    assert (
        snapshot_stale_after_seconds(monitor_min_seconds=60.0, monitor_interval_seconds=10.0)
        == 100.0
    )


def test_snapshot_window_scales_with_cadence() -> None:
    assert (
        snapshot_stale_after_seconds(monitor_min_seconds=120.0, monitor_interval_seconds=5.0)
        == 155.0
    )


def test_snapshot_window_clamps_negative_cadence() -> None:
    # A misconfigured negative cadence must not make the window shorter than the
    # base telemetry tolerance.
    assert (
        snapshot_stale_after_seconds(monitor_min_seconds=-10.0, monitor_interval_seconds=-5.0)
        == STALE_AFTER_SECONDS
    )


def test_snapshot_window_with_zero_cadence() -> None:
    assert (
        snapshot_stale_after_seconds(monitor_min_seconds=0.0, monitor_interval_seconds=0.0)
        == STALE_AFTER_SECONDS
    )
