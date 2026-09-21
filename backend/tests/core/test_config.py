"""Settings MQTT client id: unique per process, explicit env wins."""

from app.core.config import Settings


def test_default_client_id_is_unique_per_instance() -> None:
    first = Settings().mqtt_client_id
    second = Settings().mqtt_client_id

    assert first != second
    assert first.startswith("dtwin-sub-")
    assert second.startswith("dtwin-sub-")
    # MQTTv3.1.1 brokers reject client ids longer than 23 bytes.
    assert len(first) <= 23
    assert len(second) <= 23


def test_explicit_client_id_is_used_verbatim(monkeypatch) -> None:
    monkeypatch.setenv("MQTT_CLIENT_ID", "my-stable-subscriber")

    assert Settings().mqtt_client_id == "my-stable-subscriber"
