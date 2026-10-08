"""Rate-limit dependency enforcement tests.

The rate limiter is verified end-to-end against a real FastAPI app only when
the suite is run with ``AUTH_RATE_LIMIT_ENABLED=true``. By default conftest
disables it (many tests register and log in repeatedly), so these tests drive
the dependency directly with an injected fake Request and a monkeypatched
settings source instead.
"""

from __future__ import annotations

import pytest
from fastapi import Request

from app.core.config import get_settings
from app.core.exceptions import RateLimitError
from app.core.rate_limit import RateLimitDependency, client_host


def _fake_request(host: str = "203.0.113.7", *, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "raw_path": b"/api/v1/auth/login",
        "query_string": b"",
        "headers": headers,
        "client": (host, 4567),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
    }
    return Request(scope)


def _patched_dependency(monkeypatch, *, enabled: bool = True) -> RateLimitDependency:
    from app.core import rate_limit as rl

    settings = get_settings().model_copy(
        update={
            "auth_rate_limit_enabled": enabled,
            "auth_rate_limit_max_requests": 2,
            "auth_rate_limit_window_seconds": 60.0,
        }
    )
    monkeypatch.setattr(rl, "get_settings", lambda: settings)
    return RateLimitDependency("auth:test")


def test_dependency_blocks_after_limit(monkeypatch) -> None:
    dep = _patched_dependency(monkeypatch)
    request = _fake_request()

    dep(request)
    dep(request)

    with pytest.raises(RateLimitError) as exc_info:
        dep(request)
    assert exc_info.value.retry_after_seconds > 0


def test_dependency_is_a_no_op_when_disabled(monkeypatch) -> None:
    dep = _patched_dependency(monkeypatch, enabled=False)
    request = _fake_request()

    for _ in range(100):
        dep(request)  # must never raise


def test_client_host_prefers_forwarded_header() -> None:
    assert client_host(_fake_request("10.0.0.5", forwarded="198.51.100.9, 10.0.0.1")) == (
        "198.51.100.9"
    )


def test_client_host_falls_back_to_peer() -> None:
    assert client_host(_fake_request("198.51.100.9")) == "198.51.100.9"


async def test_rate_limit_error_handler_sets_retry_after_header() -> None:
    from app.main import app

    handler = app.exception_handlers[RateLimitError]

    response = await handler(_fake_request(), RateLimitError(retry_after_seconds=8.0))
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "8"

    # A sub-second wait still yields a whole-number header.
    response = await handler(_fake_request(), RateLimitError(retry_after_seconds=0.4))
    assert response.headers["Retry-After"] == "1"
