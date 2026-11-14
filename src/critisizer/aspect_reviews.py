"""Reviewer decisions on an aspect that has no approved indicator: either "no
negative evidence in the collected sources" or "too early to assess" (with a
date to look again). Without one of these or an approved indicator, an aspect is
unresolved."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from critisizer import cache
from critisizer.admin import require_admin
from critisizer.audit import record_audit
from critisizer.deps import SessionDep
from critisizer.models import Aspect, AspectReview, Indicator, Policy
from critisizer.scorecard import (
    MIN_OUTLETS,
    MIN_SOURCES,
    evidence_depth,
    policy_progress,
)

OUTCOME = "no_negative_evidence"
TOO_EARLY = "too_early"

router = APIRouter(
    prefix="/api/admin/policies/{slug}",
    tags=["aspect-review"],
    dependencies=[Depends(require_admin)],
)


class NoNegativeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class TooEarlyIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)
    review_date: date


class AspectState(BaseModel):
    code: str
    name: str
    status: Literal[
        "scored", "no_negative_evidence", "projected", "too_early", "unresolved"
    ]
    pending_drafts: int
    reason: str | None
    review_date: date | None = None


class ResolutionOut(BaseModel):
    policy_slug: str
    aspect: str
    outcome: str | None
    aspects_resolved: int
    aspects_assessed: int = 0
    aspects_total: int
    rated: bool


def _load(session, slug: str, code: str) -> tuple[Policy, Aspect]:
    policy = session.scalar(select(Policy).where(Policy.slug == slug))
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    aspect = session.scalar(select(Aspect).where(Aspect.code == code))
    if aspect is None:
        raise HTTPException(status_code=404, detail="Aspect not found")
    return policy, aspect


def _count(session, policy_id: int, aspect_id: int, status: str) -> int:
    return session.scalar(
        select(func.count(Indicator.id)).where(
            Indicator.policy_id == policy_id,
            Indicator.aspect_id == aspect_id,
            Indicator.status == status,
        )
    )


def _out(session, policy: Policy, aspect: Aspect, outcome: str | None) -> ResolutionOut:
    progress = policy_progress(session, policy.id)
    return ResolutionOut(
        policy_slug=policy.slug,
        aspect=aspect.code,
        outcome=outcome,
        aspects_resolved=progress.resolved,
        aspects_assessed=progress.assessed,
        aspects_total=progress.total,
        rated=progress.rated,
    )


def _check_open(session, policy: Policy, aspect: Aspect) -> None:
    """An aspect can only be marked while it has no approved or pending indicator."""
    if _count(session, policy.id, aspect.id, "approved"):
        raise HTTPException(
            status_code=409, detail="This aspect already has an approved indicator"
        )
    if _count(session, policy.id, aspect.id, "ai_draft"):
        raise HTTPException(
            status_code=409,
            detail="Review the pending drafts for this aspect first",
        )


def _save_review(
    session, policy: Policy, aspect: Aspect, review: AspectReview, action: str,
    details: dict,
) -> None:
    try:
        with session.begin_nested():
            session.add(review)
            session.flush()
            record_audit(
                session,
                action,
                "aspect_review",
                review.id,
                {
                    "policy": policy.slug,
                    "aspect": aspect.code,
                    "reason": review.reason,
                    **details,
                    "via": "admin-token",
                },
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="This aspect is already marked; reopen it first",
        ) from exc
    session.commit()
    cache.delete_prefix(cache.LIST_CACHE_PREFIX)


@router.get("/aspects", response_model=list[AspectState])
def list_aspect_states(slug: str, session: SessionDep) -> list[AspectState]:
    policy = session.scalar(select(Policy).where(Policy.slug == slug))
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    progress = policy_progress(session, policy.id)
    review_rows = session.execute(
        select(Aspect.code, AspectReview.reason, AspectReview.review_date)
        .join(AspectReview, AspectReview.aspect_id == Aspect.id)
        .where(AspectReview.policy_id == policy.id)
    ).all()
    reasons = {code: reason for code, reason, _ in review_rows}
    dates = {code: when for code, _, when in review_rows}
    drafts = dict(
        session.execute(
            select(Indicator.aspect_id, func.count(Indicator.id))
            .where(Indicator.policy_id == policy.id, Indicator.status == "ai_draft")
            .group_by(Indicator.aspect_id)
        ).all()
    )
    aspects = session.scalars(select(Aspect).order_by(Aspect.id)).all()
    return [
        AspectState(
            code=a.code,
            name=a.name,
            status=progress.status(a.code),
            pending_drafts=drafts.get(a.id, 0),
            reason=reasons.get(a.code),
            review_date=dates.get(a.code),
        )
        for a in aspects
    ]


@router.post(
    "/aspects/{code}/no-negative-evidence",
    response_model=ResolutionOut,
    status_code=201,
)
def mark_no_negative_evidence(
    slug: str, code: str, body: NoNegativeIn, session: SessionDep
) -> ResolutionOut:
    policy, aspect = _load(session, slug, code)
    _check_open(session, policy, aspect)
    sources, outlets = evidence_depth(session, policy.id)
    if sources < MIN_SOURCES or outlets < MIN_OUTLETS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Too little evidence to say 'none found': {sources} sources from "
                f"{outlets} outlets (need {MIN_SOURCES} from {MIN_OUTLETS})"
            ),
        )
    review = AspectReview(
        policy_id=policy.id,
        aspect_id=aspect.id,
        outcome=OUTCOME,
        reason=body.reason.strip(),
    )
    _save_review(
        session,
        policy,
        aspect,
        review,
        "aspect.no_negative_evidence",
        {"sources": sources, "outlets": outlets},
    )
    return _out(session, policy, aspect, OUTCOME)


@router.post(
    "/aspects/{code}/too-early",
    response_model=ResolutionOut,
    status_code=201,
)
def mark_too_early(
    slug: str, code: str, body: TooEarlyIn, session: SessionDep
) -> ResolutionOut:
    """Record that an aspect cannot yet be assessed, with a reason and the date
    it should be looked at again. This is not a claim of "no harm"."""
    policy, aspect = _load(session, slug, code)
    if body.review_date <= date.today():
        raise HTTPException(
            status_code=422, detail="review_date must be in the future"
        )
    _check_open(session, policy, aspect)
    review = AspectReview(
        policy_id=policy.id,
        aspect_id=aspect.id,
        outcome=TOO_EARLY,
        reason=body.reason.strip(),
        review_date=body.review_date,
    )
    _save_review(
        session,
        policy,
        aspect,
        review,
        "aspect.too_early",
        {"review_date": body.review_date.isoformat()},
    )
    return _out(session, policy, aspect, TOO_EARLY)


@router.delete("/aspects/{code}/no-negative-evidence", response_model=ResolutionOut)
def reopen_aspect(slug: str, code: str, session: SessionDep) -> ResolutionOut:
    """Remove a reviewer's finding (either kind) so the aspect is open again."""
    policy, aspect = _load(session, slug, code)
    review = session.scalar(
        select(AspectReview)
        .where(AspectReview.policy_id == policy.id, AspectReview.aspect_id == aspect.id)
        .with_for_update()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="This aspect is not marked")
    with session.begin_nested():
        record_audit(
            session,
            "aspect.reopen",
            "aspect_review",
            review.id,
            {
                "policy": policy.slug,
                "aspect": aspect.code,
                "previous_outcome": review.outcome,
                "previous_reason": review.reason,
                "via": "admin-token",
            },
        )
        session.delete(review)
    session.commit()
    cache.delete_prefix(cache.LIST_CACHE_PREFIX)
    return _out(session, policy, aspect, None)