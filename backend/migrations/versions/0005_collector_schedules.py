"""collector_schedules — Sprint M.1

Revision ID: 0005_collector_schedules
Revises: 0004_job_feedback
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_collector_schedules"
down_revision: Union[str, None] = "0004_job_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collector_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("cadence", sa.String(length=32), nullable=False),
        sa.Column("hour_utc", sa.Integer(), nullable=True),
        sa.Column("minute_utc", sa.Integer(), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("input_csv_path", sa.Text(), nullable=False),
        sa.Column("source_limit", sa.Integer(), nullable=True),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("headless", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "source_name", sa.String(length=128), nullable=False,
            server_default=sa.text("'web3_ats_collector'"),
        ),
        sa.Column(
            "source_type", sa.String(length=64), nullable=False,
            server_default=sa.text("'ats'"),
        ),
        sa.Column("then_import", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("process_pending_limit", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("then_rank", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("rank_profile_slug", sa.String(length=64), nullable=True),
        sa.Column("rank_only_unscored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rank_limit", sa.Integer(), nullable=True),
        sa.Column("then_digest", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "digest_type", sa.String(length=32), nullable=False,
            server_default=sa.text("'daily'"),
        ),
        sa.Column("digest_fresh_hours", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("digest_fresh_limit", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("digest_gem_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("digest_per_company_cap", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("digest_profile_slug", sa.String(length=64), nullable=True),
        sa.Column(
            "digest_min_ranking_score", sa.String(length=16), nullable=False,
            server_default=sa.text("'35'"),
        ),
        sa.Column(
            "digest_gem_min_score", sa.String(length=16), nullable=False,
            server_default=sa.text("'60'"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_digest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_duration_sec", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["last_ingestion_run_id"], ["ingestion_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_digest_id"], ["digests.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_collector_schedules_is_active", "collector_schedules", ["is_active"])
    op.create_index(
        "ix_collector_schedules_next_run", "collector_schedules", ["next_run_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_collector_schedules_next_run", table_name="collector_schedules")
    op.drop_index("ix_collector_schedules_is_active", table_name="collector_schedules")
    op.drop_table("collector_schedules")
