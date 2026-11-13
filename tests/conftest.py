import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
import redis
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

TEST_DB_NAME = "critisizer_test"
TEST_REDIS_DB = 15
TEST_ADMIN_TOKEN = "test-admin-token-not-secret"

_dev_url = os.environ.get("DATABASE_URL") or dotenv_values(".env")["DATABASE_URL"]
_test_url = make_url(_dev_url).set(database=TEST_DB_NAME)
# Set before anything from critisizer is imported, so the app uses the test database.
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)

# Same idea for Redis: tests use database 15, never the dev data in database 0.
_dev_redis = os.environ.get("REDIS_URL") or dotenv_values(".env")["REDIS_URL"]
os.environ["REDIS_URL"] = (
    urlparse(_dev_redis)._replace(path=f"/{TEST_REDIS_DB}").geturl()
)

# A known admin token, so tests never depend on the real one in .env.
os.environ["ADMIN_TOKEN"] = TEST_ADMIN_TOKEN


@pytest.fixture(scope="session")
def test_engine():
    admin = create_engine(
        make_url(_dev_url).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        exists = conn.scalar(
            text("select 1 from pg_database where datname = :name"),
            {"name": TEST_DB_NAME},
        )
        if not exists:
            conn.execute(text(f'create database "{TEST_DB_NAME}"'))
    admin.dispose()

    from critisizer.db import engine

    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield engine


@pytest.fixture(autouse=True)
def clean_redis() -> Iterator[None]:
    """Empty the test Redis database before and after every test."""

    def flush() -> None:
        try:
            redis.Redis.from_url(
                os.environ["REDIS_URL"], socket_connect_timeout=1, socket_timeout=1
            ).flushdb()
        except redis.RedisError:
            pass  # tests that need Redis will fail on their own

    flush()
    yield
    flush()


@pytest.fixture(autouse=True)
def reset_cache_state() -> Iterator[None]:
    """The breaker and single-flight are process-wide; never leak them across tests."""
    from critisizer import cache
    from critisizer.singleflight import flights

    cache.breaker.reset()
    flights.reset()
    yield
    cache.breaker.reset()
    flights.reset()


@pytest.fixture
def session(test_engine) -> Iterator[Session]:
    connection = test_engine.connect()
    outer = connection.begin()
    db_session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield db_session
    finally:
        db_session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def client(session):
    from fastapi.testclient import TestClient

    from critisizer.deps import get_session
    from critisizer.main import app

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


class _DeadRedis:
    """Every call fails the way a real outage does, instantly."""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise redis.ConnectionError("redis is down (test)")

        return fail


@pytest.fixture
def redis_down(monkeypatch):
    from critisizer import cache

    monkeypatch.setattr(cache, "get_redis", lambda: _DeadRedis())


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}
