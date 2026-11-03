from sqlalchemy import select

from critisizer.auth import hash_token
from critisizer.models import User

CREDS = {"email": "Reader@Example.org", "password": "correct horse"}


def test_signup_stores_a_hash_not_the_password(client, session):
    response = client.post("/api/signup", json=CREDS)
    assert response.status_code == 201
    assert response.json()["email"] == "reader@example.org"
    user = session.scalar(select(User).where(User.email == "reader@example.org"))
    assert user.password_hash != CREDS["password"]
    assert user.password_hash.startswith("scrypt$")


def test_duplicate_email_is_409_even_with_different_case(client):
    assert client.post("/api/signup", json=CREDS).status_code == 201
    other_case = {**CREDS, "email": "READER@example.org"}
    assert client.post("/api/signup", json=other_case).status_code == 409


def test_login_returns_a_token_and_stores_only_its_hash(client, session):
    client.post("/api/signup", json=CREDS)
    response = client.post("/api/login", json=CREDS)
    assert response.status_code == 200
    token = response.json()["token"]
    user = session.scalar(select(User).where(User.email == "reader@example.org"))
    assert user.token_hash != token
    assert user.token_hash == hash_token(token)


def test_wrong_password_and_unknown_email_are_both_401(client):
    client.post("/api/signup", json=CREDS)
    wrong = client.post("/api/login", json={**CREDS, "password": "wrong password"})
    unknown = client.post(
        "/api/login", json={"email": "nobody@example.org", "password": "whatever123"}
    )
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_short_password_is_422(client):
    response = client.post("/api/signup", json={**CREDS, "password": "short"})
    assert response.status_code == 422
