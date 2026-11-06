from datetime import date

import pytest
from factories import CODES, fill_policy, make_aspects, make_policy
from sqlalchemy import select

from critisizer.models import ScoreSnapshot
from critisizer.snapshots import take_snapshots


@pytest.fixture
def aspects(session):
    return make_aspects(session)


def all_aspects(score=40):
    return {code: (score, [1.0]) for code in CODES}


def test_list_marks_a_policy_without_indicators_as_unscored(client, session, aspects):
    make_policy(session, "unscored")
    fill_policy(session, aspects, "scored", all_aspects(40))
    body = {p["slug"]: p for p in client.get("/api/policies").json()}
    assert body["unscored"]["scored"] is False
    assert body["unscored"]["overall_rating"] is None
    assert body["scored"]["scored"] is True
    assert body["scored"]["overall_rating"] == 40.0


def test_detail_of_an_unscored_policy_has_no_scores(client, session, aspects):
    make_policy(session, "unscored")
    body = client.get("/api/policies/unscored").json()
    assert body["scored"] is False
    assert body["overall_rating"] is None
    assert body["expert_average"] is None
    assert body["aspects"] == []


def test_home_page_says_not_yet_scored(client, session, aspects):
    make_policy(session, "unscored")
    html = client.get("/").text
    assert "Not yet scored" in html


def test_policy_page_says_not_yet_scored(client, session, aspects):
    make_policy(session, "unscored")
    response = client.get("/policies/unscored")
    assert response.status_code == 200
    assert "Not yet scored" in response.text


def test_snapshots_skip_policies_without_indicators(session, aspects):
    make_policy(session, "unscored")
    fill_policy(session, aspects, "scored", all_aspects(40))
    report = take_snapshots(session, date(2026, 11, 2))
    assert report.created == 1
    assert report.unscored == 1
    assert len(session.scalars(select(ScoreSnapshot)).all()) == 1