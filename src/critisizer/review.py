"""Human review of AI-drafted indicators. Approve or reject; never edit."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer import cache
from critisizer.admin import require_admin
from critisizer.audit import record_audit
from critisizer.deps import SessionDep
from critisizer.models import Aspect, Evidence, Indicator, Policy, SourceItem

ACTIONS = {"approved": "indicator.approve", "rejected": "indicator.reject"}

router = APIRouter(
    prefix="/api/admin/drafts",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class EvidenceOut(BaseModel):
    quote: str | None
    source_title: str
    source_url: str
    outlet: str | None
    tier: int
    counts: bool  # False when its verification multiplier is 0


class DraftOut(BaseModel):
    id: int
    policy_slug: str
    aspect: str
    name: str
    description: str | None
    score: float
    status: str
    model: str | None
    prompt_version: str | None
    evidence: list[EvidenceOut]


class ApproveIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _evidence_for(session: Session, ids: list[int]) -> dict[int, list[EvidenceOut]]:
    rows = session.execute(
        select(Evidence, SourceItem.outlet)
        .outerjoin(SourceItem, SourceItem.id == Evidence.source_item_id)
        .where(Evidence.indicator_id.in_(ids))
        .order_by(Evidence.id)
    ).all()
    grouped: dict[int, list[EvidenceOut]] = {}
    for evidence, outlet in rows:
        grouped.setdefault(evidence.indicator_id, []).append(
            EvidenceOut(
                quote=evidence.quote,
                source_title=evidence.source_title,
                source_url=evidence.source_url,
                outlet=outlet,
                tier=evidence.source_tier,
                counts=float(evidence.verification_multiplier) > 0,
            )
        )
    return grouped


def _out(
    indicator: Indicator, aspect: str, slug: str, evidence: list[EvidenceOut]
) -> DraftOut:
    return DraftOut(
        id=indicator.id,
        policy_slug=slug,
        aspect=aspect,
        name=indicator.name,
        description=indicator.description,
        score=float(indicator.score),
        status=indicator.status,
        model=indicator.model,
        prompt_version=indicator.prompt_version,
        evidence=evidence,
    )


@router.get("", response_model=list[DraftOut])
def list_drafts(
    session: SessionDep,
    status: Literal["ai_draft", "approved", "rejected"] = "ai_draft",
    slug: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DraftOut]:
    query = (
        select(Indicator, Aspect.code, Policy.slug)
        .join(Aspect, Aspect.id == Indicator.aspect_id)
        .join(Policy, Policy.id == Indicator.policy_id)
        .where(Indicator.status == status)
        .order_by(Indicator.id)
        .limit(limit)
    )
    if slug:
        query = query.where(Policy.slug == slug)
    rows = session.execute(query).all()
    evidence = _evidence_for(session, [row[0].id for row in rows]) if rows else {}
    return [_out(i, code, s, evidence.get(i.id, [])) for i, code, s in rows]


def _review(
    session: Session, indicator_id: int, new_status: str, note: str | None
) -> DraftOut:
    # FOR UPDATE: two reviewers cannot both pass the "is it still a draft?" check.
    row = session.execute(
        select(Indicator, Aspect.code, Policy.slug)
        .join(Aspect, Aspect.id == Indicator.aspect_id)
        .join(Policy, Policy.id == Indicator.policy_id)
        .where(Indicator.id == indicator_id)
        .with_for_update(of=Indicator)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    indicator, aspect, slug = row
    if indicator.status != "ai_draft":
        raise HTTPException(
            status_code=409, detail=f"Indicator is already {indicator.status}"
        )
    evidence = _evidence_for(session, [indicator.id]).get(indicator.id, [])
    if new_status == "approved" and not any(e.counts for e in evidence):
        raise HTTPException(
            status_code=409, detail="No evidence that counts: cannot approve"
        )

    old_status = indicator.status
    key = "reason" if new_status == "rejected" else "note"
    # The change and its audit row are one unit: if either fails, neither stays.
    with session.begin_nested():
        indicator.status = new_status
        record_audit(
            session,
            ACTIONS[new_status],
            "indicator",
            indicator.id,
            {
                "indicator_id": indicator.id,
                "policy_slug": slug,
                "aspect": aspect,
                "old_status": old_status,
                "new_status": new_status,
                key: note,
                "model": indicator.model,
                "prompt_version": indicator.prompt_version,
                "via": "admin-token",
            },
        )
    session.commit()

    if new_status == "approved":  # scores changed: drop the cached policy list
        cache.delete_prefix(cache.LIST_CACHE_PREFIX)
    return _out(indicator, aspect, slug, evidence)


@router.post("/{indicator_id}/approve", response_model=DraftOut)
def approve_draft(
    indicator_id: int, session: SessionDep, body: ApproveIn | None = None
) -> DraftOut:
    return _review(session, indicator_id, "approved", body.note if body else None)


@router.post("/{indicator_id}/reject", response_model=DraftOut)
def reject_draft(indicator_id: int, body: RejectIn, session: SessionDep) -> DraftOut:
    return _review(session, indicator_id, "rejected", body.reason)