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
import time
from typing import Any

import aiomqtt

from app.core.config import Settings, get_settings
from app.core.database import dispose_engine, get_session_factory, init_engine
from app.core.exceptions import DatabaseError
from app.core.logging import configure_logging
from app.mqtt.client import create_mqtt_client, sleep_with_stop
from app.mqtt.exceptions import MQTTParseError
from app.mqtt.parser import TelemetryMessageParser
from app.mqtt.schemas import TelemetryMessage
from app.mqtt.topics import telemetry_subscribe_pattern
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate
from app.schemas.workflow import (
    WorkflowStage,
    WorkflowStatus,
    WorkflowType,
    sanitize_metadata,
)
from app.services.telemetry_service import BatchIngestResult, TelemetryService
from app.services.workflow_event_bus import publish_workflow_event

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

            await publish_workflow_event(
                workflow=WorkflowType.TELEMETRY,
                stage=WorkflowStage.MQTT_RECEIVED,
                status=WorkflowStatus.RUNNING,
                message=f"MQTT subscriber connected to {self._settings.mqtt_broker_host}:{self._settings.mqtt_broker_port}",
                metadata=sanitize_metadata(
                    {
                        "topic_pattern": telemetry_subscribe_pattern(
                            self._settings.mqtt_topic_prefix
                        ),
                        "qos": self._settings.mqtt_qos,
                    }
                ),
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
        """Consume messages in bounded batches.

        Persisting one message costs several database round trips. A serial
        one-at-a-time loop cannot keep up with multiple publishers when the
        database is remote, so a backlog builds and samples are persisted
        already older than the health analysis window. Collect up to
        ``mqtt_batch_max_messages`` (or whatever arrives within
        ``mqtt_batch_flush_seconds``) and write the batch with a single
        statement instead. The timeout bounds latency when the feed is idle.
        """
        max_batch = max(1, self._settings.mqtt_batch_max_messages)
        flush_after = self._settings.mqtt_batch_flush_seconds
        batch: list[aiomqtt.Message] = []

        while not stop_event.is_set():
            try:
                message = await asyncio.wait_for(anext(connected.messages), timeout=flush_after)
            except TimeoutError:
                if batch:
                    await self._flush_batch(batch)
                    batch = []
                continue
            except StopAsyncIteration:
                break
            batch.append(message)
            if len(batch) >= max_batch:
                await self._flush_batch(batch)
                batch = []

        if batch:
            await self._flush_batch(batch)

    async def _handle_message(self, message: aiomqtt.Message) -> None:
        """Parse and persist a single message (batch of one)."""
        await self._flush_batch([message])

    async def _flush_batch(self, messages: list[aiomqtt.Message]) -> None:
        """Validate every message, then persist the valid ones in one write."""
        parsed: list[tuple[TelemetryMessage, bytes]] = []
        for message in messages:
            topic = message.topic.value
            payload = message.payload
            try:
                envelope = self._parser.parse(topic, payload)
            except MQTTParseError as exc:
                logger.warning("Discarding invalid message on %s: %s", topic, exc)
                await publish_workflow_event(
                    workflow=WorkflowType.TELEMETRY,
                    stage=WorkflowStage.TELEMETRY_VALIDATION_ERROR,
                    status=WorkflowStatus.ERROR,
                    message=f"Invalid MQTT message on {topic}: {exc}",
                    metadata=sanitize_metadata(
                        {
                            "topic": topic,
                            "payload_size": len(payload),
                            "error": str(exc),
                        }
                    ),
                )
                continue

            await publish_workflow_event(
                workflow=WorkflowType.TELEMETRY,
                stage=WorkflowStage.TELEMETRY_PARSED,
                status=WorkflowStatus.SUCCESS,
                message=f"Telemetry parsed for vehicle {envelope.vehicle_id}",
                vehicle_id=str(envelope.vehicle_id),
                correlation_id=envelope.event_id,
                metadata=sanitize_metadata(
                    {
                        "topic": topic,
                        "payload_size": len(payload),
                        "event_id": envelope.event_id,
                        "signal_count": len(envelope.telemetry.model_dump()),
                    }
                ),
            )
            parsed.append((envelope, payload))

        if parsed:
            await self._persist_batch_with_retry(parsed)

    async def _persist_batch_with_retry(self, parsed: list[tuple[TelemetryMessage, bytes]]) -> None:
        attempts = max(1, self._settings.mqtt_message_retry_attempts)
        for attempt in range(1, attempts + 1):
            try:
                start_time = time.perf_counter()
                result = await self._persist_batch(parsed)
                duration_ms = (time.perf_counter() - start_time) * 1000

                for envelope, _raw in parsed:
                    if envelope.vehicle_id in result.unknown_vehicle_ids:
                        logger.warning(
                            "Unknown vehicle %s; discarding telemetry event %s",
                            envelope.vehicle_id,
                            envelope.event_id,
                        )
                        await publish_workflow_event(
                            workflow=WorkflowType.TELEMETRY,
                            stage=WorkflowStage.TELEMETRY_VALIDATION_ERROR,
                            status=WorkflowStatus.ERROR,
                            message=(
                                f"Unknown vehicle {envelope.vehicle_id} "
                                f"for event {envelope.event_id}"
                            ),
                            vehicle_id=str(envelope.vehicle_id),
                            correlation_id=envelope.event_id,
                            metadata=sanitize_metadata({"event_id": envelope.event_id}),
                        )
                        continue
                    await publish_workflow_event(
                        workflow=WorkflowType.TELEMETRY,
                        stage=WorkflowStage.TELEMETRY_PERSISTED,
                        status=WorkflowStatus.SUCCESS,
                        message=f"Telemetry persisted for vehicle {envelope.vehicle_id}",
                        vehicle_id=str(envelope.vehicle_id),
                        correlation_id=envelope.event_id,
                        duration_ms=duration_ms,
                        metadata=sanitize_metadata(
                            {
                                "event_id": envelope.event_id,
                                "attempt": attempt,
                                "table": "telemetry_records",
                                "batch_size": result.submitted,
                            }
                        ),
                    )
                return
            except (DatabaseError, OSError, RuntimeError) as exc:
                if attempt < attempts:
                    wait = min(2 ** (attempt - 1), 5.0)
                    logger.warning(
                        "Transient error persisting batch of %d (attempt %d/%d): %s; "
                        "retrying in %.0fs",
                        len(parsed),
                        attempt,
                        attempts,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Giving up on telemetry batch of %d after %d attempts: %s",
                        len(parsed),
                        attempts,
                        exc,
                    )
                    for envelope, _raw in parsed:
                        await publish_workflow_event(
                            workflow=WorkflowType.TELEMETRY,
                            stage=WorkflowStage.TELEMETRY_PERSIST_STARTED,
                            status=WorkflowStatus.ERROR,
                            message=(
                                f"Failed to persist telemetry event {envelope.event_id} "
                                f"after {attempts} attempts"
                            ),
                            vehicle_id=str(envelope.vehicle_id),
                            correlation_id=envelope.event_id,
                            metadata=sanitize_metadata(
                                {
                                    "event_id": envelope.event_id,
                                    "attempts": attempts,
                                    "error": str(exc),
                                }
                            ),
                        )

    async def _persist_batch(
        self, parsed: list[tuple[TelemetryMessage, bytes]]
    ) -> BatchIngestResult:
        items = []
        for envelope, _raw in parsed:
            fields: dict[str, Any] = envelope.telemetry.model_dump()
            fields["timestamp"] = envelope.timestamp
            fields["source_event_id"] = envelope.event_id
            fields["simulation_run_id"] = envelope.simulation_run_id
            fields["raw_payload"] = envelope.model_dump(mode="json")
            items.append((envelope.vehicle_id, TelemetryCreate(**fields)))

        async with self._session_factory() as session:
            service = TelemetryService(
                session=session,
                repository=TelemetryRepository(session),
                vehicle_repository=VehicleRepository(session),
            )
            return await service.ingest_batch(items)


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
