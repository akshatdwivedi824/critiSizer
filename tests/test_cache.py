import pytest
from factories import CODES, fill_policy, make_aspects

LIST_URL = "/api/policies"


@pytest.fixture
def policy(session):
    aspects = make_aspects(session)
    return fill_policy(session, aspects, "cached", {c: (40, [1.0]) for c in CODES})


def test_list_is_a_miss_then_a_hit(client, policy):
    first = client.get(LIST_URL)
    second = client.get(LIST_URL)
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"


def test_cached_list_equals_the_fresh_list(client, policy):
    first = client.get(LIST_URL).json()
    second = client.get(LIST_URL).json()
    assert first == second
    assert first[0]["slug"] == "cached"
    assert first[0]["overall_rating"] == 40.0


def test_list_still_works_when_redis_is_down(client, policy, redis_down):
    response = client.get(LIST_URL)
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert len(response.json()) == 1
