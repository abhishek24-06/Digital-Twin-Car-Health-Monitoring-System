import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables (.env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Digital Twin API"
    app_version: str = "0.1.0"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str

    cors_origins: list[str] = ["http://localhost:3000"]

    # MQTT ingestion (Phase 2)
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    # A client id must be unique per connected process on the same broker, or
    # MQTT *session takeover* makes each new connection disconnect the previous
    # one. Fixed ids caused reconnect flaps that corrupt the Windows
    # SelectorEventLoop (WinError 10038 on select()). Default to a per-process
    # unique id; an explicit MQTT_CLIENT_ID is honored verbatim instead.
    mqtt_client_id: str = Field(default_factory=lambda: f"dtwin-sub-{uuid.uuid4().hex[:8]}")
    mqtt_keepalive: int = 60
    mqtt_qos: int = 1
    mqtt_topic_prefix: str = "vehicles"
    mqtt_reconnect_max_seconds: float = 30.0
    mqtt_message_retry_attempts: int = 3

    # Vehicle health intelligence (Phase 3)
    health_analysis_window_minutes: int = 15
    health_minimum_samples: int = 10
    health_expected_interval_seconds: float = 1.0
    health_baseline_window_minutes: int = 360
    health_baseline_minimum_samples: int = 5

    # Background health monitoring: the platform evaluates health on its own as
    # telemetry arrives instead of waiting for a human to POST /health/analyze.
    # Disabled in the test suite so tests only ever observe what they trigger.
    health_monitor_enabled: bool = True
    # The loop poll interval: a vehicle with fresh telemetry gets its first
    # snapshot within ~1 interval after the first persisted sample, so this
    # directly bounds the first-assessment latency (Phase 10).
    health_monitor_interval_seconds: float = 10.0
    # Per-vehicle floor between evaluations; telemetry at 1 Hz must not produce
    # one snapshot per second.
    health_monitor_min_seconds: float = 60.0
    # Bound on how much work a single pass may start.
    health_monitor_max_vehicles: int = 25

    # Authentication / identity (Phase 6)
    # The canonical env var is JWT_SECRET; the long field name is accepted as a
    # compatibility alias because pydantic-settings lower-cases field names.
    json_web_token_secret: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET", "json_web_token_secret"),
    )
    jwt_algorithm: str = "HS256"
    auth_access_token_minutes: int = 20
    auth_refresh_token_days: int = 30
    auth_password_min_length: int = 8
    auth_password_max_length: int = 72  # bcrypt 72-byte limit

    # Auth abuse control (Phase 6)
    # Brute-force / credential-stuffing defense for the credential endpoints.
    # Disabled in the test suite so tests that register and log in repeatedly
    # are unaffected. Credential checking is deliberately unlimited here: the
    # auth endpoints are the ones that need protection.
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_max_requests: int = 10
    auth_rate_limit_window_seconds: float = 60.0

    # Realtime delivery (Phase 3)
    # Live telemetry streams poll the repository on this cadence unless the
    # client overrides it with ?interval_seconds=.
    telemetry_stream_poll_seconds: float = 1.0

    # Simulation control
    # The API spawns per-vehicle simulator subprocesses (`python -m
    # simulator.main`). These knobs bound the lifecycle: how long a freshly
    # spawned process may run before the manager considers it started, and the
    # upper bound on a graceful stop before the process is killed outright.
    simulation_startup_grace_seconds: float = Field(default=3.0, ge=0.1, le=30.0)
    simulation_stop_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    # Directory holding per-vehicle PID markers. A restarted API reads them at
    # startup to detect and terminate simulator processes left over from a
    # previous backend run (the manager's in-memory registry is gone by then).
    simulation_runtime_dir: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "dtwin-simulations")
    )

    @model_validator(mode="after")
    def _validate_simulation_settings(self) -> "Settings":
        """Refuse an unreadable runtime marker directory."""
        if not self.simulation_runtime_dir.strip():
            raise ValueError("SIMULATION_RUNTIME_DIR must be a non-empty path")
        return self

    @model_validator(mode="after")
    def _validate_security_settings(self) -> "Settings":
        """Reject unsafe JWT secrets in non-local environments.

        The default/empty secret is intended for local development only. In any
        environment that is not local development (test, staging, production),
        refusing to start with a default/empty secret prevents a deployment
        from silently signing auth tokens with a publicly known value.
        """
        if self.app_env not in ("development", "local"):
            insecure = {
                "",
                "change-me",
                "CHANGE_ME",
                "insecure-dev-secret",
                "dev-secret",
                "jwt-secret",
                "secret",
            }
            if self.json_web_token_secret in insecure or len(self.json_web_token_secret) < 32:
                raise ValueError(
                    "JWT_SECRET must be a strong random secret (>=32 chars) in non-local "
                    "environments; refusing to start with the default/empty value"
                )
        return self

    @model_validator(mode="after")
    def _validate_health_monitor_settings(self) -> "Settings":
        """Refuse a monitoring cadence that could never run or would spin."""
        if self.health_monitor_interval_seconds <= 0:
            raise ValueError("HEALTH_MONITOR_INTERVAL_SECONDS must be > 0")
        if self.health_monitor_min_seconds < 0:
            raise ValueError("HEALTH_MONITOR_MIN_SECONDS must be >= 0")
        if self.health_monitor_max_vehicles < 1:
            raise ValueError("HEALTH_MONITOR_MAX_VEHICLES must be >= 1")
        return self

    @model_validator(mode="after")
    def _validate_rate_limit_settings(self) -> "Settings":
        """Refuse a rate limit that could never trigger or would always trigger."""
        if self.auth_rate_limit_max_requests < 1:
            raise ValueError("AUTH_RATE_LIMIT_MAX_REQUESTS must be >= 1")
        if self.auth_rate_limit_window_seconds <= 0:
            raise ValueError("AUTH_RATE_LIMIT_WINDOW_SECONDS must be > 0")
        return self

    @model_validator(mode="after")
    def _validate_stream_settings(self) -> "Settings":
        """Refuse a stream poll interval that would busy-spin or never yield."""
        if self.telemetry_stream_poll_seconds <= 0:
            raise ValueError("TELEMETRY_STREAM_POLL_SECONDS must be > 0")
        return self

    @property
    def is_debug(self) -> bool:
        return self.debug

    @property
    def sync_database_url(self) -> str:
        """PostgreSQL driver URL usable by tools that need a sync driver."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
