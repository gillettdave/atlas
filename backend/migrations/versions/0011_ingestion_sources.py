"""ingestion_sources — DB-backed source list (Phase C stub).

Revision ID: 0011_ingestion_sources
Revises: 0010_career_memory_tables
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_ingestion_sources"
down_revision: Union[str, None] = "0010_career_memory_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("jobs_page_url", sa.Text(), nullable=True),
        sa.Column("careers_site_url", sa.Text(), nullable=True),
        sa.Column("ats_board_url", sa.Text(), nullable=True),
        sa.Column("ats_type", sa.String(length=64), nullable=True),
        sa.Column("resolution_type", sa.String(length=64), nullable=True),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_ingestion_sources_user_id", "ingestion_sources", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_sources_user_id", table_name="ingestion_sources")
    op.drop_table("ingestion_sources")
