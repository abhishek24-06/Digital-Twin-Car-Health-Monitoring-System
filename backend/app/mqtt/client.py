"""MQTT client construction and asyncio loop helpers."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any, Protocol

import aiomqtt


class MQTTConnectionSettings(Protocol):
    """The subset of settings needed to build an MQTT client.

    Both ``app.core.config.Settings`` and ``simulator.config.SimulatorSettings``
    provide these attributes, so either can drive client creation.
    """

    mqtt_broker_host: str
    mqtt_broker_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    mqtt_client_id: str
    mqtt_keepalive: int
    mqtt_qos: int
    mqtt_topic_prefix: str


def create_mqtt_client(settings: MQTTConnectionSettings) -> aiomqtt.Client:
    """Build an aiomqtt client configured from settings.

    Credentials are only passed to the broker when both are set, so an
    anonymous development broker works without configuration.
    """
    kwargs: dict[str, Any] = {
        "hostname": settings.mqtt_broker_host,
        "port": settings.mqtt_broker_port,
        "identifier": settings.mqtt_client_id,
        "keepalive": settings.mqtt_keepalive,
        "clean_session": True,
    }
    if settings.mqtt_username:
        kwargs["username"] = settings.mqtt_username
        kwargs["password"] = settings.mqtt_password or ""
    return aiomqtt.Client(**kwargs)


def run_async(coro: Coroutine) -> None:
    """Run a coroutine to completion.

    aiomqtt requires a loop that supports ``add_reader`` (the ``SelectorEventLoop``);
    on Windows that is not the default loop class, so install one explicitly here
    rather than relying on the deprecated ``WindowsSelectorEventLoopPolicy``.
    """
    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


async def sleep_with_stop(seconds: float, stop_event: asyncio.Event) -> None:
    """Sleep up to ``seconds`` unless ``stop_event`` becomes set first."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        pass
