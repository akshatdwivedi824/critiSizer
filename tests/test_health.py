from sqlalchemy.exc import SQLAlchemyError

from critisizer.deps import get_session
from critisizer.main import app


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_everything_answers(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_not_ready_when_redis_is_down(client, redis_down):
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["failed"] == ["redis"]


def test_not_ready_when_the_database_is_down(client):
    class Broken:
        def execute(self, *args, **kwargs):
            raise SQLAlchemyError("database is down")

    app.dependency_overrides[get_session] = lambda: Broken()
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["failed"] == ["database"]