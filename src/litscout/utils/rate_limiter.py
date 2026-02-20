"""Token-bucket rate limiter with sync and async acquire."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """A simple token-bucket rate limiter.

    Parameters
    ----------
    requests_per_second : float
        Maximum sustained request rate.
    """

    def __init__(self, requests_per_second: float) -> None:
        self.rate = requests_per_second
        self._interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request: float = 0.0

    def acquire(self) -> None:
        """Block (synchronously) until a request slot is available."""
        if self._interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last_request = time.monotonic()

    async def acquire_async(self) -> None:
        """Block (asynchronously) until a request slot is available."""
        if self._interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self._interval:
            await asyncio.sleep(self._interval - elapsed)
        self._last_request = time.monotonic()


# Pre-configured limiters for each API source
DEFAULT_RATES: dict[str, float] = {
    "semantic_scholar": 10.0,  # with key; override to 0.8 without
    "semantic_scholar_no_key": 0.8,
    "pubmed": 8.0,  # with key
    "pubmed_no_key": 2.0,
    "unpaywall": 10.0,
    "openalex": 10.0,
}
