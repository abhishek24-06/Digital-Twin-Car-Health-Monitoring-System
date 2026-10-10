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
    mqtt_client_id: str = Field(default_factory=lambda: f"dtwin-sub-{uuid.uuid4().hex[:8]}")
    mqtt_keepalive: int = 60
    mqtt_qos: int = 1
    mqtt_topic_prefix: str = "vehicles"
    mqtt_reconnect_max_seconds: float = 30.0
    mqtt_message_retry_attempts: int = 3
    # Per-message persistence costs several database round trips. Over a
    # high-latency database a serial subscriber cannot keep up with multiple
    # publishers, so a backlog builds and telemetry lands already older than the
    # health window. Consume a bounded batch and persist it in one statement
    # instead. ``mqtt_batch_flush_seconds`` bounds latency when the feed is idle.
    mqtt_batch_max_messages: int = Field(default=250, ge=1, le=5000)
    mqtt_batch_flush_seconds: float = Field(default=0.25, gt=0, le=10.0)

    # Vehicle health intelligence (Phase 3)
    health_analysis_window_minutes: int = 15
    health_minimum_samples: int = 10
    health_expected_interval_seconds: float = 1.0
    health_baseline_window_minutes: int = 360
    health_baseline_minimum_samples: int = 5

    # Background health monitoring
    health_monitor_enabled: bool = True
    health_monitor_interval_seconds: float = 10.0
    health_monitor_min_seconds: float = 60.0
    health_monitor_max_vehicles: int = 25

    # Authentication / identity (Phase 6)
    json_web_token_secret: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET", "json_web_token_secret"),
    )
    jwt_algorithm: str = "HS256"
    auth_access_token_minutes: int = 20
    auth_refresh_token_days: int = 30
    auth_password_min_length: int = 8
    auth_password_max_length: int = 72

    # Auth abuse control
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_max_requests: int = 10
    auth_rate_limit_window_seconds: float = 60.0

    # Realtime delivery
    telemetry_stream_poll_seconds: float = 1.0

    # Simulation control
    simulation_startup_grace_seconds: float = Field(default=3.0, ge=0.1, le=30.0)
    simulation_stop_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    simulation_runtime_dir: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "dtwin-simulations")
    )

    # Workflow observability (Phase 7)
    workflow_event_buffer_size: int = Field(default=500, ge=50, le=5000)
    workflow_max_subscribers: int = Field(default=50, ge=5, le=200)
    workflow_sse_heartbeat_seconds: int = Field(default=15, ge=5, le=120)

    @model_validator(mode="after")
    def _validate_simulation_settings(self) -> "Settings":
        if not self.simulation_runtime_dir.strip():
            raise ValueError("SIMULATION_RUNTIME_DIR must be a non-empty path")
        return self

    @model_validator(mode="after")
    def _validate_security_settings(self) -> "Settings":
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
        if self.health_monitor_interval_seconds <= 0:
            raise ValueError("HEALTH_MONITOR_INTERVAL_SECONDS must be > 0")
        if self.health_monitor_min_seconds < 0:
            raise ValueError("HEALTH_MONITOR_MIN_SECONDS must be >= 0")
        if self.health_monitor_max_vehicles < 1:
            raise ValueError("HEALTH_MONITOR_MAX_VEHICLES must be >= 1")
        return self

    @model_validator(mode="after")
    def _validate_rate_limit_settings(self) -> "Settings":
        if self.auth_rate_limit_max_requests < 1:
            raise ValueError("AUTH_RATE_LIMIT_MAX_REQUESTS must be >= 1")
        if self.auth_rate_limit_window_seconds <= 0:
            raise ValueError("AUTH_RATE_LIMIT_WINDOW_SECONDS must be > 0")
        return self

    @model_validator(mode="after")
    def _validate_stream_settings(self) -> "Settings":
        if self.telemetry_stream_poll_seconds <= 0:
            raise ValueError("TELEMETRY_STREAM_POLL_SECONDS must be > 0")
        return self

    @model_validator(mode="after")
    def _validate_workflow_settings(self) -> "Settings":
        if self.workflow_event_buffer_size < 50:
            raise ValueError("WORKFLOW_EVENT_BUFFER_SIZE must be >= 50")
        if self.workflow_max_subscribers < 5:
            raise ValueError("WORKFLOW_MAX_SUBSCRIBERS must be >= 5")
        if self.workflow_sse_heartbeat_seconds < 5:
            raise ValueError("WORKFLOW_SSE_HEARTBEAT_SECONDS must be >= 5")
        return self

    @property
    def is_debug(self) -> bool:
        return self.debug

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
