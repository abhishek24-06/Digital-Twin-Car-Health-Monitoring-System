"""Settings MQTT client id: unique per process, explicit env wins."""

import pytest

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


def test_health_monitor_defaults(monkeypatch) -> None:
    monkeypatch.delenv("HEALTH_MONITOR_ENABLED", raising=False)
    monkeypatch.delenv("HEALTH_MONITOR_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("HEALTH_MONITOR_MIN_SECONDS", raising=False)
    monkeypatch.delenv("HEALTH_MONITOR_MAX_VEHICLES", raising=False)

    settings = Settings()

    assert settings.health_monitor_enabled is True
    assert settings.health_monitor_interval_seconds == 10.0
    assert settings.health_monitor_min_seconds == 60.0
    assert settings.health_monitor_max_vehicles == 25


def test_health_monitor_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("HEALTH_MONITOR_ENABLED", "false")
    monkeypatch.setenv("HEALTH_MONITOR_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("HEALTH_MONITOR_MAX_VEHICLES", "3")

    settings = Settings()

    assert settings.health_monitor_enabled is False
    assert settings.health_monitor_interval_seconds == 5.0
    assert settings.health_monitor_max_vehicles == 3


def test_health_monitor_rejects_non_positive_interval(monkeypatch) -> None:
    monkeypatch.setenv("HEALTH_MONITOR_INTERVAL_SECONDS", "0")

    with pytest.raises(ValueError, match="HEALTH_MONITOR_INTERVAL_SECONDS must be > 0"):
        Settings()


def test_health_monitor_rejects_negative_min_seconds(monkeypatch) -> None:
    monkeypatch.setenv("HEALTH_MONITOR_MIN_SECONDS", "-1")

    with pytest.raises(ValueError, match="HEALTH_MONITOR_MIN_SECONDS must be >= 0"):
        Settings()


def test_health_monitor_rejects_zero_max_vehicles(monkeypatch) -> None:
    monkeypatch.setenv("HEALTH_MONITOR_MAX_VEHICLES", "0")

    with pytest.raises(ValueError, match="HEALTH_MONITOR_MAX_VEHICLES must be >= 1"):
        Settings()


def test_rate_limit_defaults(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("AUTH_RATE_LIMIT_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", raising=False)

    settings = Settings()

    assert settings.auth_rate_limit_enabled is True
    assert settings.auth_rate_limit_max_requests == 10
    assert settings.auth_rate_limit_window_seconds == 60.0


def test_rate_limit_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT_MAX_REQUESTS", "5")
    monkeypatch.setenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "30")

    settings = Settings()

    assert settings.auth_rate_limit_max_requests == 5
    assert settings.auth_rate_limit_window_seconds == 30.0


def test_rate_limit_rejects_zero_max_requests(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT_MAX_REQUESTS", "0")

    with pytest.raises(ValueError, match="AUTH_RATE_LIMIT_MAX_REQUESTS must be >= 1"):
        Settings()


def test_rate_limit_rejects_non_positive_window(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "0")

    with pytest.raises(ValueError, match="AUTH_RATE_LIMIT_WINDOW_SECONDS must be > 0"):
        Settings()


def test_stream_poll_default(monkeypatch) -> None:
    monkeypatch.delenv("TELEMETRY_STREAM_POLL_SECONDS", raising=False)

    assert Settings().telemetry_stream_poll_seconds == 1.0


def test_stream_poll_env_override(monkeypatch) -> None:
    monkeypatch.setenv("TELEMETRY_STREAM_POLL_SECONDS", "0.25")

    assert Settings().telemetry_stream_poll_seconds == 0.25


def test_stream_poll_rejects_non_positive(monkeypatch) -> None:
    monkeypatch.setenv("TELEMETRY_STREAM_POLL_SECONDS", "0")

    with pytest.raises(ValueError, match="TELEMETRY_STREAM_POLL_SECONDS must be > 0"):
        Settings()
