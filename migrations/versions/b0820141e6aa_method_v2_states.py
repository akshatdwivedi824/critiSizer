"""method v2 states

Revision ID: b0820141e6aa
Revises: 09d20bf1b251
Create Date: 2026-11-14 06:28:35.588057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0820141e6aa'
down_revision: Union[str, Sequence[str], None] = '09d20bf1b251'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "indicators",
        sa.Column(
            "evidence_status",
            sa.String(length=20),
            server_default="realised",
            nullable=False,
        ),
    )
    op.add_column("indicators", sa.Column("projection_source", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_indicators_evidence_status_allowed",
        "indicators",
        "evidence_status IN ('realised', 'alleged', 'projected')",
    )

    op.add_column("aspect_reviews", sa.Column("review_date", sa.Date(), nullable=True))
    op.drop_constraint(
        "ck_aspect_reviews_outcome_allowed", "aspect_reviews", type_="check"
    )
    op.create_check_constraint(
        "ck_aspect_reviews_outcome_allowed",
        "aspect_reviews",
        "outcome IN ('no_negative_evidence', 'too_early')",
    )
    op.create_check_constraint(
        "ck_aspect_reviews_too_early_needs_date",
        "aspect_reviews",
        "outcome <> 'too_early' OR review_date IS NOT NULL",
    )


def downgrade() -> None:
    op.execute("DELETE FROM aspect_reviews WHERE outcome = 'too_early'")
    op.drop_constraint(
        "ck_aspect_reviews_too_early_needs_date", "aspect_reviews", type_="check"
    )
    op.drop_constraint(
        "ck_aspect_reviews_outcome_allowed", "aspect_reviews", type_="check"
    )
    op.create_check_constraint(
        "ck_aspect_reviews_outcome_allowed",
        "aspect_reviews",
        "outcome IN ('no_negative_evidence')",
    )
    op.drop_column("aspect_reviews", "review_date")

    op.drop_constraint(
        "ck_indicators_evidence_status_allowed", "indicators", type_="check"
    )
    op.drop_column("indicators", "projection_source")
    op.drop_column("indicators", "evidence_status")