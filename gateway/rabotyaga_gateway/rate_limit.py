from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimit:
    bucket: str
    key: str
    limit: int
    window_seconds: int


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__("rate limit exceeded")
        self.retry_after = max(1, retry_after)


class SlidingWindowLimiter:
    """Small in-memory limiter for the single-process local bridge.

    The limiter stores only ephemeral bucket identifiers and timestamps. It does
    not persist client addresses, device identifiers, request bodies or secrets.
    """

    def __init__(self, *, max_buckets: int = 10_000):
        self._events: dict[tuple[str, str, int, int], deque[float]] = {}
        self._last_seen: dict[tuple[str, str, int, int], float] = {}
        self._lock = threading.Lock()
        self._max_buckets = max_buckets

    def check(self, limits: list[RateLimit], *, now: float | None = None) -> None:
        instant = time.monotonic() if now is None else now
        with self._lock:
            prepared: list[tuple[tuple[str, str, int, int], deque[float], RateLimit]] = []
            retry_after = 0
            for limit in limits:
                bucket_key = (limit.bucket, limit.key, limit.limit, limit.window_seconds)
                events = self._events.setdefault(bucket_key, deque())
                cutoff = instant - limit.window_seconds
                while events and events[0] <= cutoff:
                    events.popleft()
                self._last_seen[bucket_key] = instant
                prepared.append((bucket_key, events, limit))
                if len(events) >= limit.limit:
                    retry_after = max(
                        retry_after,
                        math.ceil(events[0] + limit.window_seconds - instant),
                    )

            if retry_after:
                raise RateLimitExceeded(retry_after)

            for _, events, _ in prepared:
                events.append(instant)

            if len(self._events) > self._max_buckets:
                self._prune(instant)

    def _prune(self, now: float) -> None:
        stale = sorted(self._last_seen, key=self._last_seen.get)
        remove_count = max(1, len(stale) - self._max_buckets // 2)
        for key in stale[:remove_count]:
            self._events.pop(key, None)
            self._last_seen.pop(key, None)
