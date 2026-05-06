"""Very small in-memory rate limiter (offline-friendly, no external deps).

Used for:
- login attempt throttling per IP
- API throttling per IP

Note: This is a best-effort protection for a demo/offline system. It resets on app restart.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic


@dataclass
class RateLimit:
    limit: int
    per_seconds: int


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str, *, limit: int, per_seconds: int) -> bool:
        now = monotonic()
        q = self._events.setdefault(key, deque())
        window_start = now - float(per_seconds)
        while q and q[0] < window_start:
            q.popleft()
        if len(q) >= int(limit):
            return False
        q.append(now)
        return True


limiter = RateLimiter()
