"""delivery_schedule_cron

Revision ID: 0007_delivery_schedule_cron
Revises: 0006_profile_ranker_text_signals
Create Date: 2026-04-27

Add optional cron_expression for cadence=cron (5-field UTC cron).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007_delivery_schedule_cron"
down_revision: Union[str, None] = "0006_profile_ranker_text_signals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "delivery_schedules",
        sa.Column("cron_expression", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("delivery_schedules", "cron_expression")
