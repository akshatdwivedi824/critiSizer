import json
import logging

import pytest

from critisizer.observability import REQUEST_LOGGER, Metrics, metrics


@pytest.fixture(autouse=True)
def fresh_metrics():
    metrics.reset()


@pytest.fixture
def request_log(caplog):
    logger = logging.getLogger(REQUEST_LOGGER)
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=REQUEST_LOGGER)
    yield caplog
    logger.removeHandler(caplog.handler)


def _lines(caplog):
    return [
        json.loads(r.getMessage()) for r in caplog.records if r.name == REQUEST_LOGGER
    ]


def test_response_carries_a_request_id(client):
    response = client.get("/api/policies")
    assert len(response.headers["X-Request-ID"]) == 32


def test_safe_incoming_request_id_is_reused(client):
    response = client.get("/api/policies", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_unsafe_incoming_request_id_is_replaced(client):
    response = client.get("/api/policies", headers={"X-Request-ID": "has space"})
    assert response.headers["X-Request-ID"] != "has space"
    assert len(response.headers["X-Request-ID"]) == 32


def test_log_line_has_the_expected_fields(client, request_log):
    client.get("/api/policies")
    line = _lines(request_log)[-1]
    assert line["method"] == "GET"
    assert line["route"] == "/api/policies"
    assert line["status"] == 200
    assert isinstance(line["ms"], float)
    assert len(line["request_id"]) == 32
    assert {"ts", "path"} <= set(line)


def test_route_is_the_template_not_the_raw_path(client, request_log):
    client.get("/policies/no-such-policy-xyz")
    line = _lines(request_log)[-1]
    assert line["route"].startswith("/policies/")
    assert "no-such-policy-xyz" not in line["route"]
    assert line["status"] == 404


def test_unmatched_paths_share_one_route(client, request_log):
    client.get("/no/such/thing")
    assert _lines(request_log)[-1]["route"] == "unmatched"


def test_health_checks_are_not_logged_or_counted(client, request_log):
    client.get("/health")
    assert _lines(request_log) == []
    assert "GET /health" not in metrics.snapshot()["routes"]


def test_tokens_never_reach_the_log(client, request_log):
    client.get("/api/admin/drafts", headers={"Authorization": "Bearer top-secret-xyz"})
    client.get("/api/policies?token=query-secret-xyz")
    text = " ".join(r.getMessage() for r in request_log.records)
    assert "top-secret-xyz" not in text
    assert "query-secret-xyz" not in text


def test_metrics_endpoint_refuses_without_the_token(client):
    assert client.get("/metrics").status_code in (401, 403)


def test_metrics_endpoint_counts_requests(client, admin_headers):
    client.get("/api/policies")
    client.get("/api/policies")
    body = client.get("/metrics", headers=admin_headers).json()
    stats = body["routes"]["GET /api/policies"]
    assert stats["count"] == 2
    assert stats["statuses"] == {"2xx": 2}
    assert body["totals"]["requests"] >= 2


def test_average_p95_and_max():
    m = Metrics()
    for ms in range(1, 101):
        m.record("GET", "/x", 200, float(ms), None)
    stats = m.snapshot()["routes"]["GET /x"]
    assert stats["count"] == 100
    assert stats["avg_ms"] == 50.5
    assert stats["p95_ms"] == 95.0
    assert stats["max_ms"] == 100.0


def test_odd_http_methods_share_one_bucket():
    m = Metrics()
    m.record("WEIRD", "/x", 405, 1.0, None)
    m.record("OTHERWEIRD", "/x", 405, 1.0, None)
    assert list(m.snapshot()["routes"]) == ["OTHER /x"]


def test_cache_hits_and_misses_are_counted():
    m = Metrics()
    m.record("GET", "/x", 200, 1.0, "MISS")
    m.record("GET", "/x", 200, 1.0, "HIT")
    stats = m.snapshot()["routes"]["GET /x"]
    assert (stats["cache_hits"], stats["cache_misses"]) == (1, 1)


def test_metrics_include_cache_and_single_flight_sections(client, admin_headers):
    body = client.get("/metrics", headers=admin_headers).json()
    assert body["cache"]["state"] == "closed"
    assert "coalesced" in body["single_flight"]