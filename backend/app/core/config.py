from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables (.env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
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
    mqtt_client_id: str = "digital-twin-subscriber"
    mqtt_keepalive: int = 60
    mqtt_qos: int = 1
    mqtt_topic_prefix: str = "vehicles"
    mqtt_reconnect_max_seconds: float = 30.0
    mqtt_message_retry_attempts: int = 3

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
