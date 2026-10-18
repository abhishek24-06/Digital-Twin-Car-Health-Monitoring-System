"""Truthful simulator-state reconciliation.

A simulator process can be alive while producing nothing usable: the MQTT
broker may be down, the backend subscriber may be stopped, or the feed may
simply have stopped. Reporting a hollow "running" in that case is the single
most misleading thing the UI could do.

The historical cleanup for that lives here so every consumer derives the same
answer from the same thresholds:

* the per-vehicle Simulation Control routes (:mod:`app.api.routes.simulation`),
  and
* the fleet overview (:mod:`app.services.fleet_overview`).

The thresholds themselves stay in :mod:`app.services.telemetry_freshness` --
this module only applies them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.simulation import SimulationState
from app.services.simulation_manager import SimulationStatus
from app.services.telemetry_freshness import (
    STALE_AFTER_SECONDS,
    STARTUP_BUFFER_SECONDS,
)


def telemetry_is_stale(
    simulation: SimulationStatus,
    last_telemetry_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Whether a started simulator's feed counts as stale.

    A freshly spawned simulator gets a warm-up window before a missing feed is
    treated as a fault; afterwards the newest persisted row decides.
    """
    now = now or datetime.now(UTC)
    if simulation.started_at is not None:
        uptime = (now - simulation.started_at).total_seconds()
        if uptime < STARTUP_BUFFER_SECONDS:
            return False
    if last_telemetry_at is None:
        return True
    return (now - last_telemetry_at).total_seconds() > STALE_AFTER_SECONDS


def stale_reason(last_telemetry_at: datetime | None) -> str:
    """Operator-facing explanation for a stale-but-running simulator."""
    if last_telemetry_at is None:
        return (
            "Simulator is running but no telemetry has reached the database yet. "
            "Check the MQTT broker and the backend subscriber."
        )
    return (
        f"Simulator is running but the newest telemetry is from "
        f"{last_telemetry_at.isoformat()} -- the feed has gone stale. Check the MQTT "
        "broker and the backend subscriber."
    )


def derive_simulation_state(
    simulation: SimulationStatus,
    last_telemetry_at: datetime | None,
    subscriber_running: bool,
    *,
    now: datetime | None = None,
) -> tuple[SimulationState, str | None]:
    """Truthful status for a vehicle.

    The manager's lifecycle state is reconciled against the pipeline: a started
    process that cannot possibly be delivering telemetry (subscriber offline, or
    no row in the database while the simulator has been up for longer than the
    warm-up window) is reported as ``degraded`` with a self-explanatory reason,
    never as a hollow "running".
    """
    lifecycle = simulation.status
    if lifecycle not in ("starting", "running"):
        return lifecycle, simulation.error
    if not subscriber_running:
        return (
            "degraded",
            "Telemetry ingestion is offline: the backend subscriber is not running, "
            "so simulator output is not reaching the database.",
        )
    if lifecycle == "running" and telemetry_is_stale(simulation, last_telemetry_at, now=now):
        return "degraded", stale_reason(last_telemetry_at)
    return lifecycle, simulation.error
