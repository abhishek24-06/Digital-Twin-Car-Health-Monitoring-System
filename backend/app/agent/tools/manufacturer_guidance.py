"""Manufacturer Guidance Tool — thin read-only RAG adapter for the agent.

Mirrors the ``VehicleContextTool`` pattern: the LLM never issues SQL, never
touches repositories, and never talks to the RAG corpus directly. The tool
resolves the vehicle's identity (make/model/year/engine) into a Phase 5
``VehicleScope``, runs :class:`~app.rag.rag_service.RAGService` (which contains
no LLM), and returns *bounded, serializable* evidence + citations with full
provenance. Every failure mode (no vehicle row, disabled RAG, empty evidence,
retrieval error) degrades to ``available=False`` with a ``reason`` so the agent
falls back to the Phase 4 telemetry-only path without fabricating content.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.agent.config import AgentSettings
from app.rag.rag_service import RAGService
from app.rag.schemas import Citation, RAGGuidanceResult, VehicleScope
from app.repositories.vehicle_repository import VehicleRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ManufacturerGuidanceResult:
    """Bounded, serializable manufacturer evidence for one vehicle query.

    ``available=False`` with a ``reason`` is a normal state, not an error:
    retrieval was impossible, disabled, or simply returned nothing for the
    query/scope. The reasoning step must then ignore manufacturer content
    entirely.
    """

    vehicle_id: UUID
    scope: VehicleScope | None
    guidance: str
    citations: list[Citation]
    evidence: list[dict[str, Any]]
    available: bool
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)


class ManufacturerGuidanceTool:
    """Read-only gateway between the agent layer and the RAG corpus."""

    def __init__(
        self,
        rag_service: RAGService,
        vehicle_repository: VehicleRepository,
        settings: AgentSettings,
        session: Any,
    ) -> None:
        self._rag = rag_service
        self._vehicles = vehicle_repository
        self._settings = settings
        self._session = session

    async def get_guidance(
        self,
        vehicle_id: UUID,
        query: str,
    ) -> ManufacturerGuidanceResult:
        """Retrieve manufacturer evidence for ``query`` scoped to ``vehicle_id``.

        Never raises for expected degraded states; a fully ``unavailable``
        result is returned instead.
        """
        vehicle = await self._vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            return self._fail(vehicle_id, None, reason="no-vehicle")

        scope = VehicleScope(
            make=vehicle.make or None,
            model=vehicle.model or None,
            year=vehicle.year or None,
            engine=vehicle.engine_type or None,
        )
        if not self._rag.rag_enabled:
            return self._fail(vehicle_id, scope, reason="rag-disabled")

        try:
            conn = await self._session.connection()
            result = await self._rag.search(conn, query, vehicle_scope=scope)
        except Exception as exc:  # noqa: BLE001 - degrade, never 500
            logger.warning("manufacturer guidance retrieval failed: %s", exc)
            return self._fail(vehicle_id, scope, reason="retrieval-error")

        return self._from_rag(vehicle_id, scope, result)

    @staticmethod
    def _from_rag(
        vehicle_id: UUID,
        scope: VehicleScope,
        result: RAGGuidanceResult,
    ) -> ManufacturerGuidanceResult:
        if not result.available:
            return ManufacturerGuidanceResult(
                vehicle_id=vehicle_id,
                scope=scope,
                guidance="",
                citations=[],
                evidence=[],
                available=False,
                reason="no-evidence",
                metrics=result.metrics,
            )
        return ManufacturerGuidanceResult(
            vehicle_id=vehicle_id,
            scope=scope,
            guidance=result.guidance,
            citations=result.citations,
            evidence=[
                {"index": i + 1, **e.model_dump(mode="json")} for i, e in enumerate(result.evidence)
            ],
            available=True,
            reason=result.reason or "hybrid",
            metrics=result.metrics,
        )

    @staticmethod
    def _fail(
        vehicle_id: UUID,
        scope: VehicleScope | None,
        *,
        reason: str,
    ) -> ManufacturerGuidanceResult:
        return ManufacturerGuidanceResult(
            vehicle_id=vehicle_id,
            scope=scope,
            guidance="",
            citations=[],
            evidence=[],
            available=False,
            reason=reason,
        )
