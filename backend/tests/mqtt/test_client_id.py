"""create_mqtt_client: passthrough + uniqueness of the effective client id.

No broker is required: constructing an aiomqtt client only builds the paho
client object. Two instances built from default settings must carry distinct
client ids, otherwise a second process performs an MQTT session takeover of
the first (the Windows subscriber crash this guards against).
"""

import asyncio

from app.core.config import Settings
from app.mqtt.client import create_mqtt_client


def _effective_client_id() -> str:
    async def _build() -> str:
        client = create_mqtt_client(Settings())
        # aiomqtt wraps a paho client; paho exposes no public accessor for the
        # identifier, so read its private attribute in the test.
        return client._client._client_id.decode()

    return asyncio.run(_build())


def test_default_client_ids_are_distinct() -> None:
    assert _effective_client_id() != _effective_client_id()


def test_explicit_client_id_is_used_verbatim(monkeypatch) -> None:
    monkeypatch.setenv("MQTT_CLIENT_ID", "stable-id-passthrough")
    assert _effective_client_id() == "stable-id-passthrough"
