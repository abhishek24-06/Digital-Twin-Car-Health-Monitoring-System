import uuid
from functools import lru_cache

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
