"""board_collection_log — tracks last collection time per ATS board.

Used by the collector pipeline to skip boards collected within the freshness
window (default 3 days), spreading the 2,300+ board sweep across multiple
daily runs rather than hammering all boards every day.

Revision ID: 0024_board_collection_log
Revises: 0023_user_job_scores
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_board_collection_log"
down_revision = "0023_user_job_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "board_collection_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ats_board_url", sa.Text(), nullable=False, unique=True),
        sa.Column("ats_type", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        # When this board was last successfully collected (any records or empty ok)
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=True),
        # How many consecutive runs timed out — reset to 0 on any successful fetch
        sa.Column("consecutive_timeouts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_timeout_at", sa.DateTime(timezone=True), nullable=True),
        # Total lifetime stats
        sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_board_collection_log_ats_board_url", "board_collection_log", ["ats_board_url"])
    op.create_index("ix_board_collection_log_last_collected_at", "board_collection_log", ["last_collected_at"])
    op.create_index("ix_board_collection_log_ats_type", "board_collection_log", ["ats_type"])


def downgrade() -> None:
    op.drop_table("board_collection_log")
