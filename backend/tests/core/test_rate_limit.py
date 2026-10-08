"""Unit tests for the sliding-window rate limiter."""

from __future__ import annotations

from app.core.rate_limit import RateLimiter


class _FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_max_requests_then_blocks() -> None:
    limiter = RateLimiter(max_requests=3, window_seconds=60.0)

    assert limiter.allow("203.0.113.7") == (True, 0.0)
    assert limiter.allow("203.0.113.7") == (True, 0.0)
    assert limiter.allow("203.0.113.7") == (True, 0.0)

    allowed, retry_after = limiter.allow("203.0.113.7")
    assert allowed is False
    assert retry_after > 0


def test_clients_are_isolated() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60.0)

    assert limiter.allow("a")[0] is True
    assert limiter.allow("b")[0] is True
    assert limiter.allow("a")[0] is False


def test_retry_after_tracks_oldest_arrival() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=2, window_seconds=10.0, clock=clock)

    limiter.allow("ip")
    clock.now += 2.0
    limiter.allow("ip")

    allowed, retry_after = limiter.allow("ip")
    assert allowed is False
    # Oldest arrival (at t=1000) falls out of the window at t=1010, which is
    # 8 seconds from now (t=1002).
    assert retry_after == 8.0


def test_window_slides_and_recovers_after_expiry() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=2, window_seconds=10.0, clock=clock)

    limiter.allow("ip")
    limiter.allow("ip")
    assert limiter.allow("ip")[0] is False

    # Advance past the whole window: the bucket drains and requests resume.
    clock.now += 10.0001
    assert limiter.allow("ip")[0] is True


def test_prune_removes_aged_out_buckets() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=10.0, clock=clock)

    limiter.allow("gone")
    assert limiter.bucket_count == 1

    clock.now += 100.0  # the only hit is now far outside the window
    limiter.prune()

    assert limiter.bucket_count == 0
