import pytest
from factories import CODES, fill_policy, make_aspects
from sqlalchemy import select

from critisizer.models import AuditLog, Rating

RATE_URL = "/api/policies/rated/ratings"
ADMIN_URL = "/api/admin/ratings"


@pytest.fixture
def policy(session):
    aspects = make_aspects(session)
    return fill_policy(session, aspects, "rated", {c: (40, [1.0]) for c in CODES})


def rate(client, email: str, value: float = 100) -> int:
    creds = {"email": email, "password": "correct horse"}
    client.post("/api/signup", json=creds)
    token = client.post("/api/login", json=creds).json()["token"]
    response = client.post(
        RATE_URL, json={"value": value}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    return response.json()["id"]


def audit_rows(session):
    return session.scalars(select(AuditLog).order_by(AuditLog.id)).all()


def status_of(session, rating_id: int) -> str:
    session.expire_all()
    return session.get(Rating, rating_id).status


def test_admin_list_without_a_token_is_403(client, policy):
    assert client.get(ADMIN_URL).status_code == 403


def test_wrong_token_is_403_and_changes_nothing(client, session, policy):
    rating_id = rate(client, "a@example.org")
    wrong = {"Authorization": "Bearer not-the-token"}
    response = client.post(f"{ADMIN_URL}/{rating_id}/accept", headers=wrong)
    assert response.status_code == 403
    assert status_of(session, rating_id) == "pending"
    assert audit_rows(session) == []


def test_admin_is_disabled_when_no_token_is_configured(client, policy, monkeypatch):
    from critisizer.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_token", "")
    headers = {"Authorization": "Bearer anything"}
    assert client.get(ADMIN_URL, headers=headers).status_code == 403


def test_pending_list_shows_slug_and_value(client, policy, admin_headers):
    rate(client, "a@example.org", 70)
    body = client.get(ADMIN_URL, headers=admin_headers).json()
    assert len(body) == 1
    assert body[0]["policy_slug"] == "rated"
    assert body[0]["value"] == 70.0
    assert body[0]["status"] == "pending"
    accepted = client.get(f"{ADMIN_URL}?status=accepted", headers=admin_headers)
    assert accepted.json() == []


def test_unknown_status_filter_is_422(client, policy, admin_headers):
    response = client.get(f"{ADMIN_URL}?status=bogus", headers=admin_headers)
    assert response.status_code == 422


def test_accept_changes_status_and_writes_one_audit_row(
    client, session, policy, admin_headers
):
    rating_id = rate(client, "a@example.org")
    response = client.post(f"{ADMIN_URL}/{rating_id}/accept", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert status_of(session, rating_id) == "accepted"
    rows = audit_rows(session)
    assert len(rows) == 1
    assert rows[0].action == "rating.accept"
    assert rows[0].target_type == "rating"
    assert rows[0].target_id == rating_id
    assert rows[0].actor_user_id is None
    assert rows[0].details == {
        "rating_id": rating_id,
        "old_status": "pending",
        "new_status": "accepted",
        "via": "admin-token",
    }


def test_reject_changes_status_and_writes_an_audit_row(
    client, session, policy, admin_headers
):
    rating_id = rate(client, "a@example.org")
    response = client.post(f"{ADMIN_URL}/{rating_id}/reject", headers=admin_headers)
    assert response.status_code == 200
    assert status_of(session, rating_id) == "rejected"
    rows = audit_rows(session)
    assert [r.action for r in rows] == ["rating.reject"]
    assert rows[0].details["new_status"] == "rejected"


def test_acting_twice_is_409_and_writes_no_second_row(
    client, session, policy, admin_headers
):
    rating_id = rate(client, "a@example.org")
    url = f"{ADMIN_URL}/{rating_id}/accept"
    assert client.post(url, headers=admin_headers).status_code == 200
    assert client.post(url, headers=admin_headers).status_code == 409
    assert len(audit_rows(session)) == 1


def test_unknown_rating_is_404(client, policy, admin_headers):
    response = client.post(f"{ADMIN_URL}/99999/accept", headers=admin_headers)
    assert response.status_code == 404


def test_audit_failure_rolls_back_the_status_change(
    client, session, policy, admin_headers, monkeypatch
):
    rating_id = rate(client, "a@example.org")

    def boom(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr("critisizer.admin.record_audit", boom)
    with pytest.raises(RuntimeError):
        client.post(f"{ADMIN_URL}/{rating_id}/accept", headers=admin_headers)
    assert status_of(session, rating_id) == "pending"
    assert audit_rows(session) == []


def test_accept_clears_the_cached_list(client, policy, admin_headers):
    rating_id = rate(client, "a@example.org")
    assert client.get("/api/policies").headers["X-Cache"] == "MISS"
    assert client.get("/api/policies").headers["X-Cache"] == "HIT"
    client.post(f"{ADMIN_URL}/{rating_id}/accept", headers=admin_headers)
    assert client.get("/api/policies").headers["X-Cache"] == "MISS"


def test_five_accepted_ratings_reveal_the_people_rating(
    client, session, policy, admin_headers
):
    ids = [rate(client, f"u{n}@example.org") for n in range(5)]
    before = client.get("/api/policies/rated").json()
    assert before["people_rating_visible"] is False
    for rating_id in ids:
        response = client.post(f"{ADMIN_URL}/{rating_id}/accept", headers=admin_headers)
        assert response.status_code == 200
    after = client.get("/api/policies/rated").json()
    assert after["people_rating_visible"] is True
    assert after["people_rating"] == 100.0
    assert after["overall_rating"] == 48.6
    rows = audit_rows(session)
    assert len(rows) == 5
    assert {r.action for r in rows} == {"rating.accept"}
