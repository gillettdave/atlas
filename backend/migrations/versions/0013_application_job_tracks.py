"""application_job_tracks — per-tenant CRM stage on canonical jobs (Phase E1).

Revision ID: 0013_application_job_tracks
Revises: 0012_application_packages
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_application_job_tracks"
down_revision: Union[str, None] = "0012_application_packages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Short stage labels (Jobr-style pipeline; callers may migrate values over time.)
_DEFAULT_STAGE = "interested"


def upgrade() -> None:
    op.create_table(
        "application_job_tracks",
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
            "canonical_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "current_stage",
            sa.String(length=64),
            nullable=False,
            server_default=_DEFAULT_STAGE,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "canonical_job_id",
            name="uq_application_job_tracks_user_job",
        ),
    )
    op.create_index(
        "ix_application_job_tracks_user_stage",
        "application_job_tracks",
        ["user_id", "current_stage"],
    )


def downgrade() -> None:
    op.drop_index("ix_application_job_tracks_user_stage", table_name="application_job_tracks")
    op.drop_table("application_job_tracks")
