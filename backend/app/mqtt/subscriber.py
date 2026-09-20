"""MQTT telemetry subscriber.

Listens for vehicle telemetry envelopes, validates them, and persists them
through the same service/repository layers the REST API uses. The subscriber
contains no direct SQLAlchemy persistence logic.

Design:
    - subscribes to ``{prefix}/+/telemetry``
    - reconnect loop with exponential backoff (1, 2, 4, ... capped)
    - graceful shutdown on SIGINT/SIGTERM
    - malformed / unknown-vehicle / duplicate messages are logged and skipped
    - transient database failures are retried a bounded number of times

Run with ``python -m app.mqtt.subscriber``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from typing import Any

import aiomqtt

from app.core.config import Settings, get_settings
from app.core.database import dispose_engine, get_session_factory, init_engine
from app.core.exceptions import DatabaseError, NotFoundError
from app.core.logging import configure_logging
from app.mqtt.client import create_mqtt_client, sleep_with_stop
from app.mqtt.exceptions import MQTTParseError
from app.mqtt.parser import TelemetryMessageParser
from app.mqtt.schemas import TelemetryMessage
from app.mqtt.topics import telemetry_subscribe_pattern
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)


class MQTTSubscriber:
    """Connect, consume, validate and persist MQTT telemetry messages."""

    def __init__(self, settings: Settings, session_factory) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._parser = TelemetryMessageParser(settings.mqtt_topic_prefix)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Run the subscriber until ``stop_event`` is set."""
        backoff = _initial_backoff()

        while not stop_event.is_set():
            try:
                await self._run_connection(stop_event)
                backoff = _initial_backoff()
            except aiomqtt.MqttError as exc:
                if not stop_event.is_set():
                    logger.warning("MQTT connection error: %s", exc)
            except Exception:
                if not stop_event.is_set():
                    logger.exception("Unexpected subscriber error")

            if stop_event.is_set():
                break
            logger.info("Reconnecting to MQTT broker in %.0fs", backoff)
            await sleep_with_stop(backoff, stop_event)
            backoff = _next_backoff(backoff, self._settings.mqtt_reconnect_max_seconds)

        logger.info("MQTT subscriber stopped")

    async def _run_connection(self, stop_event: asyncio.Event) -> None:
        client = create_mqtt_client(self._settings)
        async with client as connected:
            await connected.subscribe(
                telemetry_subscribe_pattern(self._settings.mqtt_topic_prefix),
                qos=self._settings.mqtt_qos,
            )
            logger.info(
                "Connected to %s:%s, subscribed to %s",
                self._settings.mqtt_broker_host,
                self._settings.mqtt_broker_port,
                telemetry_subscribe_pattern(self._settings.mqtt_topic_prefix),
            )
            consume = asyncio.create_task(self._consume_messages(connected, stop_event))
            stop_wait = asyncio.create_task(stop_event.wait())
            try:
                await asyncio.wait({consume, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                if not consume.done():
                    consume.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await consume
            if consume.done():
                with contextlib.suppress(asyncio.CancelledError):
                    error = consume.exception()
                    if error is not None:
                        raise error

    async def _consume_messages(self, connected: aiomqtt.Client, stop_event: asyncio.Event) -> None:
        async for message in connected.messages:
            if stop_event.is_set():
                break
            await self._handle_message(message)

    async def _handle_message(self, message: aiomqtt.Message) -> None:
        topic = message.topic.value
        payload = message.payload
        try:
            envelope = self._parser.parse(topic, payload)
        except MQTTParseError as exc:
            logger.warning("Discarding invalid message on %s: %s", topic, exc)
            return

        await self._persist_with_retry(envelope, payload)

    async def _persist_with_retry(self, envelope: TelemetryMessage, raw: bytes) -> None:
        attempts = max(1, self._settings.mqtt_message_retry_attempts)
        for attempt in range(1, attempts + 1):
            try:
                await self._persist(envelope, raw)
                return
            except NotFoundError:
                logger.warning(
                    "Unknown vehicle %s; discarding telemetry event %s",
                    envelope.vehicle_id,
                    envelope.event_id,
                )
                return
            except (DatabaseError, OSError, RuntimeError) as exc:
                if attempt < attempts:
                    wait = min(2 ** (attempt - 1), 5.0)
                    logger.warning(
                        "Transient error persisting message (attempt %d/%d): %s; retrying in %.0fs",
                        attempt,
                        attempts,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Giving up on telemetry event %s after %d attempts: %s",
                        envelope.event_id,
                        attempts,
                        exc,
                    )

    async def _persist(self, envelope: TelemetryMessage, raw: bytes) -> None:
        fields: dict[str, Any] = envelope.telemetry.model_dump()
        fields["timestamp"] = envelope.timestamp
        fields["source_event_id"] = envelope.event_id
        fields["raw_payload"] = envelope.model_dump(mode="json")
        data = TelemetryCreate(**fields)

        async with self._session_factory() as session:
            service = TelemetryService(
                session=session,
                repository=TelemetryRepository(session),
                vehicle_repository=VehicleRepository(session),
            )
            await service.create_telemetry(envelope.vehicle_id, data)


def _initial_backoff() -> float:
    return 1.0


def _next_backoff(current: float, maximum: float) -> float:
    if maximum <= 0:
        return current
    return min(current * 2, maximum)


def main() -> None:
    settings = get_settings()
    configure_logging(debug=settings.is_debug)
    init_engine(settings)

    stop_event = asyncio.Event()

    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop, stop_event)

    subscriber = MQTTSubscriber(settings, get_session_factory())
    try:
        loop.run_until_complete(subscriber.run_forever(stop_event))
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(dispose_engine())
        loop.close()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())


if __name__ == "__main__":
    main()
