"""collector_schedule_cron

Revision ID: 0008_collector_schedule_cron
Revises: 0007_delivery_schedule_cron
Create Date: 2026-04-27

Add cron_expression for collector_schedules (parity with delivery_schedules).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_collector_schedule_cron"
down_revision: Union[str, None] = "0007_delivery_schedule_cron"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collector_schedules",
        sa.Column("cron_expression", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("collector_schedules", "cron_expression")
