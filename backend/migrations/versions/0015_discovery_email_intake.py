"""Discovery seeds/events + Gmail IMAP email intake (Jobr port slice).

Revision ID: 0015_discovery_email_intake
Revises: 0014_user_qualification_settings
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_discovery_email_intake"
down_revision: Union[str, None] = "0014_user_qualification_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "discovery_seeds",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("stop_requested", sa.String(length=16), nullable=True),
        sa.Column("cadence_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("max_depth", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_pages", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("max_listing_age_days", sa.Integer(), nullable=True),
        sa.Column("unknown_age_policy", sa.String(length=32), nullable=True),
        sa.Column(
            "include_domains",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "exclude_domains",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("discovery_mode", sa.String(length=16), nullable=False, server_default="balanced"),
        sa.Column(
            "override_out_of_profile",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovery_seeds_user_id", "discovery_seeds", ["user_id"])
    op.create_index("ix_discovery_seeds_next_run", "discovery_seeds", ["next_run_at"])

    op.create_table(
        "discovery_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "discovery_seed_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discovery_seeds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column("discovered_url", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "canonical_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discovery_events_seed_created",
        "discovery_events",
        ["discovery_seed_id", "created_at"],
    )
    op.create_index("ix_discovery_events_user_id", "discovery_events", ["user_id"])

    op.create_table(
        "email_sync_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label_name", sa.String(length=256), nullable=False),
        sa.Column("source_name", sa.String(length=256), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("cadence_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "label_name",
            name="uq_email_sync_sources_user_provider_label",
        ),
    )
    op.create_index("ix_email_sync_sources_user_id", "email_sync_sources", ["user_id"])
    op.create_index("ix_email_sync_sources_next_sync", "email_sync_sources", ["next_sync_at"])

    op.create_table(
        "email_sync_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "email_sync_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("email_sync_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_message_id", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "canonical_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_sync_events_source_created", "email_sync_events", ["email_sync_source_id"])
    op.create_index(
        "ix_email_sync_events_provider_msg",
        "email_sync_events",
        ["email_sync_source_id", "provider_message_id"],
    )


def downgrade() -> None:
    op.drop_table("email_sync_events")
    op.drop_table("email_sync_sources")
    op.drop_table("discovery_events")
    op.drop_table("discovery_seeds")
