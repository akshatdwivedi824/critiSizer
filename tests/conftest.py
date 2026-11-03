import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

TEST_DB_NAME = "critisizer_test"

_dev_url = os.environ.get("DATABASE_URL") or dotenv_values(".env")["DATABASE_URL"]
_test_url = make_url(_dev_url).set(database=TEST_DB_NAME)
# Set before anything from critisizer is imported, so the app uses the test database.
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)


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
