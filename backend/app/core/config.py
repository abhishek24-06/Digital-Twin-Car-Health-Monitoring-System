import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Environments where the operator is on a trusted local machine. Outside these,
# settings that are merely convenient locally are refused: a weak JWT secret and
# the built-in localhost-only CORS origin list are otherwise silent
# misconfigurations in a deployed API.
_PERMISSIVE_ENVS = frozenset({"development", "local", "test"})

# Placeholder / guessable secrets. Rejected everywhere unless the operator
# explicitly opts in with ``auth_allow_insecure_dev_secret``.
_INSECURE_JWT_SECRETS = frozenset(
    {
        "",
        "change-me",
        "change_me",
        "insecure-dev-secret",
        "jwt-secret",
        "secret",
        "dev-secret",
    }
)

# The built-in localhost-only origin list. Outside permissive environments this
# default is a misconfiguration: a deployed API must declare its origins.
_DEFAULT_CORS_ORIGINS = ("http://localhost:3000",)


def _is_weak_jwt_secret(secret: str) -> bool:
    """A secret shorter than 32 chars or an obvious placeholder is weak."""
    return len(secret) < 32 or secret.lower() in _INSECURE_JWT_SECRETS


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

    # Deployment verification (Phase B). ``build_id`` is stamped by the
    # deployment (git SHA, image tag, ...) so a running server can be matched to
    # the artifact it came from. ``expected_schema_revision`` is the Alembic
    # revision this build targets; when set, the deployment-status endpoint
    # compares it with the database's recorded revision and reports drift
    # without ever applying a migration.
    build_id: str = "unknown"
    expected_schema_revision: str | None = None

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

    # Live current-session evaluation policy (current run only). These gate a
    # *definitive* live assessment: until the active run supplies at least
    # ``live_health_minimum_samples`` current-run samples spanning at least
    # ``live_health_minimum_duration_seconds``, covering at least
    # ``live_health_minimum_coverage`` of its observation window, with a latest
    # sample no older than ``live_health_max_sample_age_seconds``, the
    # assessment stays provisional (collecting_data / limited_data). A run of
    # ~1 sample/s typically clears the gate after ~30s of fresh data.
    live_health_minimum_samples: int = Field(default=30, ge=1)
    live_health_minimum_duration_seconds: float = Field(default=30.0, gt=0)
    live_health_minimum_coverage: float = Field(default=0.5, gt=0, le=1.0)
    live_health_max_sample_age_seconds: float = Field(default=15.0, gt=0)

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
    # Development-only escape hatch: Weak/empty JWT secrets are refused by
    # default (fail closed) even in development/local. A developer who
    # deliberately wants the insecure default must opt in explicitly.
    auth_allow_insecure_dev_secret: bool = False

    # Auth abuse control
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_max_requests: int = 10
    auth_rate_limit_window_seconds: float = 60.0

    # Manual analysis-trigger abuse control (Phase A). POST /health/analyze runs
    # two wide telemetry range scans plus a full deterministic analysis and
    # writes a snapshot per call, so a single client can amplify database and
    # CPU load by hammering it. This is a per-authenticated-user budget, kept
    # separate from the credential-endpoint limiter.
    analysis_rate_limit_enabled: bool = True
    analysis_rate_limit_max_requests: int = 10
    analysis_rate_limit_window_seconds: float = 60.0

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
    # Durable audit copy of workflow events (bounded by age). The in-memory
    # buffer remains the live feed; this survives restarts for post-incident
    # review and is pruned to ``workflow_event_retention_hours``.
    workflow_event_persistence_enabled: bool = True
    workflow_event_retention_hours: float = Field(default=72.0, gt=0)

    @model_validator(mode="after")
    def _validate_simulation_settings(self) -> "Settings":
        if not self.simulation_runtime_dir.strip():
            raise ValueError("SIMULATION_RUNTIME_DIR must be a non-empty path")
        return self

    @model_validator(mode="after")
    def _validate_security_settings(self) -> "Settings":
        if _is_weak_jwt_secret(self.json_web_token_secret):
            # Fail closed: a weak secret is tolerated only on a permissive
            # environment *and* only when the operator explicitly opts in.
            if not (self.app_env in _PERMISSIVE_ENVS and self.auth_allow_insecure_dev_secret):
                raise ValueError(
                    "JSON_WEB_TOKEN_SECRET is missing or too weak (need >= 32 "
                    "random characters). Set JWT_SECRET, or -- for local "
                    "development only -- set AUTH_ALLOW_INSECURE_DEV_SECRET=true "
                    "to accept the insecure development default."
                )

        if self.app_env not in _PERMISSIVE_ENVS and (
            not self.cors_origins or tuple(self.cors_origins) == _DEFAULT_CORS_ORIGINS
        ):
            raise ValueError(
                "CORS_ORIGINS must be set explicitly outside development: the "
                "built-in localhost-only default is refused. Provide the "
                "comma-separated list of allowed origins."
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
        if self.live_health_minimum_samples < 1:
            raise ValueError("LIVE_HEALTH_MINIMUM_SAMPLES must be >= 1")
        if self.live_health_minimum_duration_seconds <= 0:
            raise ValueError("LIVE_HEALTH_MINIMUM_DURATION_SECONDS must be > 0")
        if not 0 < self.live_health_minimum_coverage <= 1.0:
            raise ValueError("LIVE_HEALTH_MINIMUM_COVERAGE must be in (0, 1]")
        if self.live_health_max_sample_age_seconds <= 0:
            raise ValueError("LIVE_HEALTH_MAX_SAMPLE_AGE_SECONDS must be > 0")
        return self

    @model_validator(mode="after")
    def _validate_rate_limit_settings(self) -> "Settings":
        if self.auth_rate_limit_max_requests < 1:
            raise ValueError("AUTH_RATE_LIMIT_MAX_REQUESTS must be >= 1")
        if self.auth_rate_limit_window_seconds <= 0:
            raise ValueError("AUTH_RATE_LIMIT_WINDOW_SECONDS must be > 0")
        if self.analysis_rate_limit_max_requests < 1:
            raise ValueError("ANALYSIS_RATE_LIMIT_MAX_REQUESTS must be >= 1")
        if self.analysis_rate_limit_window_seconds <= 0:
            raise ValueError("ANALYSIS_RATE_LIMIT_WINDOW_SECONDS must be > 0")
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
