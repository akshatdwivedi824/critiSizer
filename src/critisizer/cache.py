"""Thin Redis wrapper. Every function fails open: if Redis is slow or down,
the caller sees a cache miss, never an exception.

A circuit breaker sits in front of Redis. After FAILURE_THRESHOLD consecutive
failures it opens, and every call returns its fallback immediately for
COOLDOWN_SECONDS, so a dead Redis costs one burst of timeouts instead of a
timeout on every request. After the cool-off one call is let through as a probe:
success closes the breaker, failure reopens it.

Readiness checks call get_redis() directly and bypass the breaker on purpose, so
they report the real state. While the breaker is open, rate limiting is off and
cache invalidation is skipped (both already failed open when Redis was down).
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from critisizer.config import get_settings

log = logging.getLogger(__name__)

# Short timeouts: a dead Redis must cost milliseconds, not hang the request.
_TIMEOUT_SECONDS = 0.2

# Every cached policy list starts with this; the rubric label follows.
LIST_CACHE_PREFIX = "policies:list:v1:"

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 30.0


class CircuitBreaker:
    def __init__(
        self,
        threshold: int = FAILURE_THRESHOLD,
        cooldown: float = COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at: float | None = None
            self._probing = False
            self._trips = 0
            self._skipped = 0
            self._failures_total = 0

    def allow(self) -> bool:
        """True if a Redis call may be attempted now."""
        with self._lock:
            if self._opened_at is None:
                return True
            if not self._probing and self._clock() - self._opened_at >= self._cooldown:
                self._probing = True  # half-open: exactly one probe at a time
                return True
            self._skipped += 1
            return False

    def success(self) -> None:
        with self._lock:
            was_open = self._opened_at is not None
            self._failures = 0
            self._opened_at = None
            self._probing = False
        if was_open:
            log.info("cache circuit closed: Redis answered")

    def failure(self) -> None:
        opened = False
        with self._lock:
            self._failures += 1
            self._failures_total += 1
            if self._opened_at is None:
                if self._failures < self._threshold:
                    return
                self._trips += 1
                self._opened_at = self._clock()
                opened = True
            elif self._probing:
                # The probe failed: start a new cool-off.
                self._opened_at = self._clock()
                self._probing = False
            # Otherwise this is a late failure from a call that started before the
            # breaker opened; it must not extend the cool-off.
            failures = self._failures
        if opened:
            log.warning(
                "cache circuit opened after %d failures; skipping Redis for %.0fs",
                failures,
                self._cooldown,
            )

    def abort_probe(self) -> None:
        """A probe ended in a non-Redis error; allow another probe."""
        with self._lock:
            self._probing = False

    def stats(self) -> dict[str, Any]:
        with self._lock:
            if self._opened_at is None:
                state = "closed"
            elif self._probing or self._clock() - self._opened_at >= self._cooldown:
                state = "half_open"
            else:
                state = "open"
            return {
                "state": state,
                "trips": self._trips,
                "skipped_calls": self._skipped,
                "failures": self._failures_total,
            }


breaker = CircuitBreaker()


def stats() -> dict[str, Any]:
    return breaker.stats()


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=_TIMEOUT_SECONDS,
        socket_timeout=_TIMEOUT_SECONDS,
        retry=Retry(NoBackoff(), 0),  # fail fast: one try, no retries
    )


def _guarded(operation: str, call: Callable[[], Any], fallback: Any) -> Any:
    """Run one Redis operation through the breaker; return fallback on failure."""
    if not breaker.allow():
        return fallback
    try:
        result = call()
    except redis.RedisError:
        breaker.failure()
        log.warning("cache %s failed", operation, exc_info=True)
        return fallback
    except BaseException:
        breaker.abort_probe()
        raise
    breaker.success()
    return result


def get_json(key: str) -> Any | None:
    """Return the cached value, or None on a miss or any Redis/JSON error."""
    raw = _guarded("read", lambda: get_redis().get(key), None)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        log.warning("cached value for %s is not valid JSON", key, exc_info=True)
        return None


def set_json(key: str, value: Any, ttl_seconds: int) -> bool:
    """Store value with an expiry. Returns False if it could not be stored."""
    try:
        payload = json.dumps(value)
    except (TypeError, ValueError):
        log.warning("cache write failed for %s", key, exc_info=True)
        return False
    stored = _guarded(
        "write", lambda: get_redis().set(key, payload, ex=ttl_seconds), False
    )
    return bool(stored)


def delete(key: str) -> None:
    _guarded("delete", lambda: get_redis().delete(key), None)


def delete_prefix(prefix: str) -> int:
    """Delete every key that starts with prefix. Returns how many were deleted;
    0 if Redis is down (logged, never raised)."""

    def run() -> int:
        client = get_redis()
        keys = list(client.scan_iter(match=f"{prefix}*", count=100))
        return int(client.delete(*keys)) if keys else 0

    return int(_guarded("delete_prefix", run, 0))


def hit_rate_limit(key: str, limit: int, window_seconds: int) -> int | None:
    """Count one attempt in a fixed window.

    Returns None if the attempt is allowed, or the number of seconds to wait
    if the limit is exceeded. Fails open (returns None) if Redis is down.
    """

    def run() -> tuple[int, int]:
        pipe = get_redis().pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)  # set the TTL only on the first hit
        pipe.ttl(key)
        count, _, ttl = pipe.execute()
        return count, ttl

    outcome = _guarded("rate limit", run, None)
    if outcome is None:
        return None
    count, ttl = outcome
    if count > limit:
        return max(int(ttl), 1)
    return None