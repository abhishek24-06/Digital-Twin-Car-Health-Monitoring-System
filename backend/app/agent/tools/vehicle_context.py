"""Vehicle Context Tool — the only way the agent reads vehicle data (Phase 4).

The tool's data access mirrors the layer it wraps (VehicleHealthService); the
LLM never issues SQL, touches repositories, or accesses the database itself.
Output is bounded to the configured context size before it is handed to the
model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.agent.config import AgentSettings
from app.agent.determinism import derive_confidence, derive_severity
from app.intelligence.models import HealthContext
from app.services.vehicle_health_service import VehicleHealthService


@dataclass(slots=True)
class VehicleContextResult:
    """Bounded, serializable context handed to the reasoning step."""

    vehicle_id: UUID
    context: HealthContext | None
    serialized_context: str
    context_note: str
    severity: str
    confidence: float
    context_timestamp: datetime | None


class VehicleContextTool:
    """Read-only gateway between the agent layer and vehicle health context."""

    def __init__(
        self,
        vehicle_health_service: VehicleHealthService,
        settings: AgentSettings,
    ) -> None:
        self._vehicle_health_service = vehicle_health_service
        self._settings = settings

    async def get_context(self, vehicle_id: UUID) -> VehicleContextResult:
        """Fetch the latest health snapshot for the vehicle (bounded JSON)."""
        snapshot = await self._vehicle_health_service.get_latest(vehicle_id)
        if snapshot is None:
            return VehicleContextResult(
                vehicle_id=vehicle_id,
                context=None,
                serialized_context="",
                context_note=(
                    "No Vehicle Health Context is available for this vehicle yet. "
                    "Generate one with the health analysis endpoint before asking for diagnostics."
                ),
                severity="info",
                confidence=0.0,
                context_timestamp=None,
            )

        context = HealthContext.model_validate(snapshot.context_json)
        return VehicleContextResult(
            vehicle_id=vehicle_id,
            context=context,
            serialized_context=self._serialize(context),
            context_note=self._context_note(context),
            severity=derive_severity(context),
            confidence=derive_confidence(context),
            context_timestamp=snapshot.generated_at,
        )

    def _serialize(self, context: HealthContext) -> str:
        payload = json.dumps(context.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        max_chars = max(1024, self._settings.llm_context_max_chars)
        if len(payload) > max_chars:
            payload = payload[:max_chars]
        return payload

    @staticmethod
    def _context_note(context: HealthContext) -> str:
        notes: list[str] = []
        if context.data_quality.sample_count < 10:
            notes.append(
                "Data-quality note: the sampled window is small; conclusions "
                "should be appropriately cautious."
            )
        if (
            context.data_quality.max_gap_seconds is not None
            and context.data_quality.max_gap_seconds > 60
        ):
            notes.append(
                "Data-quality note: telemetry has significant gaps; trends may be incomplete."
            )
        return " ".join(notes)
