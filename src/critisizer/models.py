from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from critisizer.db import Base


class Aspect(Base):
    __tablename__ = "aspects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    definition: Mapped[str] = mapped_column(Text)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    year: Mapped[int]
    summary: Mapped[str] = mapped_column(Text)
    summary_source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PolicyAim(Base):
    """What the government says the policy is for. Shown, never scored."""

    __tablename__ = "policy_aims"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ai_draft', 'approved', 'rejected')",
            name="ck_policy_aims_status_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(server_default="0")
    status: Mapped[str] = mapped_column(String(20), server_default="ai_draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RubricVersion(Base):
    __tablename__ = "rubric_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(50), unique=True)
    min_ratings: Mapped[int] = mapped_column(default=5)
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RubricWeight(Base):
    __tablename__ = "rubric_weights"
    __table_args__ = (
        UniqueConstraint("rubric_version_id", "aspect_id"),
        CheckConstraint("weight > 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rubric_version_id: Mapped[int] = mapped_column(
        ForeignKey("rubric_versions.id", ondelete="CASCADE")
    )
    aspect_id: Mapped[int] = mapped_column(ForeignKey("aspects.id"))
    weight: Mapped[Decimal] = mapped_column(Numeric(6, 2))


class Indicator(Base):
    __tablename__ = "indicators"
    __table_args__ = (
        CheckConstraint(
            "score >= 0 AND score <= 100", name="ck_indicators_score_range"
        ),
        CheckConstraint("weight > 0", name="ck_indicators_weight_positive"),
        CheckConstraint(
            "status IN ('ai_draft', 'approved', 'rejected')",
            name="ck_indicators_status_allowed",
        ),
        CheckConstraint(
            "evidence_status IN ('realised', 'alleged', 'projected')",
            name="ck_indicators_evidence_status_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True
    )
    aspect_id: Mapped[int] = mapped_column(ForeignKey("aspects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    weight: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default="1")
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="approved")
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    evidence_status: Mapped[str] = mapped_column(
        String(20), server_default="realised"
    )
    # For a projected indicator: who made the forecast (a named source).
    projection_source: Mapped[str | None] = mapped_column(Text)


class AspectReview(Base):
    """A reviewer's recorded finding on an aspect with no approved indicator:
    either that the collected sources hold no negative evidence for it, or that
    it is too early to assess (with a date to look again). Without this row or
    an approved indicator, the aspect is unresolved."""

    __tablename__ = "aspect_reviews"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "aspect_id", name="uq_aspect_reviews_policy_aspect"
        ),
        CheckConstraint(
            "outcome IN ('no_negative_evidence', 'too_early')",
            name="ck_aspect_reviews_outcome_allowed",
        ),
        CheckConstraint(
            "outcome <> 'too_early' OR review_date IS NOT NULL",
            name="ck_aspect_reviews_too_early_needs_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True
    )
    aspect_id: Mapped[int] = mapped_column(ForeignKey("aspects.id"))
    outcome: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    # When a "too early" finding is due to be looked at again.
    review_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("indicator_id", "content_hash"),
        CheckConstraint(
            "source_tier >= 1 AND source_tier <= 4", name="ck_evidence_tier_range"
        ),
        CheckConstraint(
            "verification_multiplier IN (1.00, 0.80, 0.50, 0.00)",
            name="ck_evidence_multiplier_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    indicator_id: Mapped[int] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE")
    )
    source_url: Mapped[str] = mapped_column(Text)
    source_title: Mapped[str] = mapped_column(String(300))
    source_tier: Mapped[int]
    verification_multiplier: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    content_hash: Mapped[str] = mapped_column(String(64))
    archived_location: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    source_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_items.id", ondelete="SET NULL")
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EvidenceRun(Base):
    """One fetch of source material for a policy, with the raw response kept."""

    __tablename__ = "evidence_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True
    )
    query_version: Mapped[str] = mapped_column(String(20))
    query_text: Mapped[str] = mapped_column(Text)
    source_api: Mapped[str] = mapped_column(String(50))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    result_count: Mapped[int] = mapped_column(server_default="0")
    raw: Mapped[Any | None] = mapped_column(JSONB)


class SourceItem(Base):
    """A collected article or document excerpt, stored once per policy."""

    __tablename__ = "source_items"
    __table_args__ = (UniqueConstraint("policy_id", "content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_runs.id", ondelete="CASCADE"), index=True
    )
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    outlet: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excerpt: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'moderator', 'admin')", name="ck_users_role_allowed"
        ),
        UniqueConstraint("token_hash", name="uq_users_token_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(20), server_default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "policy_id"),
        CheckConstraint("value >= 0 AND value <= 100", name="ck_ratings_value_range"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="ck_ratings_status_allowed",
        ),
        Index("ix_ratings_policy_status", "policy_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE")
    )
    value: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    __table_args__ = (
        UniqueConstraint("policy_id", "rubric_version_id", "week"),
        CheckConstraint(
            "expert_average >= 0 AND expert_average <= 100",
            name="ck_snapshots_expert_range",
        ),
        CheckConstraint(
            "overall_rating >= 0 AND overall_rating <= 100",
            name="ck_snapshots_overall_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE")
    )
    rubric_version_id: Mapped[int] = mapped_column(ForeignKey("rubric_versions.id"))
    week: Mapped[date]
    aspect_scores: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expert_average: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    people_rating: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    people_rating_count: Mapped[int] = mapped_column(server_default="0")
    overall_rating: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    spike_flag: Mapped[bool]
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[int | None]
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    """A unit of background work. Claimed by the worker, never by a web request."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_jobs_status_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), server_default="queued")
    attempts: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))