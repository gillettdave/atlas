"""Add text_edited_at to career_facts — tracks when fact_text was manually edited

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_career_fact_text_edited_at"
down_revision = "0019_candidate_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "career_facts",
        sa.Column("text_edited_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("career_facts", "text_edited_at")
