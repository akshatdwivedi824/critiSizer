from datetime import date
from decimal import Decimal

import pytest
from factories import CODES, fill_policy, make_aspects
from sqlalchemy import select

from critisizer.models import ScoreSnapshot
from critisizer.snapshots import take_snapshots, week_start

MONDAY = date(2026, 11, 2)
NEXT_MONDAY = date(2026, 11, 9)


@pytest.fixture
def aspects(session):
    return make_aspects(session)


@pytest.fixture
def policies(session, aspects):
    fill_policy(session, aspects, "alpha", {c: (40, [1.0]) for c in CODES})
    fill_policy(session, aspects, "beta", {c: (60, [1.0]) for c in CODES})


def stored(session):
    return session.scalars(select(ScoreSnapshot).order_by(ScoreSnapshot.id)).all()


@pytest.mark.parametrize(
    "day", [date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 8)]
)
def test_week_start_is_the_monday(day):
    assert week_start(day) == MONDAY


def test_a_week_that_is_not_a_monday_is_refused(session, policies):
    with pytest.raises(ValueError, match="Monday"):
        take_snapshots(session, date(2026, 11, 4))


def test_one_snapshot_per_policy_with_exact_aspect_scores(session, policies):
    report = take_snapshots(session, MONDAY)
    rows = stored(session)
    assert (report.created, report.failed) == (2, 0)
    assert len(rows) == 2
    alpha = rows[0]
    assert alpha.week == MONDAY
    assert alpha.overall_rating == Decimal("40.00")
    assert set(alpha.aspect_scores) == set(CODES)
    assert all(isinstance(v, str) for v in alpha.aspect_scores.values())
    assert Decimal(alpha.aspect_scores[CODES[0]]) == Decimal(40)


def test_running_twice_leaves_one_row_per_policy(session, policies):
    take_snapshots(session, MONDAY)
    second = take_snapshots(session, MONDAY)
    assert (second.created, second.skipped) == (0, 2)
    assert len(stored(session)) == 2


def test_default_rerun_leaves_an_existing_row_alone(session, policies):
    take_snapshots(session, MONDAY)
    snapshot = stored(session)[0]
    snapshot.overall_rating = Decimal("1.00")
    session.flush()
    take_snapshots(session, MONDAY)
    session.refresh(snapshot)
    assert snapshot.overall_rating == Decimal("1.00")


def test_replace_overwrites_the_existing_row(session, policies):
    take_snapshots(session, MONDAY)
    snapshot = stored(session)[0]
    original_id = snapshot.id
    snapshot.overall_rating = Decimal("1.00")
    session.flush()
    report = take_snapshots(session, MONDAY, replace=True)
    session.refresh(snapshot)
    assert (report.replaced, report.created) == (2, 0)
    assert snapshot.overall_rating == Decimal("40.00")
    assert snapshot.id == original_id
    assert len(stored(session)) == 2


def test_a_different_week_makes_new_rows(session, policies):
    take_snapshots(session, MONDAY)
    take_snapshots(session, NEXT_MONDAY)
    assert len(stored(session)) == 4


def test_a_policy_that_cannot_be_scored_is_skipped(session, aspects):
    broken = {c: (40, [1.0]) for c in CODES}
    broken[CODES[0]] = (40, [0])  # only an excluded allegation: no valid evidence
    fill_policy(session, aspects, "broken", broken)
    fill_policy(session, aspects, "fine", {c: (40, [1.0]) for c in CODES})
    report = take_snapshots(session, MONDAY)
    assert (report.created, report.failed) == (1, 1)
    assert len(stored(session)) == 1


def test_history_of_an_unknown_policy_is_404(client):
    assert client.get("/api/policies/nope/history").status_code == 404


def test_history_of_a_policy_without_snapshots_is_empty(client, policies):
    response = client.get("/api/policies/alpha/history")
    assert response.status_code == 200
    assert response.json() == []


def test_history_returns_the_snapshot_with_the_rubric_label(client, session, policies):
    take_snapshots(session, MONDAY)
    body = client.get("/api/policies/alpha/history").json()
    label = client.get("/api/policies/alpha").json()["rubric_label"]
    assert len(body) == 1
    assert body[0]["week"] == "2026-11-02"
    assert body[0]["rubric_label"] == label
    assert body[0]["overall_rating"] == 40.0
    assert body[0]["aspect_scores"][CODES[0]] == 40.0


def test_history_is_newest_week_first(client, session, policies):
    take_snapshots(session, MONDAY)
    take_snapshots(session, NEXT_MONDAY)
    body = client.get("/api/policies/alpha/history").json()
    assert [item["week"] for item in body] == ["2026-11-09", "2026-11-02"]
