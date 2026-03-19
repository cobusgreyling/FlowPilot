"""Per-connector rate limiter.

Enforces API rate limits to prevent hitting service quotas.
Supports both token bucket and sliding window strategies.
"""

from __future__ import annotations

import asyncio
import time
import threading
from collections import deque
from dataclasses import dataclass, field


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a connector."""
    connector: str
    max_requests: int
    window_seconds: float
    burst_limit: int | None = None  # Max burst above steady rate

    @property
    def rate_per_second(self) -> float:
        return self.max_requests / self.window_seconds


# Default rate limits for known services
DEFAULT_LIMITS = {
    "slack": RateLimitConfig("slack", max_requests=1, window_seconds=1.0),
    "github": RateLimitConfig("github", max_requests=5000, window_seconds=3600, burst_limit=100),
    "email": RateLimitConfig("email", max_requests=10, window_seconds=60),
    "http": RateLimitConfig("http", max_requests=100, window_seconds=60),
    "ai": RateLimitConfig("ai", max_requests=50, window_seconds=60),
}


class SlidingWindowLimiter:
    """Sliding window rate limiter for a single connector."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._total_requests = 0
        self._total_throttled = 0

    def acquire(self) -> bool:
        """Try to acquire a request slot. Returns True if allowed."""
        now = time.monotonic()
        cutoff = now - self.config.window_seconds

        with self._lock:
            # Remove expired timestamps
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

            if len(self._timestamps) < self.config.max_requests:
                self._timestamps.append(now)
                self._total_requests += 1
                return True

            self._total_throttled += 1
            return False

    async def acquire_async(self) -> None:
        """Wait until a request slot is available."""
        while not self.acquire():
            # Calculate wait time until oldest request expires
            if self._timestamps:
                wait = self._timestamps[0] + self.config.window_seconds - time.monotonic()
                await asyncio.sleep(max(0.01, wait))
            else:
                await asyncio.sleep(0.01)

    @property
    def current_usage(self) -> int:
        """Number of requests in the current window."""
        now = time.monotonic()
        cutoff = now - self.config.window_seconds
        with self._lock:
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            return len(self._timestamps)

    @property
    def remaining(self) -> int:
        """Remaining requests in the current window."""
        return max(0, self.config.max_requests - self.current_usage)

    def get_stats(self) -> dict:
        return {
            "connector": self.config.connector,
            "limit": self.config.max_requests,
            "window_seconds": self.config.window_seconds,
            "current_usage": self.current_usage,
            "remaining": self.remaining,
            "total_requests": self._total_requests,
            "total_throttled": self._total_throttled,
        }


class RateLimiter:
    """Manages rate limiters for all connectors."""

    def __init__(self, custom_limits: dict[str, RateLimitConfig] | None = None):
        self._limiters: dict[str, SlidingWindowLimiter] = {}
        limits = dict(DEFAULT_LIMITS)
        if custom_limits:
            limits.update(custom_limits)
        for name, config in limits.items():
            self._limiters[name] = SlidingWindowLimiter(config)

    def get_limiter(self, connector: str) -> SlidingWindowLimiter | None:
        return self._limiters.get(connector)

    def acquire(self, connector: str) -> bool:
        """Try to acquire a request slot for a connector."""
        limiter = self._limiters.get(connector)
        if not limiter:
            return True  # No limit configured
        return limiter.acquire()

    async def acquire_async(self, connector: str) -> None:
        """Wait for a request slot for a connector."""
        limiter = self._limiters.get(connector)
        if limiter:
            await limiter.acquire_async()

    def set_limit(self, connector: str, max_requests: int, window_seconds: float) -> None:
        """Set or update a rate limit."""
        config = RateLimitConfig(connector, max_requests, window_seconds)
        self._limiters[connector] = SlidingWindowLimiter(config)

    def get_all_stats(self) -> list[dict]:
        return [l.get_stats() for l in self._limiters.values()]
