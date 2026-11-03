"""Thin Redis wrapper. Every function fails open: if Redis is slow or down,
the caller sees a cache miss, never an exception."""

import json
import logging
from functools import lru_cache
from typing import Any

import redis

from critisizer.config import get_settings

log = logging.getLogger(__name__)

# Short timeouts: a dead Redis must cost milliseconds, not hang the request.
_TIMEOUT_SECONDS = 0.2


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=_TIMEOUT_SECONDS,
        socket_timeout=_TIMEOUT_SECONDS,
    )


def get_json(key: str) -> Any | None:
    """Return the cached value, or None on a miss or any Redis/JSON error."""
    try:
        raw = get_redis().get(key)
        return None if raw is None else json.loads(raw)
    except (redis.RedisError, ValueError):
        log.warning("cache read failed for %s", key, exc_info=True)
        return None


def set_json(key: str, value: Any, ttl_seconds: int) -> bool:
    """Store value with an expiry. Returns False if it could not be stored."""
    try:
        get_redis().set(key, json.dumps(value), ex=ttl_seconds)
        return True
    except (redis.RedisError, TypeError, ValueError):
        log.warning("cache write failed for %s", key, exc_info=True)
        return False


def delete(key: str) -> None:
    try:
        get_redis().delete(key)
    except redis.RedisError:
        log.warning("cache delete failed for %s", key, exc_info=True)
