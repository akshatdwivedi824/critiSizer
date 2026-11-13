import threading
import time

import pytest
import redis
from factories import CODES, fill_policy, make_aspects

from critisizer import cache
from critisizer.cache import CircuitBreaker
from critisizer.cache import get_redis as real_get_redis
from critisizer.singleflight import SingleFlight


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _breaker(clock):
    return CircuitBreaker(threshold=3, cooldown=30.0, clock=clock)


def _trip(breaker):
    for _ in range(3):
        breaker.failure()


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


@pytest.fixture
def policy(session):
    aspects = make_aspects(session)
    return fill_policy(session, aspects, "cached", {c: (40, [1.0]) for c in CODES})


@pytest.fixture
def dead_redis_calls(monkeypatch):
    calls = {"n": 0}

    class Dead:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                calls["n"] += 1
                raise redis.ConnectionError("redis is down (test)")

            return fail

    monkeypatch.setattr(cache, "get_redis", lambda: Dead())
    return calls


# ---- circuit breaker ----


def test_breaker_stays_closed_below_the_threshold():
    breaker = _breaker(Clock())
    breaker.failure()
    breaker.failure()
    assert breaker.allow() is True
    assert breaker.stats()["state"] == "closed"


def test_a_success_resets_the_consecutive_count():
    breaker = _breaker(Clock())
    breaker.failure()
    breaker.failure()
    breaker.success()
    breaker.failure()
    breaker.failure()
    assert breaker.allow() is True


def test_breaker_opens_at_the_threshold_and_skips_calls():
    breaker = _breaker(Clock())
    _trip(breaker)
    assert breaker.allow() is False
    assert breaker.allow() is False
    stats = breaker.stats()
    assert stats["state"] == "open"
    assert stats["trips"] == 1
    assert stats["skipped_calls"] == 2


def test_after_the_cooldown_exactly_one_probe_is_allowed():
    clock = Clock()
    breaker = _breaker(clock)
    _trip(breaker)
    clock.now += 30
    assert breaker.allow() is True
    assert breaker.allow() is False
    assert breaker.stats()["state"] == "half_open"


def test_a_successful_probe_closes_the_breaker():
    clock = Clock()
    breaker = _breaker(clock)
    _trip(breaker)
    clock.now += 30
    assert breaker.allow() is True
    breaker.success()
    assert breaker.allow() is True
    assert breaker.stats()["state"] == "closed"


def test_a_failed_probe_starts_a_new_cooldown():
    clock = Clock()
    breaker = _breaker(clock)
    _trip(breaker)
    clock.now += 30
    assert breaker.allow() is True
    breaker.failure()
    assert breaker.allow() is False
    clock.now += 29
    assert breaker.allow() is False
    clock.now += 1
    assert breaker.allow() is True
    assert breaker.stats()["trips"] == 1


def test_a_late_failure_does_not_extend_the_cooldown():
    clock = Clock()
    breaker = _breaker(clock)
    _trip(breaker)
    clock.now += 20
    breaker.failure()
    clock.now += 10
    assert breaker.allow() is True


# ---- the breaker in front of Redis ----


def test_redis_is_left_alone_once_the_breaker_opens(dead_redis_calls):
    for _ in range(10):
        assert cache.get_json("test:key") is None
    stats = cache.stats()
    assert dead_redis_calls["n"] == cache.FAILURE_THRESHOLD
    assert stats["state"] == "open"
    assert stats["trips"] == 1
    assert stats["skipped_calls"] == 7


def test_pages_keep_working_with_the_breaker_open(client, policy, dead_redis_calls):
    for _ in range(5):
        response = client.get("/api/policies")
        assert response.status_code == 200
        assert response.headers["X-Cache"] == "MISS"
    assert dead_redis_calls["n"] <= cache.FAILURE_THRESHOLD
    assert cache.stats()["state"] == "open"


def test_breaker_closes_again_when_redis_returns(monkeypatch, dead_redis_calls):
    clock = Clock()
    monkeypatch.setattr(cache.breaker, "_clock", clock)
    for _ in range(3):
        cache.get_json("test:key")
    assert cache.stats()["state"] == "open"

    monkeypatch.setattr(cache, "get_redis", real_get_redis)
    clock.now += 30
    assert cache.set_json("test:key", 1, 30) is True
    assert cache.stats()["state"] == "closed"
    assert cache.get_json("test:key") == 1


# ---- single-flight ----


def test_concurrent_calls_share_one_computation():
    flight = SingleFlight()
    started, release = threading.Event(), threading.Event()
    computed = []
    results = []

    def slow():
        computed.append(1)
        started.set()
        release.wait(2)
        return "value"

    threads = [threading.Thread(target=lambda: results.append(flight.run("k", slow)))]
    threads[0].start()
    assert started.wait(2)
    for _ in range(4):
        thread = threading.Thread(target=lambda: results.append(flight.run("k", slow)))
        threads.append(thread)
        thread.start()
    _wait_for(lambda: flight.stats()["coalesced"] == 4)
    release.set()
    for thread in threads:
        thread.join(2)

    assert results == ["value"] * 5
    assert len(computed) == 1
    assert flight.stats()["in_flight"] == 0


def test_followers_compute_for_themselves_if_the_leader_fails():
    flight = SingleFlight()
    started, release = threading.Event(), threading.Event()
    leader_errors, follower_results = [], []

    def failing():
        started.set()
        release.wait(2)
        raise RuntimeError("boom")

    def lead():
        try:
            flight.run("k", failing)
        except RuntimeError as exc:
            leader_errors.append(exc)

    leader = threading.Thread(target=lead)
    leader.start()
    assert started.wait(2)
    follower = threading.Thread(
        target=lambda: follower_results.append(flight.run("k", lambda: "mine"))
    )
    follower.start()
    _wait_for(lambda: flight.stats()["coalesced"] == 1)
    release.set()
    leader.join(2)
    follower.join(2)

    assert len(leader_errors) == 1
    assert follower_results == ["mine"]


def test_a_follower_stops_waiting_for_a_slow_leader():
    flight = SingleFlight(wait_seconds=0.05)
    started, release = threading.Event(), threading.Event()
    results = []

    def slow():
        started.set()
        release.wait(2)
        return "slow"

    leader = threading.Thread(target=lambda: results.append(flight.run("k", slow)))
    leader.start()
    assert started.wait(2)
    assert flight.run("k", lambda: "fast") == "fast"
    assert flight.stats()["wait_timeouts"] == 1
    release.set()
    leader.join(2)


def test_a_finished_flight_does_not_serve_stale_results():
    flight = SingleFlight()
    assert flight.run("k", lambda: 1) == 1
    assert flight.run("k", lambda: 2) == 2