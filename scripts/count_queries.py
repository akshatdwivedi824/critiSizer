"""Count the SQL queries and time behind one uncached policy-list request."""

from time import perf_counter

from sqlalchemy import event, select

from critisizer.db import SessionLocal, engine
from critisizer.models import Policy
from critisizer.scorecard import build_policy_summary, load_active_rubric

statements: list[str] = []


@event.listens_for(engine, "before_cursor_execute")
def record(conn, cursor, statement, parameters, context, executemany):
    statements.append(statement)


def run_once(session) -> tuple[int, int, int, float]:
    statements.clear()
    start = perf_counter()
    policies = session.scalars(select(Policy).order_by(Policy.name)).all()
    rubric = load_active_rubric(session)
    setup = len(statements)
    for policy in policies:
        build_policy_summary(session, policy, rubric)
    elapsed = perf_counter() - start
    return len(policies), setup, len(statements), elapsed


def main() -> None:
    with SessionLocal() as session:
        run_once(session)  # warm-up, not counted
        n, setup, total, elapsed = run_once(session)
    per_policy = (total - setup) / n
    per_policy_ms = (elapsed * 1000) / n
    print(f"policies: {n}")
    print(
        f"queries for the whole list: {total} ({setup} fixed + {per_policy:g} per policy)"
    )
    print(
        f"time for the whole list: {elapsed * 1000:.0f} ms ({per_policy_ms:.1f} ms per policy)"
    )
    for size in (100, 2000):
        queries = setup + per_policy * size
        seconds = per_policy_ms * size / 1000
        print(
            f"at {size} policies: about {queries:,.0f} queries, {seconds:.1f} s per uncached list"
        )


if __name__ == "__main__":
    main()
