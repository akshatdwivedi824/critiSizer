from decimal import Decimal

from fastapi import APIRouter, HTTPException, Response
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from critisizer import cache
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

LIST_CACHE_TTL_SECONDS = 60
RATING_LIMIT = 5
RATING_WINDOW_SECONDS = 60


@router.get("/policies", response_model=list[PolicySummary])
def list_policies(session: SessionDep, response: Response) -> list[PolicySummary]:
    policies = session.scalars(select(Policy).order_by(Policy.name)).all()
    if not policies:
        return []
    rubric = load_active_rubric(session)

    # The rubric label is part of the key, so a new rubric never serves old scores.
    key = f"policies:list:v1:{rubric.label}"
    cached = cache.get_json(key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    summaries = [build_policy_summary(session, p, rubric) for p in policies]
    cache.set_json(
        key,
        [s.model_dump(mode="json") for s in summaries],
        LIST_CACHE_TTL_SECONDS,
    )
    response.headers["X-Cache"] = "MISS"
    return summaries


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
    retry_after = cache.hit_rate_limit(
        f"ratelimit:rating:{user.id}", RATING_LIMIT, RATING_WINDOW_SECONDS
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many rating attempts. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
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
