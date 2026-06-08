"""Add location search fields to candidate_profiles

Adds home_city, home_lat, home_lng, search_radius_km, target_cities,
and search_mode to support Phase 1 location-aware job search.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-08
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from alembic import op

revision = "0022_candidate_profile_location"
down_revision = "0021_job_score_qualification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidate_profiles", sa.Column("home_city", sa.String(255), nullable=True))
    op.add_column("candidate_profiles", sa.Column("home_lat", sa.Float(), nullable=True))
    op.add_column("candidate_profiles", sa.Column("home_lng", sa.Float(), nullable=True))
    op.add_column("candidate_profiles", sa.Column("search_radius_km", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("candidate_profiles", sa.Column("target_cities", ARRAY(sa.String(255)), nullable=True))
    op.add_column("candidate_profiles", sa.Column("search_mode", sa.String(16), nullable=False, server_default="remote"))


def downgrade() -> None:
    op.drop_column("candidate_profiles", "search_mode")
    op.drop_column("candidate_profiles", "target_cities")
    op.drop_column("candidate_profiles", "search_radius_km")
    op.drop_column("candidate_profiles", "home_lng")
    op.drop_column("candidate_profiles", "home_lat")
    op.drop_column("candidate_profiles", "home_city")
