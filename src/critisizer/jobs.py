"""A small job queue stored in Postgres. Functions flush; callers commit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer.models import Job

MAX_ATTEMPTS = 3
STUCK_AFTER = timedelta(minutes=15)


def _moment(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def enqueue(
    session: Session, kind: str, policy_id: int | None, now: datetime | None = None
) -> Job:
    """Queue a job, or return the one already waiting or running for it."""
    existing = session.scalar(
        select(Job).where(
            Job.kind == kind,
            Job.policy_id == policy_id,
            Job.status.in_(("queued", "running")),
        )
    )
    if existing is not None:
        return existing
    job = Job(
        kind=kind,
        policy_id=policy_id,
        status="queued",
        attempts=0,
        run_after=_moment(now),
    )
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session, now: datetime | None = None) -> Job | None:
    """Take the oldest job that is due. Two workers never get the same job."""
    moment = _moment(now)
    job = session.scalar(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= moment)
        .order_by(Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.started_at = moment
    session.flush()
    return job


def finish(job: Job, now: datetime | None = None) -> None:
    job.status = "done"
    job.error = None
    job.finished_at = _moment(now)


def fail(
    job: Job,
    error: str,
    retry_in: timedelta,
    now: datetime | None = None,
    permanent: bool = False,
) -> None:
    """Record a failure: retry later, or give up after MAX_ATTEMPTS."""
    moment = _moment(now)
    job.error = error[:500]
    if permanent or job.attempts >= MAX_ATTEMPTS:
        job.status = "failed"
        job.finished_at = moment
    else:
        job.status = "queued"
        job.run_after = moment + retry_in


def recover_stuck(session: Session, now: datetime | None = None) -> int:
    """Put jobs that have been 'running' too long back on the queue."""
    moment = _moment(now)
    stuck = session.scalars(
        select(Job).where(
            Job.status == "running", Job.started_at < moment - STUCK_AFTER
        )
    ).all()
    for job in stuck:
        job.status = "queued"
        job.run_after = moment
    session.flush()
    return len(stuck)