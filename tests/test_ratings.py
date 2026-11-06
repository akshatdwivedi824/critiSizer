import pytest
from factories import CODES, fill_policy, make_aspects
from sqlalchemy import select, text

from critisizer.models import Rating

URL = "/api/policies/rated/ratings"


@pytest.fixture
def aspects(session):
    return make_aspects(session)


@pytest.fixture
def policy(session, aspects):
    return fill_policy(session, aspects, "rated", {c: (40, [1.0]) for c in CODES})


def sign_in(client, email="reader@example.org"):
    creds = {"email": email, "password": "correct horse"}
    client.post("/api/signup", json=creds)
    token = client.post("/api/login", json=creds).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def accept_all(session):
    for rating in session.scalars(select(Rating)):
        rating.status = "accepted"
    session.flush()


def test_rating_without_a_token_is_401(client, policy):
    assert client.post(URL, json={"value": 70}).status_code == 401


def test_rating_with_a_wrong_token_is_401(client, policy):
    headers = {"Authorization": "Bearer not-a-real-token"}
    assert client.post(URL, json={"value": 70}, headers=headers).status_code == 401


def test_first_rating_is_pending(client, policy):
    response = client.post(URL, json={"value": 70}, headers=sign_in(client))
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["value"] == 70.0


def test_second_rating_from_the_same_user_is_409(client, policy):
    headers = sign_in(client)
    assert client.post(URL, json={"value": 70}, headers=headers).status_code == 201
    assert client.post(URL, json={"value": 20}, headers=headers).status_code == 409


def test_out_of_range_value_is_422(client, policy):
    headers = sign_in(client)
    assert client.post(URL, json={"value": 150}, headers=headers).status_code == 422
    assert client.post(URL, json={"value": -1}, headers=headers).status_code == 422


def test_unknown_policy_is_404(client, policy):
    response = client.post(
        "/api/policies/nope/ratings", json={"value": 70}, headers=sign_in(client)
    )
    assert response.status_code == 404


def test_pending_ratings_never_change_the_score(client, policy):
    for n in range(6):
        headers = sign_in(client, f"user{n}@example.org")
        client.post(URL, json={"value": 100}, headers=headers)
    body = client.get("/api/policies/rated").json()
    assert body["people_rating"] is None
    assert body["people_rating_visible"] is False
    assert body["overall_rating"] == 40.0


def test_people_rating_appears_after_five_accepted_ratings(client, session, policy):
    for n in range(4):
        client.post(URL, json={"value": 100}, headers=sign_in(client, f"u{n}@x.org"))
    accept_all(session)
    body = client.get("/api/policies/rated").json()
    assert body["people_rating_count"] == 4
    assert body["people_rating_visible"] is False
    assert body["overall_rating"] == 40.0

    client.post(URL, json={"value": 100}, headers=sign_in(client, "u4@x.org"))
    accept_all(session)
    body = client.get("/api/policies/rated").json()
    assert body["people_rating_count"] == 5
    assert body["people_rating_visible"] is True
    assert body["people_rating"] == 100.0
    # (6 aspects x 40 + people 100) / 7 = 48.57
    assert body["overall_rating"] == 48.6

def test_ratings_must_be_whole_numbers(client, policy):
    headers = sign_in(client)
    for bad in (55.5, 55.0, "55", True, None):
        response = client.post(URL, json={"value": bad}, headers=headers)
        assert response.status_code == 422, bad


@pytest.mark.parametrize("value", [0, 1, 100])
def test_edge_whole_numbers_are_accepted(client, policy, value):
    headers = sign_in(client, f"edge{value}@example.org")
    response = client.post(URL, json={"value": value}, headers=headers)
    assert response.status_code == 201
    assert response.json()["value"] == value


def test_the_database_stores_ratings_as_integers(session):
    kind = session.execute(
        text(
            "select data_type from information_schema.columns "
            "where table_name = 'ratings' and column_name = 'value'"
        )
    ).scalar()
    assert kind == "smallint"