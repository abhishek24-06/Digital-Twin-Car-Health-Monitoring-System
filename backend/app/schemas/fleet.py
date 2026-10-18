"""Read-only fleet overview contract for the dashboard.

The fleet dashboard needs four things that, individually, would cost one request
per vehicle: the latest stored health assessment, the active-alert tally, the
newest telemetry timestamp, and the simulator state. This endpoint returns all
of them for every vehicle the caller may access in a single round trip.

Freshness is classified *here*, from the same thresholds the rest of the
backend uses (:mod:`app.services.telemetry_freshness`), so the dashboard can
never contradict Simulation Control or the workflow monitor. Nothing in the
response is synthesised: an absent assessment is ``None``, never a default
score, and a stale assessment is labelled as such rather than passed off as the
current state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.simulation import SimulationState

#: Telemetry freshness for one vehicle.
#:
#: * ``recent``  -- the newest persisted sample is within the stale threshold.
#: * ``stale``   -- samples exist but the newest is older than the threshold.
#: * ``no_data`` -- the vehicle has never persisted a sample.
#: * ``unknown`` -- a timestamp was present but could not be interpreted. It is
#:   never used as a stand-in for "we did not check".
TelemetryFreshness = Literal["recent", "stale", "no_data", "unknown"]

#: How current a stored assessment is relative to the health monitor's cadence.
AssessmentFreshness = Literal["fresh", "stale", "none"]


class FleetAssessmentSummary(BaseModel):
    """The most recent stored health assessment for one vehicle.

    A snapshot is historical evidence, so it always carries its own
    ``generated_at``: the dashboard labels it with that timestamp and never
    presents an aged score as the vehicle's current state.
    """

    health_status: str
    #: The best available rating while ``health_status`` is a data-state label
    #: (e.g. ``limited_data`` with a ``critical`` provisional rating). ``None``
    #: when the status already is a rating.
    provisional_rating: str | None = None
    health_score: float | None = None
    confidence: float | None = None
    generated_at: datetime
    #: A provisional assessment (limited data / low confidence) must not read as
    #: a definitive verdict.
    provisional: bool = False
    data_sufficiency: str | None = None
    analysis_scope: str | None = None
    sample_count: int | None = None


class FleetVehicleSummary(BaseModel):
    """One fleet row: identity, simulator state, freshness and assessment."""

    vehicle_id: UUID
    vin: str
    make: str
    model: str
    year: int
    engine_type: str | None = None
    status: str

    #: Reconciled simulator state (never a hollow "running" while the feed is
    #: down -- see :mod:`app.services.simulation_state`).
    simulation_state: SimulationState
    simulation_scenario: str | None = None
    simulation_started_at: datetime | None = None
    simulation_error: str | None = None

    last_telemetry_at: datetime | None = None
    telemetry_freshness: TelemetryFreshness

    #: Latest stored assessment, or ``None`` when the vehicle was never scored.
    assessment: FleetAssessmentSummary | None = None
    assessment_freshness: AssessmentFreshness

    open_alerts: int = 0
    critical_open_alerts: int = 0
    warning_open_alerts: int = 0
    #: Whether this vehicle currently needs attention (see
    #: :mod:`app.services.fleet_overview` for the exact definition).
    requires_attention: bool = False


class FleetTotals(BaseModel):
    """Fleet KPI counts, each derived from one documented signal."""

    vehicles: int
    vehicles_with_recent_telemetry: int
    vehicles_requiring_attention: int
    vehicles_with_open_alerts: int
    active_simulations: int
    open_alerts: int
    critical_open_alerts: int


class FleetOverviewResponse(BaseModel):
    """Single-round-trip fleet snapshot backing the dashboard."""

    generated_at: datetime
    #: The thresholds used to classify freshness above, echoed so the UI can
    #: explain itself and reuse the exact same numbers.
    telemetry_stale_after_seconds: float
    assessment_stale_after_seconds: float
    totals: FleetTotals
    vehicles: list[FleetVehicleSummary] = Field(default_factory=list)
