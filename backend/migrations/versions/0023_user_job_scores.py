"""user_job_scores — per-user current best score per job.

Replaces the digest builder's reliance on jobs.ranking_score (last-writer-wins)
with a per-user score table. One row per (user_id, job_id), updated in-place
on each rescore. Supports multiple users without score interference.

Revision ID: 0023_user_job_scores
Revises: 0022_candidate_profile_location
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0023_user_job_scores"
down_revision = "0022_candidate_profile_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_job_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("profile_slug", sa.String(100), nullable=True),
        sa.Column("hidden_gem", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("bucket", sa.String(16), server_default="skip", nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.UniqueConstraint("user_id", "job_id", name="uq_user_job_scores_user_job"),
    )
    op.create_index("ix_user_job_scores_user_id", "user_job_scores", ["user_id"])
    op.create_index("ix_user_job_scores_job_id", "user_job_scores", ["job_id"])
    op.execute(
        "CREATE INDEX ix_user_job_scores_user_score "
        "ON user_job_scores (user_id, score DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_job_scores_user_score")
    op.drop_index("ix_user_job_scores_job_id", table_name="user_job_scores")
    op.drop_index("ix_user_job_scores_user_id", table_name="user_job_scores")
    op.drop_table("user_job_scores")
