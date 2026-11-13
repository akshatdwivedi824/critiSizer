"""Request logging and in-memory metrics.

Every request gets an X-Request-ID, one JSON log line and a metrics entry. The
route is recorded as its template ("/policies/{slug}"), never the raw path, so
metrics cannot grow without limit. Query strings, request bodies and the
Authorization header are never logged.

Metrics live in this process's memory. They reset when the service restarts or
spins down, and each worker process keeps its own (Render runs one).
"""

import json
import logging
import math
import re
import sys
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from critisizer import cache
from critisizer.admin import require_admin
from critisizer.singleflight import flights

REQUEST_LOGGER = "critisizer.request"
QUIET_ROUTES = {"/health", "/health/ready"}
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
SAMPLES = 500
_ID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class _StdoutHandler(logging.StreamHandler):
    """Writes to whatever sys.stdout is at emit time (safe under test capture)."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self):
        return sys.stdout


def configure_logging() -> None:
    logger = logging.getLogger(REQUEST_LOGGER)
    if logger.handlers:
        return
    handler = _StdoutHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._started = time.time()
            self._routes: dict[str, dict[str, Any]] = {}

    def record(
        self, method: str, route: str, status: int, ms: float, cache: str | None
    ) -> None:
        if method not in METHODS:
            method = "OTHER"
        key = f"{method} {route}"
        with self._lock:
            row = self._routes.get(key)
            if row is None:
                row = self._routes[key] = {
                    "count": 0,
                    "statuses": {},
                    "cache_hits": 0,
                    "cache_misses": 0,
                    "total_ms": 0.0,
                    "max_ms": 0.0,
                    "samples": deque(maxlen=SAMPLES),
                }
            row["count"] += 1
            klass = f"{status // 100}xx"
            row["statuses"][klass] = row["statuses"].get(klass, 0) + 1
            if cache == "HIT":
                row["cache_hits"] += 1
            elif cache == "MISS":
                row["cache_misses"] += 1
            row["total_ms"] += ms
            row["max_ms"] = max(row["max_ms"], ms)
            row["samples"].append(ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            routes = {key: _summarise(row) for key, row in sorted(self._routes.items())}
            started = self._started
        return {
            "since": datetime.fromtimestamp(started, UTC).isoformat(),
            "uptime_seconds": round(time.time() - started),
            "note": "In memory; resets when the service restarts or spins down.",
            "totals": {
                "requests": sum(r["count"] for r in routes.values()),
                "server_errors": sum(r["statuses"].get("5xx", 0) for r in routes.values()),
            },
            "routes": routes,
        }


def _summarise(row: dict[str, Any]) -> dict[str, Any]:
    ordered = sorted(row["samples"])
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else 0.0
    return {
        "count": row["count"],
        "statuses": dict(sorted(row["statuses"].items())),
        "cache_hits": row["cache_hits"],
        "cache_misses": row["cache_misses"],
        "avg_ms": round(row["total_ms"] / row["count"], 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(row["max_ms"], 2),
    }


metrics = Metrics()


def _request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            if _ID_OK.match(candidate):
                return candidate
            break
    return uuid.uuid4().hex


def _finish(scope: Scope, request_id: str, seen: dict[str, Any], ms: float) -> None:
    route = getattr(scope.get("route"), "path", None) or "unmatched"
    if route in QUIET_ROUTES:
        return
    method = scope.get("method", "GET")
    if method not in METHODS:
        method = "OTHER"
    metrics.record(method, route, seen["status"], ms, seen["cache"])
    line: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "request_id": request_id,
        "method": method,
        "route": route,
        "path": scope.get("path", "")[:200],
        "status": seen["status"],
        "ms": round(ms, 1),
    }
    if seen["cache"]:
        line["cache"] = seen["cache"]
    logging.getLogger(REQUEST_LOGGER).info(json.dumps(line, separators=(",", ":")))


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _request_id(scope)
        started = time.perf_counter()
        seen: dict[str, Any] = {"status": 500, "cache": None}

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                seen["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                seen["cache"] = headers.get("x-cache")
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            try:
                _finish(scope, request_id, seen, (time.perf_counter() - started) * 1000)
            except Exception:
                logging.getLogger(__name__).exception("request logging failed")


router = APIRouter()


@router.get("/metrics", dependencies=[Depends(require_admin)], include_in_schema=False)
def metrics_endpoint() -> dict[str, Any]:
    """Admin-only request counts and latency, from this process's memory."""
    return {
        **metrics.snapshot(),
        "cache": cache.stats(),
        "single_flight": flights.stats(),
    }