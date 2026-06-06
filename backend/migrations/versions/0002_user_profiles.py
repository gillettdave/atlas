"""user_profiles + job_scores.profile_id

Revision ID: 0002_user_profiles
Revises: 0001_initial
Create Date: 2026-04-24

Introduces Ranker v2 primitives:
- `user_profiles` table with per-component weight multipliers and
  custom strong/weak/negative keyword lists.
- `job_scores.profile_id` nullable FK so a job can have parallel scores
  per profile (null == the legacy "global default").
- Seeds a single default profile so v1 semantics are preserved.
"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_user_profiles"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "weights",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "strong_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "weak_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "negative_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("preferred_remote", sa.String(length=16), nullable=True),
        sa.Column(
            "min_score_threshold",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
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
        sa.UniqueConstraint("slug", name="uq_user_profiles_slug"),
    )
    op.create_index(
        "ix_user_profiles_is_active", "user_profiles", ["is_active"]
    )
    # Only ONE default profile at a time. Partial unique index on is_default
    # where is_default = true.
    op.execute(
        "CREATE UNIQUE INDEX uq_user_profiles_single_default "
        "ON user_profiles (is_default) WHERE is_default = true"
    )

    # job_scores.profile_id --------------------------------------------------
    op.add_column(
        "job_scores",
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_job_scores_profile_id",
        "job_scores",
        "user_profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_job_scores_job_profile_created",
        "job_scores",
        ["job_id", "profile_id", sa.text("created_at DESC")],
    )

    # Seed the default profile so Ranker v2 can bootstrap.
    profiles_tbl = sa.table(
        "user_profiles",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.Text),
        sa.column("weights", postgresql.JSONB),
        sa.column("strong_keywords", postgresql.JSONB),
        sa.column("weak_keywords", postgresql.JSONB),
        sa.column("negative_keywords", postgresql.JSONB),
        sa.column("preferred_remote", sa.String),
        sa.column("min_score_threshold", sa.Numeric),
        sa.column("is_default", sa.Boolean),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        profiles_tbl,
        [
            {
                "id": uuid.uuid4(),
                "slug": "default",
                "display_name": "Default",
                "description": (
                    "Ranker v1 equivalent: all weights 1.0, no keyword overrides."
                ),
                "weights": {},
                "strong_keywords": [],
                "weak_keywords": [],
                "negative_keywords": [],
                "preferred_remote": None,
                "min_score_threshold": 0,
                "is_default": True,
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_scores_job_profile_created", table_name="job_scores"
    )
    op.drop_constraint(
        "fk_job_scores_profile_id", "job_scores", type_="foreignkey"
    )
    op.drop_column("job_scores", "profile_id")

    op.execute("DROP INDEX IF EXISTS uq_user_profiles_single_default")
    op.drop_index("ix_user_profiles_is_active", table_name="user_profiles")
    op.drop_table("user_profiles")
