"""Reviewer decisions that an aspect has no negative evidence in the collected
sources. Without one of these or an approved indicator, an aspect is unresolved
and the policy gets no overall rating."""

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

router = APIRouter(
    prefix="/api/admin/policies/{slug}",
    tags=["aspect-review"],
    dependencies=[Depends(require_admin)],
)


class NoNegativeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class AspectState(BaseModel):
    code: str
    name: str
    status: Literal["scored", "no_negative_evidence", "unresolved"]
    pending_drafts: int
    reason: str | None


class ResolutionOut(BaseModel):
    policy_slug: str
    aspect: str
    outcome: str | None
    aspects_resolved: int
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
        aspects_total=progress.total,
        rated=progress.rated,
    )


@router.get("/aspects", response_model=list[AspectState])
def list_aspect_states(slug: str, session: SessionDep) -> list[AspectState]:
    policy = session.scalar(select(Policy).where(Policy.slug == slug))
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    progress = policy_progress(session, policy.id)
    reasons = dict(
        session.execute(
            select(Aspect.code, AspectReview.reason)
            .join(AspectReview, AspectReview.aspect_id == Aspect.id)
            .where(AspectReview.policy_id == policy.id)
        ).all()
    )
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

    if _count(session, policy.id, aspect.id, "approved"):
        raise HTTPException(
            status_code=409, detail="This aspect already has an approved indicator"
        )
    if _count(session, policy.id, aspect.id, "ai_draft"):
        raise HTTPException(
            status_code=409,
            detail="Review the pending drafts for this aspect first",
        )
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
    try:
        with session.begin_nested():
            session.add(review)
            session.flush()
            record_audit(
                session,
                "aspect.no_negative_evidence",
                "aspect_review",
                review.id,
                {
                    "policy": policy.slug,
                    "aspect": aspect.code,
                    "reason": review.reason,
                    "sources": sources,
                    "outlets": outlets,
                    "via": "admin-token",
                },
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="This aspect is already marked"
        ) from exc
    session.commit()
    cache.delete_prefix(cache.LIST_CACHE_PREFIX)
    return _out(session, policy, aspect, OUTCOME)


@router.delete("/aspects/{code}/no-negative-evidence", response_model=ResolutionOut)
def reopen_aspect(slug: str, code: str, session: SessionDep) -> ResolutionOut:
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
                "previous_reason": review.reason,
                "via": "admin-token",
            },
        )
        session.delete(review)
    session.commit()
    cache.delete_prefix(cache.LIST_CACHE_PREFIX)
    return _out(session, policy, aspect, None)
