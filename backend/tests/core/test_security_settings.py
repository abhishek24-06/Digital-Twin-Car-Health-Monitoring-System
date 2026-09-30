"""Phase 6 security settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_BASE = {
    "app_env": "test",
    "database_url": "postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_test",
}


def _settings(**overrides) -> Settings:
    payload = {**_BASE, **overrides}
    return Settings(**payload)


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "short",
        "change-me",
        "CHANGE_ME",
        "insecure-dev-secret",
        "jwt-secret",
        "secret",
        "dev-secret",
    ],
)
def test_settings_reject_weak_secret_outside_development(secret: str) -> None:
    with pytest.raises(ValidationError):
        _settings(app_env="production", json_web_token_secret=secret)


def test_settings_reject_short_secret_outside_development() -> None:
    with pytest.raises(ValidationError):
        _settings(app_env="staging", json_web_token_secret="x" * 31)


def test_settings_accept_strong_secret_in_production() -> None:
    settings = _settings(app_env="production", json_web_token_secret="x" * 64)
    assert settings.json_web_token_secret == "x" * 64
    assert settings.jwt_algorithm == "HS256"
    assert settings.auth_access_token_minutes == 20
    assert settings.auth_refresh_token_days == 30


def test_settings_allow_insecure_secret_in_dev() -> None:
    settings = _settings(app_env="development", json_web_token_secret="")
    assert settings.json_web_token_secret == ""


def test_settings_allow_insecure_secret_in_local() -> None:
    settings = _settings(app_env="local", json_web_token_secret="local-only-secret")
    assert settings.json_web_token_secret == "local-only-secret"
