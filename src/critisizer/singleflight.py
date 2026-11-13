"""Single-flight: when many requests miss the same cache key at once, one of them
computes the value and the rest wait for it, instead of all hitting the database.

Per process only. Render runs one worker, so that is one computation per key; with
several processes there would be at most one per process. A follower that waits
longer than wait_seconds, or whose leader failed, computes the value itself, so a
slow or broken leader can never block other requests for long.
"""

import threading
from collections.abc import Callable
from typing import Any

WAIT_SECONDS = 5.0


class _Flight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class SingleFlight:
    def __init__(self, wait_seconds: float = WAIT_SECONDS) -> None:
        self._wait_seconds = wait_seconds
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._flights: dict[str, _Flight] = {}
            self._leaders = 0
            self._coalesced = 0
            self._wait_timeouts = 0

    def run(self, key: str, compute: Callable[[], Any]) -> Any:
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = self._flights[key] = _Flight()
                self._leaders += 1
            else:
                self._coalesced += 1
        if leader:
            return self._lead(key, flight, compute)
        if flight.done.wait(self._wait_seconds):
            if flight.error is None:
                return flight.result
        else:
            with self._lock:
                self._wait_timeouts += 1
        return compute()

    def _lead(self, key: str, flight: _Flight, compute: Callable[[], Any]) -> Any:
        try:
            flight.result = compute()
            return flight.result
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                if self._flights.get(key) is flight:
                    del self._flights[key]
            flight.done.set()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "leaders": self._leaders,
                "coalesced": self._coalesced,
                "wait_timeouts": self._wait_timeouts,
                "in_flight": len(self._flights),
            }


flights = SingleFlight()