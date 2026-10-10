"""Shared telemetry-freshness thresholds.

The Simulation Control routes and the derived workflow telemetry-state service
must agree on when a running simulator's feed counts as stale. The thresholds
live here once so both consumers reuse the same values instead of duplicating
(or drifting from) them.

A freshly spawned simulator gets a warm-up window before its missing feed is
treated as a fault; afterwards any running process whose newest persisted row
is older than ``STALE_AFTER_SECONDS`` is considered degraded rather than
healthily "running".

Health snapshots age on a *different* clock from telemetry. The health monitor
throttles per-vehicle evaluations to at most one per
``health_monitor_min_seconds`` and a pass can be up to
``health_monitor_interval_seconds`` late, so a perfectly healthy engine can
legitimately go that long between snapshots. Reusing the 30-second telemetry
window for snapshots made the UI declare a fresh, actively-produced snapshot
"stale" for roughly half of every evaluation cycle. ``snapshot_stale_after_seconds``
derives the correct threshold from the monitor's own cadence.
"""

from __future__ import annotations

STARTUP_BUFFER_SECONDS = 25.0
STALE_AFTER_SECONDS = 30.0


def snapshot_stale_after_seconds(
    *,
    monitor_min_seconds: float,
    monitor_interval_seconds: float,
) -> float:
    """Max age a health snapshot may reach while the monitor is healthy.

    A snapshot is produced at most once per ``monitor_min_seconds`` per vehicle
    and the next pass can run up to ``monitor_interval_seconds`` later, so the
    engine closing on ``monitor_min_seconds + monitor_interval_seconds`` of age
    is normal. ``STALE_AFTER_SECONDS`` is added as tolerance for a single
    missed/slow tick so ordinary jitter is never reported as a fault while a
    genuinely stopped monitor still surfaces quickly.
    """
    cadence = max(monitor_min_seconds, 0.0) + max(monitor_interval_seconds, 0.0)
    return cadence + STALE_AFTER_SECONDS
