"""Add qualification scoring columns to job_scores

Adds qualification_score, qualification_reasoning, qualification_scored_at,
and description_hash_at_scoring to job_scores for lazy LLM qualification
caching.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_job_score_qualification"
down_revision = "0020_career_fact_text_edited_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_scores", sa.Column("qualification_score", sa.Float(), nullable=True))
    op.add_column("job_scores", sa.Column("qualification_reasoning", sa.Text(), nullable=True))
    op.add_column("job_scores", sa.Column("qualification_scored_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_scores", sa.Column("description_hash_at_scoring", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("job_scores", "description_hash_at_scoring")
    op.drop_column("job_scores", "qualification_scored_at")
    op.drop_column("job_scores", "qualification_reasoning")
    op.drop_column("job_scores", "qualification_score")
