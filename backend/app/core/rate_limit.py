"""In-process sliding-window rate limiting for the credential endpoints.

No new dependency: a dict of deques is enough for a single process. Each named
scope (login / register / refresh) gets its own limiter instance, so one
endpoint being hammered does not starve the others. The client identity is the
socket peer address, or the leftmost ``X-Forwarded-For`` value when a reverse
proxy is in front. Behind such a proxy, only a *trusted* proxy should set that
header; production deployments must strip untrusted client-supplied values.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock

from fastapi import Request

from app.core.config import get_settings
from app.core.exceptions import RateLimitError


class RateLimiter:
    """Sliding-window limiter mapping a client key to arrival timestamps.

    Thread-safe: uvicorn may execute the FastAPI dependency in a threadpool
    thread. Bucket memory is bounded because stale hits are dropped on access
    and empty buckets are pruned.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        """Return ``(allowed, seconds_to_wait)``.

        ``seconds_to_wait`` is ``0.0`` when the request is allowed; when a
        request is rejected it is the time until the oldest arrival leaves the
        window (the value for a ``Retry-After`` header).
        """
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                retry_after = max(0.0, bucket[0] + self._window - now)
                return False, retry_after
            bucket.append(now)
            return True, 0.0

    def prune(self) -> None:
        """Drop buckets whose hits have all aged out of the window."""
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            stale = [
                key
                for key, bucket in self._hits.items()
                if not bucket or (bucket and bucket[-1] < cutoff)
            ]
            for key in stale:
                del self._hits[key]

    @property
    def bucket_count(self) -> int:
        with self._lock:
            return len(self._hits)


class RateLimitDependency:
    """FastAPI dependency enforcing a per-scope limiter for one client address.

    Settings are read on every call so configuration stays live, and the
    limiter is built on first use with the values in force at that moment.
    When rate limiting is disabled the dependency is a no-op.
    """

    def __init__(self, scope: str) -> None:
        self._scope = scope
        self._limiter: RateLimiter | None = None

    def __call__(self, request: Request) -> None:
        settings = get_settings()
        if not settings.auth_rate_limit_enabled:
            return
        if self._limiter is None:
            self._limiter = RateLimiter(
                max_requests=settings.auth_rate_limit_max_requests,
                window_seconds=settings.auth_rate_limit_window_seconds,
            )
        allowed, retry_after = self._limiter.allow(client_host(request))
        if not allowed:
            raise RateLimitError(retry_after_seconds=retry_after)


def client_host(request: Request) -> str:
    """Identity of the caller for rate limiting purposes."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"
