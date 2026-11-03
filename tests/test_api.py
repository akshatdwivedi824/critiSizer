import pytest
from factories import CODES, add_indicator, fill_policy, make_aspects
from fastapi.testclient import TestClient

from critisizer.deps import get_session
from critisizer.main import app


@pytest.fixture
def aspects(session):
    return make_aspects(session)


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def all_aspects(score=40):
    return {code: (score, [1.0]) for code in CODES}


def test_list_is_empty_without_policies(client):
    response = client.get("/api/policies")
    assert response.status_code == 200
    assert response.json() == []


def test_list_returns_policies_ordered_by_name(client, session, aspects):
    fill_policy(session, aspects, "b-policy", all_aspects(40))
    fill_policy(session, aspects, "a-policy", all_aspects(20))
    body = client.get("/api/policies").json()
    assert [p["slug"] for p in body] == ["a-policy", "b-policy"]
    assert body[0]["overall_rating"] == 20.0
    assert body[0]["people_rating"] is None


def test_detail_matches_hand_calculation(client, session, aspects):
    fill_policy(
        session,
        aspects,
        "hand-calc",
        {
            "outcome_failure": (20, [1.0]),
            "cost_waste": (15, [1.0]),
            "transparency_gap": (25, [1.0]),
            "ground_level_harm": (20, [0.8]),
            "legal_challenges": (10, [1.0]),
            "equity_impact": (30, [0.5]),
        },
    )
    body = client.get("/api/policies/hand-calc").json()
    assert body["overall_rating"] == 16.8
    assert body["spike_flag"] is False
    assert body["rubric_label"] == "test-v1"
    assert len(body["aspects"]) == 6
    assert [a["score"] for a in body["aspects"]] == [20.0, 15.0, 25.0, 16.0, 10.0, 15.0]


def test_detail_flags_excluded_evidence(client, session, aspects):
    rows = {c: (40, [1.0]) for c in CODES if c != "ground_level_harm"}
    policy = fill_policy(session, aspects, "excluded", rows)
    add_indicator(session, policy, aspects["ground_level_harm"], 60, [0])
    add_indicator(session, policy, aspects["ground_level_harm"], 20, [0.8])
    body = client.get("/api/policies/excluded").json()
    harm = next(a for a in body["aspects"] if a["code"] == "ground_level_harm")
    assert harm["score"] == 16.0
    flags = [e["excluded"] for i in harm["indicators"] for e in i["evidence"]]
    assert sorted(flags) == [False, True]


def test_unknown_slug_is_a_json_404(client):
    response = client.get("/api/policies/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Policy not found"}
