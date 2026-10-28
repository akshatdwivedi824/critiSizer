from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
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