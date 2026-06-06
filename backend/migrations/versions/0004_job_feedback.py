"""job_feedback

Revision ID: 0004_job_feedback
Revises: 0003_delivery_schedules
Create Date: 2026-04-24

Sprint I: append-only event log of user reactions to jobs. Used by
the digest builder to avoid re-showing resolved jobs, and eventually
by the ranker to learn weight nudges.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0004_job_feedback"
down_revision: Union[str, None] = "0003_delivery_schedules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment=(
                "Profile this feedback was given under. Null = pre-Sprint-G "
                "or anonymous. The API layer fills it with the default "
                "profile when slug is omitted."
            ),
        ),
        # saved | dismissed | applied | interviewed | rejected | clicked
        sa.Column("action", sa.String(length=32), nullable=False),
        # ui | email_click | slack_reaction | api
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="ui",
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["user_profiles.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_job_feedback_job_profile_created",
        "job_feedback",
        ["job_id", "profile_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_job_feedback_profile_action",
        "job_feedback",
        ["profile_id", "action"],
    )
    op.create_index(
        "ix_job_feedback_created_at",
        "job_feedback",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_job_feedback_created_at", table_name="job_feedback")
    op.drop_index("ix_job_feedback_profile_action", table_name="job_feedback")
    op.drop_index(
        "ix_job_feedback_job_profile_created", table_name="job_feedback"
    )
    op.drop_table("job_feedback")
