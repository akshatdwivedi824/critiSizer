from decimal import Decimal

from fastapi import APIRouter, HTTPException
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from critisizer.auth import CurrentUser
from critisizer.deps import SessionDep
from critisizer.models import Policy, Rating
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


class RatingIn(BaseModel):
    value: float = Field(ge=0, le=100)
    comment: str | None = Field(default=None, max_length=1000)


class RatingOut(BaseModel):
    id: int
    policy_slug: str
    value: float
    status: str


@router.post("/policies/{slug}/ratings", response_model=RatingOut, status_code=201)
def rate_policy(
    slug: str, body: RatingIn, user: CurrentUser, session: SessionDep
) -> RatingOut:
    policy = session.scalar(select(Policy).where(Policy.slug == slug))
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    rating = Rating(
        user_id=user.id,
        policy_id=policy.id,
        value=Decimal(str(body.value)).quantize(Decimal("0.01")),
        comment=body.comment,
    )
    try:
        with session.begin_nested():
            session.add(rating)
    except IntegrityError as exc:
        if isinstance(exc.orig, UniqueViolation):
            raise HTTPException(409, "You have already rated this policy") from exc
        raise
    session.commit()
    return RatingOut(
        id=rating.id,
        policy_slug=policy.slug,
        value=float(rating.value),
        status=rating.status,
    )
