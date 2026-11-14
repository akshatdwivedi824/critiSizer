from datetime import date, timedelta

import pytest
from factories import CODES, add_indicator, fill_policy, make_aspects, make_policy
from sqlalchemy import select

from critisizer.models import (
    AspectReview,
    AuditLog,
    EvidenceRun,
    Indicator,
    SourceItem,
)
from critisizer.snapshots import take_snapshots

LAST = "equity_impact"
FIVE = {code: (40, [1.0]) for code in CODES if code != LAST}
# Method v2: an overall rating needs at least 4 aspects on realised evidence.
THREE = {code: (40, [1.0]) for code in CODES[:3]}
FOUR = {code: (40, [1.0]) for code in CODES[:4]}
NONE_FOUND = {"reason": "read all collected sources; none describe equity harm"}
FUTURE = (date.today() + timedelta(days=30)).isoformat()
TOO_EARLY = {
    "reason": "law only partly in force; no outcomes reported yet",
    "review_date": FUTURE,
}


@pytest.fixture
def aspects(session):
    return make_aspects(session)


def add_sources(session, policy, count, outlets):
    run = EvidenceRun(
        policy_id=policy.id, query_version="v1", query_text="q", source_api="test"
    )
    session.add(run)
    session.flush()
    for n in range(count):
        session.add(
            SourceItem(
                run_id=run.id,
                policy_id=policy.id,
                url=f"https://example.org/{policy.id}/{n}",
                outlet=f"outlet-{n % outlets}",
                excerpt="text",
                content_hash=f"{policy.id}-{n}",
            )
        )
    session.flush()
    session.commit()


def url(slug, code=LAST):
    return f"/api/admin/policies/{slug}/aspects/{code}/no-negative-evidence"


def too_early_url(slug, code=LAST):
    return f"/api/admin/policies/{slug}/aspects/{code}/too-early"


def listed(client, slug):
    return {p["slug"]: p for p in client.get("/api/policies").json()}[slug]


@pytest.fixture
def partial(session, aspects):
    """Three aspects on realised evidence: below the minimum of four."""
    policy = fill_policy(session, aspects, "partial", THREE)
    add_sources(session, policy, 4, 2)
    return policy


def test_three_assessed_aspects_give_no_overall_rating(client, partial):
    body = client.get("/api/policies/partial").json()
    assert body["scored"] is True
    assert body["rated"] is False
    assert body["overall_rating"] is None
    assert body["expert_average"] is None
    assert (body["aspects_resolved"], body["aspects_total"]) == (3, 6)
    assert body["aspects_assessed"] == 3
    statuses = {a["code"]: a["status"] for a in body["aspects"]}
    assert statuses[LAST] == "unresolved"
    reviewed = next(a for a in body["aspects"] if a["code"] == CODES[0])
    assert reviewed["score"] == 40.0
    assert body["source_count"] == 4
    assert body["outlet_count"] == 2


def test_four_realised_aspects_are_enough_for_a_rating(client, session, aspects):
    fill_policy(session, aspects, "four", FOUR)
    session.commit()
    body = client.get("/api/policies/four").json()
    assert body["rated"] is True
    assert body["overall_rating"] == 40.0
    assert (body["aspects_assessed"], body["aspects_resolved"]) == (4, 4)
    assert body["method_version"] == "v2"


def test_marking_a_fourth_aspect_makes_the_policy_rated(
    client, session, partial, admin_headers
):
    response = client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["rated"] is True
    assert response.json()["aspects_assessed"] == 4
    body = client.get("/api/policies/partial").json()
    assert body["rated"] is True
    assert body["overall_rating"] == 30.0  # (3 * 40 + 0) / 4
    last = next(a for a in body["aspects"] if a["code"] == LAST)
    assert last["status"] == "no_negative_evidence"
    assert last["score"] == 0.0
    assert last["review_reason"] == NONE_FOUND["reason"]


def test_marking_is_audited(client, session, partial, admin_headers):
    client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    rows = session.scalars(select(AuditLog)).all()
    assert [r.action for r in rows] == ["aspect.no_negative_evidence"]
    assert rows[0].details["reason"] == NONE_FOUND["reason"]
    assert rows[0].details["sources"] == 4


def test_marking_needs_a_token_and_a_reason(client, partial, admin_headers):
    assert client.post(url("partial"), json=NONE_FOUND).status_code == 403
    short = client.post(url("partial"), json={"reason": "no"}, headers=admin_headers)
    assert short.status_code == 422


def test_marking_is_refused_with_too_little_evidence(
    client, session, aspects, admin_headers
):
    thin = fill_policy(session, aspects, "thin", FIVE)
    add_sources(session, thin, 2, 2)
    assert (
        client.post(url("thin"), json=NONE_FOUND, headers=admin_headers).status_code
        == 409
    )
    one_outlet = fill_policy(session, aspects, "one-outlet", FIVE)
    add_sources(session, one_outlet, 5, 1)
    assert (
        client.post(
            url("one-outlet"), json=NONE_FOUND, headers=admin_headers
        ).status_code
        == 409
    )
    assert session.scalars(select(AspectReview)).all() == []


def test_marking_is_refused_when_the_aspect_has_an_approved_indicator(
    client, partial, admin_headers
):
    response = client.post(
        url("partial", CODES[0]), json=NONE_FOUND, headers=admin_headers
    )
    assert response.status_code == 409


def test_marking_is_refused_while_a_draft_is_pending(
    client, session, partial, aspects, admin_headers
):
    add_indicator(session, partial, aspects[LAST], 50, [1.0])
    draft = session.scalars(select(Indicator).order_by(Indicator.id.desc())).first()
    draft.status = "ai_draft"
    session.commit()
    response = client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    assert response.status_code == 409


def test_marking_twice_is_409(client, partial, admin_headers):
    assert (
        client.post(url("partial"), json=NONE_FOUND, headers=admin_headers).status_code
        == 201
    )
    assert (
        client.post(url("partial"), json=NONE_FOUND, headers=admin_headers).status_code
        == 409
    )


def test_unknown_policy_or_aspect_is_404(client, partial, admin_headers):
    assert (
        client.post(url("nope"), json=NONE_FOUND, headers=admin_headers).status_code
        == 404
    )
    assert (
        client.post(
            url("partial", "nonsense"), json=NONE_FOUND, headers=admin_headers
        ).status_code
        == 404
    )


def test_reopening_removes_the_rating_and_is_audited(
    client, session, partial, admin_headers
):
    client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    response = client.delete(url("partial"), headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["rated"] is False
    assert client.get("/api/policies/partial").json()["overall_rating"] is None
    actions = [
        r.action for r in session.scalars(select(AuditLog).order_by(AuditLog.id))
    ]
    assert actions == ["aspect.no_negative_evidence", "aspect.reopen"]


def test_reopening_an_unmarked_aspect_is_404(client, partial, admin_headers):
    assert client.delete(url("partial"), headers=admin_headers).status_code == 404


def test_the_list_cache_is_cleared_when_an_aspect_is_marked(
    client, partial, admin_headers
):
    assert listed(client, "partial")["overall_rating"] is None
    client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    assert listed(client, "partial")["overall_rating"] == 30.0


def test_aspect_states_listing(client, session, partial, admin_headers):
    client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    body = client.get(
        "/api/admin/policies/partial/aspects", headers=admin_headers
    ).json()
    by_code = {a["code"]: a for a in body}
    assert by_code[LAST]["status"] == "no_negative_evidence"
    assert by_code[CODES[0]]["status"] == "scored"


def test_snapshots_skip_a_policy_below_the_assessed_minimum(
    session, aspects, admin_headers
):
    fill_policy(session, aspects, "partial", THREE)
    fill_policy(session, aspects, "whole", {c: (40, [1.0]) for c in CODES})
    make_policy(session, "empty")
    report = take_snapshots(session, date(2026, 11, 2))
    assert (report.created, report.unrated, report.unscored) == (1, 1, 1)


def test_a_reviewed_none_found_aspect_lets_a_snapshot_be_taken(
    client, session, partial, admin_headers
):
    client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    report = take_snapshots(session, date(2026, 11, 2))
    assert report.created == 1


# ---- "too early" (method v2) ------------------------------------------------


def test_too_early_is_recorded_and_not_counted(client, partial, admin_headers):
    response = client.post(
        too_early_url("partial"), json=TOO_EARLY, headers=admin_headers
    )
    assert response.status_code == 201
    assert response.json()["outcome"] == "too_early"
    assert response.json()["rated"] is False
    body = client.get("/api/policies/partial").json()
    assert (body["aspects_resolved"], body["aspects_assessed"]) == (4, 3)
    assert body["rated"] is False
    last = next(a for a in body["aspects"] if a["code"] == LAST)
    assert last["status"] == "too_early"
    assert last["review_date"] == FUTURE
    assert last["score"] is None


def test_too_early_needs_a_token_a_reason_and_a_future_date(
    client, partial, admin_headers
):
    target = too_early_url("partial")
    assert client.post(target, json=TOO_EARLY).status_code == 403
    short = {**TOO_EARLY, "reason": "no"}
    assert client.post(target, json=short, headers=admin_headers).status_code == 422
    past = {**TOO_EARLY, "review_date": "2020-01-01"}
    assert client.post(target, json=past, headers=admin_headers).status_code == 422


def test_too_early_is_refused_when_the_aspect_has_an_approved_indicator(
    client, partial, admin_headers
):
    response = client.post(
        too_early_url("partial", CODES[0]), json=TOO_EARLY, headers=admin_headers
    )
    assert response.status_code == 409


def test_too_early_twice_is_409(client, partial, admin_headers):
    target = too_early_url("partial")
    assert client.post(target, json=TOO_EARLY, headers=admin_headers).status_code == 201
    assert client.post(target, json=TOO_EARLY, headers=admin_headers).status_code == 409


def test_too_early_is_audited_and_can_be_reopened(
    client, session, partial, admin_headers
):
    client.post(too_early_url("partial"), json=TOO_EARLY, headers=admin_headers)
    response = client.delete(url("partial"), headers=admin_headers)
    assert response.status_code == 200
    states = client.get(
        "/api/admin/policies/partial/aspects", headers=admin_headers
    ).json()
    assert {a["code"]: a["status"] for a in states}[LAST] == "unresolved"
    actions = [
        r.action for r in session.scalars(select(AuditLog).order_by(AuditLog.id))
    ]
    assert actions == ["aspect.too_early", "aspect.reopen"]


# ---- projected indicators (method v2) ---------------------------------------


def add_projected(session, policy, aspects, score=100):
    add_indicator(session, policy, aspects[LAST], score, [1.0])
    row = session.scalars(select(Indicator).order_by(Indicator.id.desc())).first()
    row.evidence_status = "projected"
    row.projection_source = "Fiscal memorandum"
    session.commit()


def test_a_projected_indicator_is_shown_but_not_in_the_number(
    client, session, aspects
):
    policy = fill_policy(session, aspects, "four", FOUR)
    add_projected(session, policy, aspects)
    body = client.get("/api/policies/four").json()
    assert body["rated"] is True
    assert body["overall_rating"] == 40.0  # the projected 100 is excluded
    assert (body["aspects_assessed"], body["aspects_resolved"]) == (4, 5)
    last = next(a for a in body["aspects"] if a["code"] == LAST)
    assert last["status"] == "projected"
    assert last["score"] == 100.0
    assert last["indicators"][0]["evidence_status"] == "projected"
    assert last["indicators"][0]["projection_source"] == "Fiscal memorandum"


def test_a_projected_aspect_cannot_complete_the_minimum(client, session, aspects):
    policy = fill_policy(session, aspects, "three", THREE)
    add_projected(session, policy, aspects)
    body = client.get("/api/policies/three").json()
    assert body["rated"] is False
    assert (body["aspects_assessed"], body["aspects_resolved"]) == (3, 4)