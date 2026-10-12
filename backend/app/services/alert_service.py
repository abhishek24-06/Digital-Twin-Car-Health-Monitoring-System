"""Persistent, first-class alerts derived from live health findings.

Findings inside a health snapshot are immutable evidence. Alerts are the mutable
counterpart: the background monitor materializes an alert for every
current-session **warning/critical** finding, folds repeats into the existing
active alert (deduplication), auto-resolves an alert once the condition is no
longer observed on a *definitive* evaluation, and records every transition in
``alert_events``. Users acknowledge and resolve alerts through the API.

Historical (windowed) analyses never create alerts: an alert always represents
the vehicle's current session, mirroring the live-vs-historical separation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.intelligence.rules import (
    INSUFFICIENT_DATA_RULE,
    LIMITED_DATA_RULE,
    LIVE_SUFFICIENCY_RULE,
)
from app.models.alert import (
    ALERT_ACTIVE_STATUSES,
    ALERT_EVENT_ACKNOWLEDGED,
    ALERT_EVENT_CREATED,
    ALERT_EVENT_RECURRED,
    ALERT_EVENT_RESOLVED,
    ALERT_STATUS_ACKNOWLEDGED,
    ALERT_STATUS_OPEN,
    ALERT_STATUS_RESOLVED,
    Alert,
    AlertEvent,
)
from app.models.user import User
from app.repositories.alert_repository import AlertRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.vehicle_access import ensure_vehicle_access

logger = logging.getLogger(__name__)

#: Rules that describe the *state of the data* rather than the vehicle. They are
#: intentionally not alert-worthy: an alert must be actionable telemetry
#: evidence, never a "not enough data" notice. Data-quality findings are also
#: excluded by severity (they are informational).
_EXCLUDED_RULES = frozenset(
    {
        INSUFFICIENT_DATA_RULE,
        LIMITED_DATA_RULE,
        LIVE_SUFFICIENCY_RULE,
        "TELEMETRY_GAP",
        "LOW_DATA_COVERAGE",
    }
)

#: Short, human-readable titles per rule id. Unknown rules fall back to the
#: title-cased id so a new rule still produces a legible alert.
_RULE_TITLES: dict[str, str] = {
    "COOLANT_TEMP_HIGH": "Coolant temperature high",
    "OIL_TEMP_HIGH": "Oil temperature high",
    "BATTERY_VOLTAGE_LOW": "Battery voltage low",
    "BATTERY_VOLTAGE_HIGH": "Battery voltage high",
    "ENGINE_LOAD_HIGH": "Engine load high",
    "RPM_UNUSUAL": "Engine speed unusual",
    "FUEL_LEVEL_LOW": "Fuel level low",
    "RAPID_COOLANT_RISE": "Rapid coolant temperature rise",
    "RAPID_OIL_TEMP_RISE": "Rapid oil temperature rise",
}

_AUTO_RESOLUTION_NOTE = (
    "Automatically resolved: the condition was no longer present in the "
    "current session on the latest definitive evaluation."
)


def is_alert_worthy(finding: dict[str, Any]) -> bool:
    """Whether a serialized finding should become a persistent alert.

    Only warning/critical, non-data-quality findings whose rule is not a
    data-sufficiency notice qualify.
    """
    if finding.get("severity") not in ("warning", "critical"):
        return False
    rule_id = finding.get("rule_id")
    if not isinstance(rule_id, str) or rule_id in _EXCLUDED_RULES:
        return False
    return finding.get("category") != "data_quality"


def alert_title(rule_id: str) -> str:
    return _RULE_TITLES.get(rule_id, rule_id.replace("_", " ").capitalize())


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _parse_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


class AlertService:
    """Materializes findings into alerts and drives the alert lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        vehicle_repository: VehicleRepository,
        alert_repository: AlertRepository,
    ) -> None:
        self._session = session
        self._vehicle_repository = vehicle_repository
        self._alert_repository = alert_repository

    # ------------------------------------------------------------------
    # Materialization (background monitor -> alerts)
    # ------------------------------------------------------------------
    async def sync_from_snapshot(self, snapshot: Any) -> list[Alert]:
        """Create/refresh/auto-resolve alerts from one live health snapshot.

        ``snapshot`` is a ``HealthSnapshot`` (or a test double exposing
        ``vehicle_id``/``context_json``). Alert-worthiness, deduplication and
        auto-resolution are all decided here so the monitor stays transport-only.
        """
        vehicle_id = getattr(snapshot, "vehicle_id", None)
        context = getattr(snapshot, "context_json", None) or {}
        findings = context.get("findings") or []
        provisional = bool(context.get("provisional", False))
        run_id = _parse_uuid(context.get("simulation_run_id"))
        snapshot_id = _parse_uuid(getattr(snapshot, "id", None))
        observed_at = getattr(snapshot, "generated_at", None) or datetime.now(UTC)

        if vehicle_id is None:
            logger.warning("alert sync skipped: snapshot has no vehicle_id")
            return []

        worthy = [f for f in findings if isinstance(f, dict) and is_alert_worthy(f)]
        active = {
            a.dedup_key: a for a in await self._alert_repository.list_active_by_vehicle(vehicle_id)
        }

        touched: list[Alert] = []
        seen: set[str] = set()
        for finding in worthy:
            rule_id = str(finding.get("rule_id"))
            dedup_key = f"{vehicle_id}:{rule_id}"
            seen.add(dedup_key)
            existing = active.get(dedup_key)
            if existing is None:
                touched.append(
                    await self._create_alert(
                        vehicle_id=vehicle_id,
                        run_id=run_id,
                        snapshot_id=snapshot_id,
                        finding=finding,
                        observed_at=observed_at,
                        provisional=provisional,
                    )
                )
            else:
                touched.append(
                    await self._record_recurrence(
                        existing,
                        run_id=run_id,
                        snapshot_id=snapshot_id,
                        finding=finding,
                        observed_at=observed_at,
                        provisional=provisional,
                    )
                )

        # Auto-resolve an active alert only when a *definitive* (non-provisional)
        # evaluation no longer observes it: insufficient data is not evidence
        # that a condition has cleared.
        if not provisional:
            for dedup_key, alert in active.items():
                if dedup_key in seen:
                    continue
                await self._auto_resolve(alert, observed_at)

        await self._session.commit()
        return touched

    async def _create_alert(
        self,
        *,
        vehicle_id: UUID,
        run_id: UUID | None,
        snapshot_id: UUID | None,
        finding: dict[str, Any],
        observed_at: datetime,
        provisional: bool,
    ) -> Alert:
        rule_id = str(finding.get("rule_id"))
        alert = Alert(
            vehicle_id=vehicle_id,
            simulation_run_id=run_id,
            dedup_key=f"{vehicle_id}:{rule_id}",
            rule_id=rule_id,
            category=finding.get("category"),
            severity=str(finding.get("severity")),
            status=ALERT_STATUS_OPEN,
            title=alert_title(rule_id),
            message=str(finding.get("message", "")),
            metric=finding.get("metric"),
            observed_value=_as_float(finding.get("observed_value")),
            threshold=_as_float(finding.get("threshold")),
            unit=finding.get("unit"),
            confidence=_as_float(finding.get("confidence")),
            provisional=provisional,
            occurrence_count=1,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            evidence=finding,
            snapshot_id=snapshot_id,
        )
        created = await self._alert_repository.create(alert)
        await self._alert_repository.add_event(
            AlertEvent(
                alert_id=created.id,
                event_type=ALERT_EVENT_CREATED,
                from_status=None,
                to_status=ALERT_STATUS_OPEN,
                actor_user_id=None,
                note=f"Detected: {created.title}",
            )
        )
        logger.info(
            "alert created: vehicle_id=%s rule_id=%s severity=%s alert_id=%s",
            vehicle_id,
            rule_id,
            created.severity,
            created.id,
        )
        return created

    async def _record_recurrence(
        self,
        alert: Alert,
        *,
        run_id: UUID | None,
        snapshot_id: UUID | None,
        finding: dict[str, Any],
        observed_at: datetime,
        provisional: bool,
    ) -> Alert:
        previous_severity = alert.severity
        alert.simulation_run_id = run_id
        alert.snapshot_id = snapshot_id
        alert.severity = str(finding.get("severity"))
        alert.category = finding.get("category")
        alert.message = str(finding.get("message", alert.message))
        alert.metric = finding.get("metric")
        alert.observed_value = _as_float(finding.get("observed_value"))
        alert.threshold = _as_float(finding.get("threshold"))
        alert.unit = finding.get("unit")
        alert.confidence = _as_float(finding.get("confidence"))
        alert.provisional = provisional
        alert.evidence = finding
        alert.occurrence_count += 1
        alert.last_seen_at = observed_at

        note = f"Recurred (occurrence #{alert.occurrence_count})"
        if alert.severity != previous_severity:
            note += f"; severity changed {previous_severity} -> {alert.severity}"
        await self._alert_repository.add_event(
            AlertEvent(
                alert_id=alert.id,
                event_type=ALERT_EVENT_RECURRED,
                from_status=alert.status,
                to_status=alert.status,
                actor_user_id=None,
                note=note,
            )
        )
        return alert

    async def _auto_resolve(self, alert: Alert, observed_at: datetime) -> None:
        previous = alert.status
        alert.status = ALERT_STATUS_RESOLVED
        alert.resolved_at = observed_at
        alert.resolved_by = None
        alert.resolution_note = "Condition no longer present in the current session."
        await self._alert_repository.add_event(
            AlertEvent(
                alert_id=alert.id,
                event_type=ALERT_EVENT_RESOLVED,
                from_status=previous,
                to_status=ALERT_STATUS_RESOLVED,
                actor_user_id=None,
                note="Auto-resolved: condition no longer observed in a definitive evaluation.",
            )
        )
        logger.info("alert auto-resolved: alert_id=%s rule_id=%s", alert.id, alert.rule_id)

    # ------------------------------------------------------------------
    # Read / lifecycle (user-facing)
    # ------------------------------------------------------------------
    async def list_for_user(
        self,
        vehicle_id: UUID,
        user: User,
        *,
        statuses: list[str] | None = None,
        severity: str | None = None,
        page: int,
        page_size: int,
    ) -> tuple[list[Alert], int]:
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self._alert_repository.list_by_vehicle(
            vehicle_id,
            statuses=statuses,
            severity=severity,
            page=page,
            page_size=page_size,
        )

    async def get_for_user(
        self, vehicle_id: UUID, alert_id: UUID, user: User
    ) -> tuple[Alert, list[AlertEvent]]:
        alert = await self._get_scoped_alert(vehicle_id, alert_id, user)
        events = await self._alert_repository.list_events(alert.id)
        return alert, events

    async def acknowledge_for_user(
        self,
        vehicle_id: UUID,
        alert_id: UUID,
        user: User,
        *,
        note: str | None = None,
    ) -> Alert:
        alert = await self._get_scoped_alert(vehicle_id, alert_id, user)
        if alert.status == ALERT_STATUS_RESOLVED:
            raise ConflictError("A resolved alert cannot be acknowledged")
        if alert.status == ALERT_STATUS_ACKNOWLEDGED:
            # Idempotent: re-acknowledging is a no-op (never rewrites history).
            return alert

        alert.status = ALERT_STATUS_ACKNOWLEDGED
        alert.acknowledged_at = datetime.now(UTC)
        alert.acknowledged_by = user.id
        alert.acknowledge_note = note
        await self._alert_repository.add_event(
            AlertEvent(
                alert_id=alert.id,
                event_type=ALERT_EVENT_ACKNOWLEDGED,
                from_status=ALERT_STATUS_OPEN,
                to_status=ALERT_STATUS_ACKNOWLEDGED,
                actor_user_id=user.id,
                note=note,
            )
        )
        await self._session.commit()
        await self._session.refresh(alert)
        return alert

    async def resolve_for_user(
        self,
        vehicle_id: UUID,
        alert_id: UUID,
        user: User,
        *,
        note: str | None = None,
    ) -> Alert:
        alert = await self._get_scoped_alert(vehicle_id, alert_id, user)
        if alert.status == ALERT_STATUS_RESOLVED:
            return alert

        previous = alert.status
        alert.status = ALERT_STATUS_RESOLVED
        alert.resolved_at = datetime.now(UTC)
        alert.resolved_by = user.id
        alert.resolution_note = note
        await self._alert_repository.add_event(
            AlertEvent(
                alert_id=alert.id,
                event_type=ALERT_EVENT_RESOLVED,
                from_status=previous,
                to_status=ALERT_STATUS_RESOLVED,
                actor_user_id=user.id,
                note=note,
            )
        )
        await self._session.commit()
        await self._session.refresh(alert)
        return alert

    async def _get_scoped_alert(self, vehicle_id: UUID, alert_id: UUID, user: User) -> Alert:
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        alert = await self._alert_repository.get_by_id(alert_id)
        if alert is None or alert.vehicle_id != vehicle_id:
            # Never reveal that an alert exists on a vehicle the caller cannot
            # address: both unowned-vehicle and cross-vehicle ids are a 404.
            raise NotFoundError("Alert")
        return alert

    @staticmethod
    def is_active(alert: Alert) -> bool:
        return alert.status in ALERT_ACTIVE_STATUSES
