from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from critisizer.deps import SessionDep
from critisizer.models import Policy
from critisizer.schemas import PolicyDetail, PolicySummary
from critisizer.scorecard import (
    build_policy_detail,
    build_policy_summary,
    load_active_rubric,
)

router = APIRouter(prefix="/api", tags=["policies"])


@router.get("/policies", response_model=list[PolicySummary])
def list_policies(session: SessionDep) -> list[PolicySummary]:
    policies = session.scalars(select(Policy).order_by(Policy.name)).all()
    if not policies:
        return []
    rubric = load_active_rubric(session)
    return [build_policy_summary(session, p, rubric) for p in policies]


@router.get("/policies/{slug}", response_model=PolicyDetail)
def get_policy(slug: str, session: SessionDep) -> PolicyDetail:
    policy = session.scalar(select(Policy).where(Policy.slug == slug))
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    rubric = load_active_rubric(session)
    return build_policy_detail(session, policy, rubric)