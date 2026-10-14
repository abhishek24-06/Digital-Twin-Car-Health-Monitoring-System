"""Pipeline evaluation package (RQ3 alerts, RQ4 latency, RQ6 robustness).

Unlike :mod:`evaluation.analysis`, which evaluates the analyzer over in-memory
:class:`evaluation.runner.EpisodeResult` objects, this package drives the **real
runtime path**: MQTT publish → subscriber → PostgreSQL, then the real
:class:`app.services.vehicle_health_service.VehicleHealthService` and
:class:`app.services.alert_service.AlertService` exactly as the background
monitor does. It therefore requires an isolated disposable database and a
private Mosquitto broker, and is gated behind the Phase C fail-closed contract.
"""

from __future__ import annotations

__all__: list[str] = []
