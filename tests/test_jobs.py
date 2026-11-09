from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from critisizer.evidence.gdelt import CollectError
from critisizer.jobs import (
    MAX_ATTEMPTS,
    STUCK_AFTER,
    claim_next,
    enqueue,
    fail,
    finish,
    recover_stuck,
)
from critisizer.models import EvidenceRun, Job, Policy
from critisizer.worker import handle_collect, run_once

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def policy(session):
    row = Policy(slug="job-test", name="Agnipath Scheme", year=2022, summary="x")
    session.add(row)
    session.flush()
    return row


def test_enqueue_creates_a_queued_job_once(session, policy):
    first = enqueue(session, "collect", policy.id, NOW)
    again = enqueue(session, "collect", policy.id, NOW)
    assert first.status == "queued"
    assert again.id == first.id


def test_claim_marks_running_and_is_taken_once(session, policy):
    enqueue(session, "collect", policy.id, NOW)
    job = claim_next(session, NOW)
    assert job.status == "running"
    assert job.attempts == 1
    assert claim_next(session, NOW) is None


def test_claim_skips_jobs_scheduled_for_later(session, policy):
    enqueue(session, "collect", policy.id, NOW + timedelta(hours=1))
    assert claim_next(session, NOW) is None


def test_finish_marks_done(session, policy):
    enqueue(session, "collect", policy.id, NOW)
    job = claim_next(session, NOW)
    finish(job, NOW)
    assert job.status == "done"


def test_failure_requeues_with_a_delay(session, policy):
    enqueue(session, "collect", policy.id, NOW)
    job = claim_next(session, NOW)
    fail(job, "boom", timedelta(minutes=5), NOW)
    assert job.status == "queued"
    assert job.run_after == NOW + timedelta(minutes=5)
    assert claim_next(session, NOW) is None
    assert claim_next(session, NOW + timedelta(minutes=6)) is not None


def test_failure_gives_up_after_max_attempts(session, policy):
    enqueue(session, "collect", policy.id, NOW)
    moment = NOW
    job = None
    for _ in range(MAX_ATTEMPTS):
        job = claim_next(session, moment)
        fail(job, "x", timedelta(minutes=1), moment)
        moment += timedelta(minutes=5)
    assert job.status == "failed"
    assert claim_next(session, moment) is None


def test_stuck_running_jobs_are_recovered(session, policy):
    enqueue(session, "collect", policy.id, NOW)
    job = claim_next(session, NOW)
    assert recover_stuck(session, NOW + timedelta(minutes=5)) == 0
    assert recover_stuck(session, NOW + STUCK_AFTER + timedelta(minutes=1)) == 1
    assert job.status == "queued"


def test_run_once_marks_success_done(session, policy):
    job = enqueue(session, "collect", policy.id, NOW)
    handlers = {"collect": lambda s, j: None}
    assert run_once(session, handlers, NOW) is True
    assert job.status == "done"
    assert run_once(session, handlers, NOW) is False


def test_crashing_handler_rolls_back_its_partial_writes(session, policy):
    job = enqueue(session, "collect", policy.id, NOW)

    def crash(s, j):
        s.add(Policy(slug="partial", name="P", year=2020, summary="x"))
        s.flush()
        raise RuntimeError("boom")

    run_once(session, {"collect": crash}, NOW)
    assert session.scalar(select(Policy).where(Policy.slug == "partial")) is None
    assert job.status == "queued"
    assert "RuntimeError" in job.error


def test_rate_limit_failure_waits_fifteen_minutes(session, policy):
    job = enqueue(session, "collect", policy.id, NOW)

    def throttled(s, j):
        raise CollectError("gave_up")

    run_once(session, {"collect": throttled}, NOW)
    assert job.status == "queued"
    assert job.run_after == NOW + timedelta(minutes=15)


def test_unknown_job_kind_fails_permanently(session):
    job = enqueue(session, "mystery", None, NOW)
    run_once(session, {}, NOW)
    assert job.status == "failed"
    assert job.error == "unknown_kind"


class _EmptyClient:
    def search(self, query):
        return '{"articles": []}', []


def test_collect_handler_records_a_run(session, policy):
    job = enqueue(session, "collect", policy.id, NOW)
    handle_collect(session, job, _EmptyClient())
    runs = session.scalars(select(EvidenceRun)).all()
    assert len(runs) == 1


def test_collect_handler_needs_a_policy(session):
    job = Job(kind="collect", policy_id=None, status="queued", attempts=0, run_after=NOW)
    session.add(job)
    session.flush()
    with pytest.raises(LookupError):
        handle_collect(session, job, _EmptyClient())