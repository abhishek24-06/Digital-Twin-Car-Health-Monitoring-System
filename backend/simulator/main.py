"""Simulator entrypoint.

Publishes a telemetry envelope every ``SIMULATOR_INTERVAL_SECONDS`` on
``{prefix}/{vehicle_id}/telemetry`` after announcing ``online`` status, and
announces ``offline`` status on graceful shutdown.

Run with ``python -m simulator.main``.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import UTC, datetime
from uuid import uuid4

import aiomqtt

from app.core.logging import configure_logging
from app.mqtt.schemas import SCHEMA_VERSION, StatusMessage, TelemetryMessage
from simulator.config import SimulatorSettings, get_simulator_settings
from simulator.publisher import SimulatorPublisher
from simulator.telemetry_generator import SimulationEngine

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC)


async def run_forever(settings: SimulatorSettings, stop_event: asyncio.Event) -> None:
    """Publish telemetry until ``stop_event`` is set, reconnecting on drops."""
    engine = SimulationEngine(settings)
    backoff = 1.0
    offline_published = False

    while not stop_event.is_set():
        try:
            async with SimulatorPublisher(settings) as publisher:
                await publisher.publish_status(
                    StatusMessage(
                        vehicle_id=settings.vehicle_id,
                        status="online",
                        timestamp=_now_utc(),
                    )
                )
                logger.info("Simulator connected; publishing to %s", settings.vehicle_id)
                while not stop_event.is_set():
                    sample = engine.step(settings.interval_seconds)
                    message = TelemetryMessage(
                        schema_version=SCHEMA_VERSION,
                        event_id=uuid4().hex,
                        vehicle_id=settings.vehicle_id,
                        timestamp=_now_utc(),
                        telemetry=sample,
                    )
                    await publisher.publish_telemetry(message)
                    await _sleep(stop_event, settings.interval_seconds)
        except aiomqtt.MqttError as exc:
            if not stop_event.is_set():
                logger.warning("MQTT connection lost: %s", exc)
        except Exception:
            if not stop_event.is_set():
                logger.exception("Simulator loop error")
        finally:
            if not offline_published:
                await _publish_offline_status(settings)
                offline_published = True
            if not stop_event.is_set():
                logger.info("Reconnecting simulator in %.0fs", backoff)
                await _sleep(stop_event, backoff)
                backoff = min(backoff * 2, settings.mqtt_reconnect_max_seconds)

    logger.info("Simulator stopped")


async def _sleep(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def _publish_offline_status(settings: SimulatorSettings) -> None:
    try:
        async with SimulatorPublisher(settings) as publisher:
            await publisher.publish_status(
                StatusMessage(
                    vehicle_id=settings.vehicle_id,
                    status="offline",
                    timestamp=_now_utc(),
                )
            )
    except Exception:
        logger.exception("Failed to publish offline status")


def main() -> None:
    settings = get_simulator_settings()
    configure_logging(debug=settings.debug)

    stop_event = asyncio.Event()
    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())

    try:
        loop.run_until_complete(run_forever(settings, stop_event))
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
