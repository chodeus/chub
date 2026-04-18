"""
Hand-rolled in-memory token-bucket rate limiter.

Designed for a single-user self-hosted app: no Redis, no extra deps. Keys
are (endpoint, client IP). Buckets are created on first hit. Old buckets
are periodically pruned to prevent unbounded memory growth.

Use as a FastAPI dependency:

    limiter = RateLimiter(rate=5, burst=10)
    @router.post("/expensive", dependencies=[Depends(limiter)])
    async def expensive(...): ...
"""

import threading
import time
from typing import Dict, Tuple

from fastapi import HTTPException, Request


class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, tokens: float, last_refill: float) -> None:
        self.tokens = tokens
        self.last_refill = last_refill


class RateLimiter:
    """
    Token-bucket limiter keyed by (endpoint_path, client_ip).

    rate: tokens added per second.
    burst: bucket capacity (max tokens held at once).
    """

    _PRUNE_INTERVAL = 300  # seconds

    def __init__(self, rate: float, burst: int) -> None:
        if rate <= 0 or burst <= 0:
            raise ValueError("rate and burst must be positive")
        self.rate = float(rate)
        self.burst = int(burst)
        self._buckets: Dict[Tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()
        self._last_prune = time.monotonic()

    def _client_ip(self, request: Request) -> str:
        # Honor X-Forwarded-For only if nothing else is available;
        # in a homelab setup the socket peer IP is authoritative.
        return request.client.host if request.client else "unknown"

    def _prune_locked(self, now: float) -> None:
        if now - self._last_prune < self._PRUNE_INTERVAL:
            return
        stale = now - self._PRUNE_INTERVAL
        dead = [k for k, b in self._buckets.items() if b.last_refill < stale]
        for k in dead:
            del self._buckets[k]
        self._last_prune = now

    def __call__(self, request: Request) -> None:
        key = (request.url.path, self._client_ip(request))
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.burst - 1, last_refill=now)
                self._buckets[key] = bucket
                return
            elapsed = now - bucket.last_refill
            bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rate)
            bucket.last_refill = now
            if bucket.tokens < 1:
                retry_after = max(1, int((1 - bucket.tokens) / self.rate))
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.tokens -= 1


# Shared limiter instances. Local-first app — the only limiter that
# protects against a real threat model is login (password brute-force).
login_limiter = RateLimiter(rate=0.2, burst=5)  # 1 per 5s, 5 burst
