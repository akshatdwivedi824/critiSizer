from decimal import Decimal

import pytest
from factories import add_indicator, make_aspects, make_policy
from sqlalchemy import select

from critisizer.models import AuditLog, Indicator

URL = "/api/admin/drafts"
GOOD = [Decimal("1.00")]
ZERO = [Decimal("0.00")]


@pytest.fixture
def aspects(session):
    return make_aspects(session)


@pytest.fixture
def policy(session):
    return make_policy(session, "review-policy")


def make_draft(session, policy, aspects, multipliers=GOOD):
    add_indicator(session, policy, aspects["outcome_failure"], 60, multipliers)
    indicator = session.scalars(
        select(Indicator).order_by(Indicator.id.desc())
    ).first()
    indicator.status = "ai_draft"
    session.commit()
    return indicator.id


def audit_rows(session):
    return session.scalars(select(AuditLog).order_by(AuditLog.id)).all()


def test_list_without_a_token_is_403(client):
    assert client.get(URL).status_code == 403


def test_approve_without_a_token_is_403(client, session, policy, aspects):
    draft_id = make_draft(session, policy, aspects)
    assert client.post(f"{URL}/{draft_id}/approve").status_code == 403
    session.expire_all()
    assert session.get(Indicator, draft_id).status == "ai_draft"
    assert audit_rows(session) == []


def test_list_shows_only_drafts(client, session, policy, aspects, admin_headers):
    draft_id = make_draft(session, policy, aspects)
    add_indicator(session, policy, aspects["cost_waste"], 40, GOOD)  # approved
    session.commit()
    body = client.get(URL, headers=admin_headers).json()
    assert [d["id"] for d in body] == [draft_id]
    assert body[0]["policy_slug"] == "review-policy"
    assert body[0]["aspect"] == "outcome_failure"
    assert body[0]["evidence"][0]["counts"] is True


def test_draft_without_a_description_still_lists(
    client, session, policy, aspects, admin_headers
):
    draft_id = make_draft(session, policy, aspects)
    session.get(Indicator, draft_id).description = None
    session.commit()
    response = client.get(URL, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()[0]["description"] is None


def test_approve_changes_status_and_writes_one_audit_row(
    client, session, policy, aspects, admin_headers
):
    draft_id = make_draft(session, policy, aspects)
    response = client.post(
        f"{URL}/{draft_id}/approve", json={"note": "checked"}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    session.expire_all()
    assert session.get(Indicator, draft_id).status == "approved"
    rows = audit_rows(session)
    assert len(rows) == 1
    assert rows[0].action == "indicator.approve"
    assert rows[0].target_id == draft_id
    assert rows[0].details["note"] == "checked"
    assert rows[0].details["old_status"] == "ai_draft"


def test_approve_works_without_a_body(client, session, policy, aspects, admin_headers):
    draft_id = make_draft(session, policy, aspects)
    response = client.post(f"{URL}/{draft_id}/approve", headers=admin_headers)
    assert response.status_code == 200


def test_reject_stores_the_reason_in_the_audit_row(
    client, session, policy, aspects, admin_headers
):
    draft_id = make_draft(session, policy, aspects)
    response = client.post(
        f"{URL}/{draft_id}/reject",
        json={"reason": "cites the stated aim, not a failure"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    session.expire_all()
    assert session.get(Indicator, draft_id).status == "rejected"
    rows = audit_rows(session)
    assert len(rows) == 1
    assert rows[0].action == "indicator.reject"
    assert rows[0].details["reason"] == "cites the stated aim, not a failure"


def test_reject_needs_a_real_reason(client, session, policy, aspects, admin_headers):
    draft_id = make_draft(session, policy, aspects)
    response = client.post(
        f"{URL}/{draft_id}/reject", json={"reason": "no"}, headers=admin_headers
    )
    assert response.status_code == 422
    session.expire_all()
    assert session.get(Indicator, draft_id).status == "ai_draft"
    assert audit_rows(session) == []


def test_second_decision_is_409_and_writes_nothing_more(
    client, session, policy, aspects, admin_headers
):
    draft_id = make_draft(session, policy, aspects)
    first = client.post(f"{URL}/{draft_id}/approve", headers=admin_headers)
    assert first.status_code == 200
    again = client.post(
        f"{URL}/{draft_id}/reject",
        json={"reason": "changed my mind"},
        headers=admin_headers,
    )
    assert again.status_code == 409
    assert len(audit_rows(session)) == 1


def test_cannot_approve_without_counting_evidence(
    client, session, policy, aspects, admin_headers
):
    draft_id = make_draft(session, policy, aspects, multipliers=ZERO)
    response = client.post(f"{URL}/{draft_id}/approve", headers=admin_headers)
    assert response.status_code == 409
    session.expire_all()
    assert session.get(Indicator, draft_id).status == "ai_draft"
    assert audit_rows(session) == []


def test_can_still_reject_a_draft_with_no_counting_evidence(
    client, session, policy, aspects, admin_headers
):
    draft_id = make_draft(session, policy, aspects, multipliers=ZERO)
    response = client.post(
        f"{URL}/{draft_id}/reject",
        json={"reason": "evidence does not support it"},
        headers=admin_headers,
    )
    assert response.status_code == 200


def test_unknown_draft_is_404(client, admin_headers):
    response = client.post(f"{URL}/999999/approve", headers=admin_headers)
    assert response.status_code == 404