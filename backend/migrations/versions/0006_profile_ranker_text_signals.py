"""user_profiles.ranker_text_signals — Ranker v2 text fit

Revision ID: 0006_profile_ranker_text_signals
Revises: 0005_collector_schedules
Create Date: 2026-04-27

Stores a sparse TF–IDF-style reference vector (positive feedback job
descriptions) plus note-mined keyword suggestions per profile.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0006_profile_ranker_text_signals"
down_revision: Union[str, None] = "0005_collector_schedules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "ranker_text_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "ranker_text_signals")
