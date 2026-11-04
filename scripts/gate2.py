"""Gate 2 checker. Prints PASS or FAIL for each check; exits 1 if any fail."""

import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from critisizer import cache
from critisizer.db import SessionLocal
from critisizer.main import app
from critisizer.snapshots import week_start

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_ROUTES = [
    ("GET", "/api/policies"),
    ("GET", "/api/policies/{slug}"),
    ("GET", "/api/policies/{slug}/history"),
    ("POST", "/api/policies/{slug}/ratings"),
    ("GET", "/api/admin/ratings"),
    ("POST", "/api/admin/ratings/{rating_id}/accept"),
    ("POST", "/api/admin/ratings/{rating_id}/reject"),
]

REQUIRED_FILES = [
    "docs/capacity.md",
    "docs/load-test.md",
    "docs/img/scorecard.png",
    "docs/adr/0001-database-and-score-versioning.md",
    "docs/adr/0002-caching-and-failure-behaviour.md",
    "LOG.md",
]


def fail(message: str) -> None:
    raise AssertionError(message)


def route_exists(method: str, path: str) -> None:
    paths = app.openapi().get("paths", {})
    if method.lower() not in paths.get(path, {}):
        fail("route not registered")


def token_hash_column_exists() -> None:
    with SessionLocal() as session:
        row = session.scalar(
            text(
                "select 1 from information_schema.columns "
                "where table_name = 'users' and column_name = 'token_hash'"
            )
        )
    if row is None:
        fail("users.token_hash is missing; run alembic upgrade head")


def redis_answers() -> None:
    try:
        cache.get_redis().ping()
    except redis.RedisError as exc:
        fail(f"no answer from Redis ({type(exc).__name__}); run docker compose up -d")


def snapshot_for_this_week() -> None:
    this_week = week_start(date.today())
    with SessionLocal() as session:
        count = session.scalar(
            text("select count(*) from score_snapshots where week = :week"),
            {"week": this_week},
        )
    if not count:
        fail(f"no snapshot for the week of {this_week}; run scripts/snapshot.py")


def audit_log_has_a_row() -> None:
    with SessionLocal() as session:
        count = session.scalar(text("select count(*) from audit_log"))
    if not count:
        fail("audit_log is empty; accept or reject one rating through the admin API")


def file_exists(relative: str) -> None:
    if not (ROOT / relative).is_file():
        fail("file not found")


def readme_has_an_image() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if not re.search(r"!\[[^\]]*\]\([^)]+\)", readme):
        fail("no image in README.md")


def readme_has_a_mermaid_block() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "```mermaid" not in readme:
        fail("no mermaid block in README.md")


def build_checks() -> list[tuple[str, Callable[[], None]]]:
    checks: list[tuple[str, Callable[[], None]]] = []
    for method, path in REQUIRED_ROUTES:
        checks.append(
            (f"route {method} {path}", lambda m=method, p=path: route_exists(m, p))
        )
    checks += [
        ("users.token_hash exists", token_hash_column_exists),
        ("Redis answers a ping", redis_answers),
        ("snapshot row for the current week", snapshot_for_this_week),
        ("audit log has at least one row", audit_log_has_a_row),
    ]
    for relative in REQUIRED_FILES:
        checks.append((f"file {relative}", lambda r=relative: file_exists(r)))
    checks += [
        ("README has an image", readme_has_an_image),
        ("README has a mermaid block", readme_has_a_mermaid_block),
    ]
    return checks


def main() -> int:
    checks = build_checks()
    failed = 0
    for name, check in checks:
        try:
            check()
        except (AssertionError, SQLAlchemyError, redis.RedisError, OSError) as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
        else:
            print(f"PASS  {name}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
