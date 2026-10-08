"""Sliding-window rate limit per client IP, to protect the LLM quota on a public demo."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_hour: int, window_s: float = 3600.0):
        self.per_hour = per_hour
        self.window = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, seconds until the next slot frees up)."""
        if self.per_hour <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.per_hour:
                return False, int(self.window - (now - q[0])) + 1
            q.append(now)
            return True, 0
