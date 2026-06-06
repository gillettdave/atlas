"""users table + tenant-scoped user_profiles

Revision ID: 0009_users_and_profile_scope
Revises: 0008_collector_schedule_cron
Create Date: 2026-04-29

- Introduces ``users`` with a deterministic seeded local tenant row.
- Adds ``user_profiles.user_id`` so ranker profiles are per-tenant
  (compound unique on user_id + slug; one default profile per user).
"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_users_and_profile_scope"
down_revision: Union[str, None] = "0008_collector_schedule_cron"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must match ``app.constants.SEEDED_LOCAL_USER_ID`` (uuid5(NAMESPACE_DNS, …)).
SEEDED_LOCAL_USER_ID = uuid.UUID("d713ee46-77c9-50cb-ac74-17fa99329375")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
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
    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_email_lower_when_present
        ON users (LOWER(TRIM(email)))
        WHERE email IS NOT NULL AND LENGTH(TRIM(email)) > 0
        """
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO users (id, email, display_name)
            VALUES (CAST(:uid AS UUID), NULL, :dname)
            """
        ),
        {"uid": str(SEEDED_LOCAL_USER_ID), "dname": "Local (seeded)"},
    )

    op.add_column(
        "user_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    conn.execute(
        sa.text(
            """
            UPDATE user_profiles
            SET user_id = CAST(:uid AS UUID)
            WHERE user_id IS NULL
            """
        ),
        {"uid": str(SEEDED_LOCAL_USER_ID)},
    )
    op.alter_column(
        "user_profiles",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_user_profiles_user_id",
        "user_profiles",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_user_profiles_user_id", "user_profiles", ["user_id"]
    )

    op.drop_constraint("uq_user_profiles_slug", "user_profiles", type_="unique")
    op.create_unique_constraint(
        "uq_user_profiles_user_slug",
        "user_profiles",
        ["user_id", "slug"],
    )
    op.execute("DROP INDEX IF EXISTS uq_user_profiles_single_default")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_user_profiles_single_default_per_user
        ON user_profiles (user_id)
        WHERE is_default = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_user_profiles_single_default_per_user")
    op.drop_constraint(
        "uq_user_profiles_user_slug",
        "user_profiles",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_user_profiles_slug",
        "user_profiles",
        ["slug"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_user_profiles_single_default
        ON user_profiles (is_default)
        WHERE is_default = true
        """
    )

    op.drop_index("ix_user_profiles_user_id", table_name="user_profiles")
    op.drop_constraint(
        "fk_user_profiles_user_id", "user_profiles", type_="foreignkey"
    )
    op.drop_column("user_profiles", "user_id")

    op.drop_table("users")
