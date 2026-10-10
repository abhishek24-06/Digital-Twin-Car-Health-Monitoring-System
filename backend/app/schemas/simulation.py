"""Wire schemas for dynamic vehicle simulator control.

Scenario names mirror the simulator's canonical set by importing its
``ScenarioName`` Literal, so the API can never drift from the scenarios the
simulator actually supports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from simulator.config import ScenarioName

SimulationState = Literal["stopped", "starting", "running", "stopping", "degraded", "error"]

INTERVAL_MIN = 0.1
INTERVAL_MAX = 60.0
SEED_MIN = 0


class SimulationStartRequest(BaseModel):
    """Configuration for one simulator process.

    Every field is validated server-side and then baked into the simulator
    process environment verbatim -- no user-supplied value ever reaches the
    process environment apart from these. ``extra="forbid"`` keeps a client
    from sneaking arbitrary settings through.
    """

    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioName = "normal"
    interval_seconds: float = Field(default=1.0, gt=0, le=INTERVAL_MAX)
    seed: int | None = Field(default=None, ge=SEED_MIN)


class SimulationStatusResponse(BaseModel):
    """Current simulator state for one vehicle.

    Deliberately omits process details (PID, command line, environment): the
    client only ever needs the lifecycle state and the user-facing parameters.
    ``last_telemetry_at`` is the newest persisted telemetry timestamp for the
    vehicle. The API derives ``status="degraded"`` (with a reason in
    ``error``) whenever a process is alive but the end-to-end pipeline is not
    producing data -- e.g. the backend subscriber is offline or no telemetry
    has reached the database while the simulator has been up.
    """

    vehicle_id: UUID
    status: SimulationState
    scenario: ScenarioName | None = None
    interval_seconds: float | None = None
    seed: int | None = None
    started_at: datetime | None = None
    error: str | None = None
    last_telemetry_at: datetime | None = None
    correlation_id: str | None = None
