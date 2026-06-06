"""application_packages — per-job drafts (Phase D slice).

Revision ID: 0012_application_packages
Revises: 0011_ingestion_sources
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_application_packages"
down_revision: Union[str, None] = "0011_ingestion_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_packages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("strategy_notes", sa.Text(), nullable=False),
        sa.Column("resume_markdown", sa.Text(), nullable=False),
        sa.Column("cover_letter_markdown", sa.Text(), nullable=False),
        sa.Column("generation_tone", sa.String(length=50), nullable=True),
        sa.Column("generation_emphasis", sa.Text(), nullable=True),
        sa.Column("generation_source", sa.String(length=50), nullable=True),
        sa.Column("evidence_used_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "job_id",
            "version",
            name="uq_application_packages_user_job_version",
        ),
    )
    op.create_index(
        "ix_application_packages_user_job",
        "application_packages",
        ["user_id", "job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_application_packages_user_job", table_name="application_packages")
    op.drop_table("application_packages")
