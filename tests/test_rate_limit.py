# A policy that does not exist: attempts are 404, but they still count.
URL = "/api/policies/nope/ratings"
BODY = {"value": 50}


def sign_in(client, email):
    creds = {"email": email, "password": "correct horse"}
    client.post("/api/signup", json=creds)
    token = client.post("/api/login", json=creds).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def attempt(client, headers):
    return client.post(URL, json=BODY, headers=headers)


def test_sixth_attempt_in_a_minute_is_429_with_retry_after(client):
    headers = sign_in(client, "a@example.org")
    statuses = [attempt(client, headers).status_code for _ in range(5)]
    assert statuses == [404] * 5
    blocked = attempt(client, headers)
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60


def test_limit_is_per_user(client):
    a = sign_in(client, "a@example.org")
    b = sign_in(client, "b@example.org")
    for _ in range(6):
        attempt(client, a)
    assert attempt(client, a).status_code == 429
    assert attempt(client, b).status_code == 404


def test_rate_limit_fails_open_when_redis_is_down(client, redis_down):
    headers = sign_in(client, "a@example.org")
    statuses = {attempt(client, headers).status_code for _ in range(8)}
    assert statuses == {404}
