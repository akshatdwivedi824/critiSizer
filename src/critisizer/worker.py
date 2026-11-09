"""Background worker: python -m critisizer.worker [--once] [--enqueue-all]."""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer.db import SessionLocal
from critisizer.evidence.collect import collect_for_policy
from critisizer.evidence.gdelt import CollectError, GdeltClient
from critisizer.evidence.text import fetch_article_text
from critisizer.jobs import claim_next, enqueue, fail, finish, recover_stuck
from critisizer.models import Job, Policy

logger = logging.getLogger("critisizer.worker")

POLL_SECONDS = 5
RETRY_DEFAULT = timedelta(minutes=1)
RETRY_RATE_LIMITED = timedelta(minutes=15)

Handler = Callable[[Session, Job], None]


def handle_collect(
    session: Session,
    job: Job,
    client: GdeltClient,
    fetch: Callable[[str], str | None] = fetch_article_text,
) -> None:
    policy = session.get(Policy, job.policy_id) if job.policy_id else None
    if policy is None:
        raise LookupError("policy_missing")
    collect_for_policy(session, policy, client, fetch)


def run_once(
    session: Session, handlers: dict[str, Handler], now: datetime | None = None
) -> bool:
    """Run at most one due job. Returns False when there was nothing to do."""
    recover_stuck(session, now)
    job = claim_next(session, now)
    if job is None:
        return False
    handler = handlers.get(job.kind)
    if handler is None:
        fail(job, "unknown_kind", RETRY_DEFAULT, now, permanent=True)
        return True
    try:
        with session.begin_nested():  # a crash rolls back its partial writes
            handler(session, job)
    except CollectError as exc:
        fail(job, f"CollectError: {exc}", RETRY_RATE_LIMITED, now)
    except Exception as exc:  # noqa: BLE001 - any failure is recorded on the job
        fail(job, f"{type(exc).__name__}: {exc}", RETRY_DEFAULT, now)
    else:
        finish(job, now)
    return True


def build_handlers(client: GdeltClient) -> dict[str, Handler]:
    return {"collect": lambda session, job: handle_collect(session, job, client)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="critisizer.worker")
    parser.add_argument("--once", action="store_true", help="drain due jobs, then exit")
    parser.add_argument("--enqueue-all", action="store_true", help="queue collection for every policy")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.enqueue_all:
        with SessionLocal() as session:
            ids = session.scalars(select(Policy.id)).all()
            for policy_id in ids:
                enqueue(session, "collect", policy_id)
            session.commit()
        logger.info("queued collection for %d policies", len(ids))
        return

    handlers = build_handlers(GdeltClient())
    while True:
        with SessionLocal() as session:
            did_work = run_once(session, handlers)
            session.commit()
        if did_work:
            logger.info("ran one job")
            continue
        if args.once:
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()