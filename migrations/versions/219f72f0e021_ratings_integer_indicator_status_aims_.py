"""ratings integer, indicator status, aims and source items

Revision ID: 219f72f0e021
Revises: f03fbd8bdfcf
Create Date: 2026-11-06 09:36:00.100303

"""

from sqlalchemy.dialects import postgresql
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '219f72f0e021'
down_revision: Union[str, Sequence[str], None] = 'f03fbd8bdfcf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ratings are whole numbers only.
    op.alter_column(
        "ratings",
        "value",
        existing_type=sa.Numeric(5, 2),
        type_=sa.SmallInteger(),
        existing_nullable=False,
        postgresql_using="round(value)::smallint",
    )

    op.add_column("policies", sa.Column("summary_source_url", sa.Text(), nullable=True))

    # AI drafts reuse indicators; existing rows stay approved.
    op.add_column(
        "indicators",
        sa.Column("status", sa.String(20), server_default="approved", nullable=False),
    )
    op.add_column("indicators", sa.Column("model", sa.String(100), nullable=True))
    op.add_column(
        "indicators", sa.Column("prompt_version", sa.String(50), nullable=True)
    )
    op.create_check_constraint(
        "ck_indicators_status_allowed",
        "indicators",
        "status IN ('ai_draft', 'approved', 'rejected')",
    )

    op.create_table(
        "policy_aims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("policies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status", sa.String(20), server_default="ai_draft", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ai_draft', 'approved', 'rejected')",
            name="ck_policy_aims_status_allowed",
        ),
    )
    op.create_index("ix_policy_aims_policy_id", "policy_aims", ["policy_id"])

    op.create_table(
        "evidence_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("policies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_version", sa.String(20), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("source_api", sa.String(50), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_evidence_runs_policy_id", "evidence_runs", ["policy_id"])

    op.create_table(
        "source_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("evidence_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("policies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("outlet", sa.String(200), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("policy_id", "content_hash"),
    )
    op.create_index("ix_source_items_run_id", "source_items", ["run_id"])
    op.create_index("ix_source_items_policy_id", "source_items", ["policy_id"])

    op.add_column("evidence", sa.Column("quote", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("source_item_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_evidence_source_item_id",
        "evidence",
        "source_items",
        ["source_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_evidence_source_item_id", "evidence", type_="foreignkey")
    op.drop_column("evidence", "source_item_id")
    op.drop_column("evidence", "quote")

    op.drop_table("source_items")
    op.drop_table("evidence_runs")
    op.drop_table("policy_aims")

    op.drop_constraint("ck_indicators_status_allowed", "indicators", type_="check")
    op.drop_column("indicators", "prompt_version")
    op.drop_column("indicators", "model")
    op.drop_column("indicators", "status")

    op.drop_column("policies", "summary_source_url")

    op.alter_column(
        "ratings",
        "value",
        existing_type=sa.SmallInteger(),
        type_=sa.Numeric(5, 2),
        existing_nullable=False,
        postgresql_using="value::numeric(5,2)",
    )