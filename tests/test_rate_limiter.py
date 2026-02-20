"""Tests for litscout.utils.rate_limiter."""

import time

from litscout.utils.rate_limiter import RateLimiter


def test_rate_limiter_no_delay_first_call():
    limiter = RateLimiter(10.0)
    start = time.monotonic()
    limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.1  # first call should be instant


def test_rate_limiter_enforces_delay():
    limiter = RateLimiter(100.0)  # 100 req/s = 0.01s between
    limiter.acquire()
    start = time.monotonic()
    limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.005  # at least close to 0.01s


def test_rate_limiter_zero_rate():
    limiter = RateLimiter(0.0)
    # Should not block
    limiter.acquire()
    limiter.acquire()
