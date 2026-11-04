import secrets
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select

from critisizer import cache
from critisizer.audit import record_audit
from critisizer.auth import bearer
from critisizer.config import get_settings
from critisizer.deps import SessionDep
from critisizer.models import Policy, Rating

ACTIONS = {"accepted": "rating.accept", "rejected": "rating.reject"}


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    """Admin endpoints need the ADMIN_TOKEN. A missing or empty token is refused."""
    expected = get_settings().admin_token
    supplied = credentials.credentials if credentials else ""
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Admin access required")


router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


class AdminRatingOut(BaseModel):
    id: int
    policy_slug: str
    user_id: int
    value: float
    status: str
    comment: str | None
    created_at: datetime


def _out(rating: Rating, slug: str) -> AdminRatingOut:
    return AdminRatingOut(
        id=rating.id,
        policy_slug=slug,
        user_id=rating.user_id,
        value=float(rating.value),
        status=rating.status,
        comment=rating.comment,
        created_at=rating.created_at,
    )


@router.get("/ratings", response_model=list[AdminRatingOut])
def list_ratings(
    session: SessionDep,
    status: Literal["pending", "accepted", "rejected"] = "pending",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AdminRatingOut]:
    rows = session.execute(
        select(Rating, Policy.slug)
        .join(Policy, Policy.id == Rating.policy_id)
        .where(Rating.status == status)
        .order_by(Rating.id)
        .limit(limit)
    ).all()
    return [_out(rating, slug) for rating, slug in rows]


def _moderate(session, rating_id: int, new_status: str) -> AdminRatingOut:
    # FOR UPDATE: two admins acting on the same rating at once cannot both
    # pass the "is it pending?" check.
    row = session.execute(
        select(Rating, Policy.slug)
        .join(Policy, Policy.id == Rating.policy_id)
        .where(Rating.id == rating_id)
        .with_for_update(of=Rating)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Rating not found")
    rating, slug = row
    if rating.status != "pending":
        raise HTTPException(
            status_code=409, detail=f"Rating is already {rating.status}"
        )

    old_status = rating.status
    # The change and its audit row are one unit: if either fails, neither stays.
    with session.begin_nested():
        rating.status = new_status
        record_audit(
            session,
            ACTIONS[new_status],
            "rating",
            rating.id,
            {
                "rating_id": rating.id,
                "old_status": old_status,
                "new_status": new_status,
                "via": "admin-token",
            },
        )
    session.commit()

    # Only after the commit, so a reader cannot re-fill the cache with old data.
    if new_status == "accepted":
        cache.delete_prefix(cache.LIST_CACHE_PREFIX)
    return _out(rating, slug)


@router.post("/ratings/{rating_id}/accept", response_model=AdminRatingOut)
def accept_rating(rating_id: int, session: SessionDep) -> AdminRatingOut:
    return _moderate(session, rating_id, "accepted")


@router.post("/ratings/{rating_id}/reject", response_model=AdminRatingOut)
def reject_rating(rating_id: int, session: SessionDep) -> AdminRatingOut:
    return _moderate(session, rating_id, "rejected")
