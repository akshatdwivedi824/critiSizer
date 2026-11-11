from datetime import date

import pytest
from factories import CODES, fill_policy, make_aspects, make_policy
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
NONE_FOUND = {"reason": "read all collected sources; none describe equity harm"}


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


def listed(client, slug):
    return {p["slug"]: p for p in client.get("/api/policies").json()}[slug]


@pytest.fixture
def partial(session, aspects):
    policy = fill_policy(session, aspects, "partial", FIVE)
    add_sources(session, policy, 4, 2)
    return policy


def test_five_of_six_aspects_gives_no_overall_rating(client, partial):
    body = client.get("/api/policies/partial").json()
    assert body["scored"] is True
    assert body["rated"] is False
    assert body["overall_rating"] is None
    assert body["expert_average"] is None
    assert (body["aspects_resolved"], body["aspects_total"]) == (5, 6)
    statuses = {a["code"]: a["status"] for a in body["aspects"]}
    assert statuses[LAST] == "unresolved"
    reviewed = next(a for a in body["aspects"] if a["code"] == CODES[0])
    assert reviewed["score"] == 40.0
    assert body["source_count"] == 4
    assert body["outlet_count"] == 2


def test_marking_the_last_aspect_completes_the_rating(
    client, session, partial, admin_headers
):
    response = client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["rated"] is True
    body = client.get("/api/policies/partial").json()
    assert body["rated"] is True
    assert body["overall_rating"] == 33.3  # (5 * 40 + 0) / 6
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
    from factories import add_indicator

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
    assert listed(client, "partial")["overall_rating"] == 33.3


def test_aspect_states_listing(client, session, partial, admin_headers):
    client.post(url("partial"), json=NONE_FOUND, headers=admin_headers)
    body = client.get(
        "/api/admin/policies/partial/aspects", headers=admin_headers
    ).json()
    by_code = {a["code"]: a for a in body}
    assert by_code[LAST]["status"] == "no_negative_evidence"
    assert by_code[CODES[0]]["status"] == "scored"


def test_snapshots_skip_a_policy_that_is_not_fully_resolved(
    session, aspects, admin_headers
):
    fill_policy(session, aspects, "partial", FIVE)
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
