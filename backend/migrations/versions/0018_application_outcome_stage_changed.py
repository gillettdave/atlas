"""application_job_tracks — structured outcome + stage_changed_at (W6).

Revision ID: 0018_application_outcomes
Revises: 0017_cs_src_user_id
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018_application_outcomes"
down_revision: Union[str, None] = "0017_cs_src_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OUTCOME_CHECK = (
    "application_outcome IS NULL OR application_outcome IN ("
    "'rejected', 'interviewing', 'offered', 'hired', 'withdrawn')"
)


def upgrade() -> None:
    op.add_column(
        "application_job_tracks",
        sa.Column(
            "application_outcome",
            sa.String(length=24),
            nullable=True,
        ),
    )
    op.add_column(
        "application_job_tracks",
        sa.Column(
            "stage_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE application_job_tracks SET stage_changed_at = "
            "COALESCE(updated_at, created_at) WHERE stage_changed_at IS NULL"
        )
    )
    op.create_check_constraint(
        "ck_application_job_tracks_outcome",
        "application_job_tracks",
        _OUTCOME_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_application_job_tracks_outcome",
        "application_job_tracks",
        type_="check",
    )
    op.drop_column("application_job_tracks", "stage_changed_at")
    op.drop_column("application_job_tracks", "application_outcome")
