"""collector_schedules.ingestion_sources_user_id — DB sources tenant.

Revision ID: 0017_cs_src_user_id
Revises: 0016_collector_use_db_src
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0017_cs_src_user_id"
down_revision: Union[str, None] = "0016_collector_use_db_src"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collector_schedules",
        sa.Column(
            "ingestion_sources_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_collector_schedules_ingestion_sources_user_id_users",
        "collector_schedules",
        "users",
        ["ingestion_sources_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_collector_schedules_ingestion_sources_user_id_users",
        "collector_schedules",
        type_="foreignkey",
    )
    op.drop_column("collector_schedules", "ingestion_sources_user_id")
