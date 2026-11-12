"""Small in-process sliding-window limiter for the single-worker deployment."""

from __future__ import annotations

import time
from collections import deque
from threading import Lock


class SlidingWindowRateLimiter:
    def __init__(self, max_buckets: int = 4096) -> None:
        self.max_buckets = max_buckets
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def retry_after(self, key: str, attempts: int, window_seconds: int) -> int | None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= attempts:
                return max(1, int(window_seconds - (now - bucket[0])) + 1)
            bucket.append(now)
            if len(self._buckets) > self.max_buckets:
                self._prune(cutoff)
        return None

    def _prune(self, cutoff: float) -> None:
        stale = [key for key, bucket in self._buckets.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            self._buckets.pop(key, None)
        while len(self._buckets) > self.max_buckets:
            self._buckets.pop(next(iter(self._buckets)))
