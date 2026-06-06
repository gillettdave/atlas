"""collector_schedules.use_ingestion_sources — collect from ingestion_sources rows.

Revision ID: 0016_collector_use_db_src
Revises: 0015_discovery_email_intake
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# Keep <= 32 chars: alembic_version.version_num is VARCHAR(32).
revision: str = "0016_collector_use_db_src"
down_revision: Union[str, None] = "0015_discovery_email_intake"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collector_schedules",
        sa.Column(
            "use_ingestion_sources",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column(
        "collector_schedules",
        "use_ingestion_sources",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("collector_schedules", "use_ingestion_sources")
