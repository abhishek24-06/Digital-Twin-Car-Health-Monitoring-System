"""Typed triggers for the Phase 4 agent layer.

An explicit enum keeps trigger types consistent across the API, the service,
LangGraph state and persisted diagnosis records.
"""

from __future__ import annotations

from enum import StrEnum


class TriggerType(StrEnum):
    """The reason an agent execution was started."""

    USER_QUERY = "USER_QUERY"
    CRITICAL_TELEMETRY_EVENT = "CRITICAL_TELEMETRY_EVENT"
    DASHBOARD_LOAD = "DASHBOARD_LOAD"
