"""Weekly score snapshots: one stored scorecard per (policy, rubric version, week)."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from critisizer.models import Policy, RubricVersion, ScoreSnapshot
from critisizer.scorecard import load_active_rubric, policy_progress, score_policy
from critisizer.scoring.engine import OverallResult, ScoringError

log = logging.getLogger(__name__)

_KEY = ["policy_id", "rubric_version_id", "week"]


def week_start(day: date) -> date:
    """The Monday of the ISO week containing `day`. The one definition of 'week'."""
    return day - timedelta(days=day.weekday())


@dataclass
class SnapshotReport:
    created: int = 0
    replaced: int = 0
    skipped: int = 0
    failed: int = 0
    unscored: int = 0
    unrated: int = 0


def _values(policy_id: int, version_id: int, week: date, result: OverallResult) -> dict:
    return {
        "policy_id": policy_id,
        "rubric_version_id": version_id,
        "week": week,
        # Exact Decimal text, not floats, so a snapshot re-reads without loss.
        "aspect_scores": {
            code: str(score) for code, score in result.aspect_scores.items()
        },
        "expert_average": result.expert_average,
        "people_rating": result.people_rating,
        "people_rating_count": result.people_rating_count,
        "overall_rating": result.overall_rating,
        "spike_flag": result.spike_flag,
    }


def take_snapshots(
    session: Session, week: date, replace: bool = False
) -> SnapshotReport:
    """Store each rated policy's current scores for `week`. The caller commits.

    A policy with no resolved aspect is not yet scored, and one with some
    unresolved aspects is not yet rated; neither gets a snapshot, so the history
    never holds a number that meant "partly reviewed". An existing snapshot for
    the same (policy, rubric version, week) is left alone unless replace=True. A
    policy that fails scoring is logged and skipped; it never stops the others.
    """
    if week != week_start(week):
        raise ValueError(f"week must be a Monday, got {week} ({week:%A})")

    rubric = load_active_rubric(session)
    version_id = session.scalars(
        select(RubricVersion.id).where(RubricVersion.is_active.is_(True))
    ).one()

    report = SnapshotReport()
    policies = session.scalars(select(Policy).order_by(Policy.id)).all()
    for policy in policies:
        progress = policy_progress(session, policy.id)
        if progress.resolved == 0:
            report.unscored += 1
            continue
        if not progress.rated:
            report.unrated += 1
            continue
        try:
            result = score_policy(session, policy.id, rubric)
        except ScoringError:
            log.warning("skipping %s: scoring failed", policy.slug, exc_info=True)
            report.failed += 1
            continue

        values = _values(policy.id, version_id, week, result)
        exists = (
            session.scalar(
                select(ScoreSnapshot.id).where(
                    ScoreSnapshot.policy_id == policy.id,
                    ScoreSnapshot.rubric_version_id == version_id,
                    ScoreSnapshot.week == week,
                )
            )
            is not None
        )
        statement = insert(ScoreSnapshot).values(**values)
        if exists and not replace:
            report.skipped += 1
        elif exists:
            changes = {k: v for k, v in values.items() if k not in _KEY}
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=_KEY,
                    set_={**changes, "computed_at": func.now()},
                )
            )
            report.replaced += 1
        else:
            session.execute(statement.on_conflict_do_nothing(index_elements=_KEY))
            report.created += 1
    return report
