"""delivery_schedules

Revision ID: 0003_delivery_schedules
Revises: 0002_user_profiles
Create Date: 2026-04-24

Sprint H: persistent schedule rows that tell the scheduler loop what
digest to build, how often, and where to ship it.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0003_delivery_schedules"
down_revision: Union[str, None] = "0002_user_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "delivery_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        # daily | hourly | every_n_minutes
        sa.Column("cadence", sa.String(length=32), nullable=False),
        sa.Column("hour_utc", sa.Integer(), nullable=True),
        sa.Column("minute_utc", sa.Integer(), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),

        sa.Column("profile_slug", sa.String(length=64), nullable=True),
        sa.Column(
            "digest_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),

        # slack | email | csv_only | none
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column(
            "recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "include_hidden_gems",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),

        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),

        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        # ok | error | skipped
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "last_digest_id", postgresql.UUID(as_uuid=True), nullable=True
        ),

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

        sa.ForeignKeyConstraint(
            ["last_digest_id"], ["digests.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("name", name="uq_delivery_schedules_name"),
    )
    op.create_index(
        "ix_delivery_schedules_active", "delivery_schedules", ["is_active"]
    )
    op.create_index(
        "ix_delivery_schedules_next_run",
        "delivery_schedules",
        ["next_run_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delivery_schedules_next_run", table_name="delivery_schedules"
    )
    op.drop_index(
        "ix_delivery_schedules_active", table_name="delivery_schedules"
    )
    op.drop_table("delivery_schedules")
