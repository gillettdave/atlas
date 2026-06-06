"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-23

Creates the full canonical schema for Project Atlas:
    ingestion_runs, raw_job_events, jobs, job_source_sightings,
    job_scores, digests, digest_items, pipeline_events.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ingestion_runs --------------------------------------------------------
    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'running'")),
        sa.Column("rows_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_ingestion_runs_source_name", "ingestion_runs", ["source_name"])
    op.create_index("ix_ingestion_runs_source_type", "ingestion_runs", ["source_type"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])

    # raw_job_events --------------------------------------------------------
    op.create_table(
        "raw_job_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("fetch_status", sa.String(length=32), nullable=False, server_default="'fetched'"),
        sa.Column("parse_status", sa.String(length=32), nullable=False, server_default="'pending'"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_runs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_raw_job_events_run", "raw_job_events", ["ingestion_run_id"])
    op.create_index("ix_raw_job_events_provider", "raw_job_events", ["provider"])
    op.create_index("ix_raw_job_events_fetch_status", "raw_job_events", ["fetch_status"])
    op.create_index("ix_raw_job_events_parse_status", "raw_job_events", ["parse_status"])
    op.create_index("ix_raw_job_events_created_at", "raw_job_events", ["created_at"])

    # jobs ------------------------------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_job_id", sa.String(length=256), nullable=True),
        sa.Column("company_name", sa.String(length=256), nullable=False),
        sa.Column("normalized_company_name", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("normalized_title", sa.String(length=512), nullable=False),
        sa.Column("location", sa.String(length=256), nullable=True),
        sa.Column("remote_type", sa.String(length=32), nullable=True),
        sa.Column("apply_url", sa.Text(), nullable=False),
        sa.Column("canonical_apply_url", sa.Text(), nullable=False),
        sa.Column("description_clean", sa.Text(), nullable=True),
        sa.Column("description_hash", sa.String(length=64), nullable=True),
        sa.Column("salary_text", sa.String(length=256), nullable=True),
        sa.Column("employment_type", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("quality_score", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("ranking_score", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "external_job_id", name="uq_jobs_provider_external_id"),
        sa.UniqueConstraint("canonical_apply_url", name="uq_jobs_canonical_apply_url"),
    )
    op.create_index("ix_jobs_provider", "jobs", ["provider"])
    op.create_index("ix_jobs_normalized_company_name", "jobs", ["normalized_company_name"])
    op.create_index("ix_jobs_normalized_title", "jobs", ["normalized_title"])
    op.create_index("ix_jobs_apply_url", "jobs", ["apply_url"])
    op.create_index("ix_jobs_canonical_apply_url", "jobs", ["canonical_apply_url"])
    op.create_index("ix_jobs_description_hash", "jobs", ["description_hash"])
    op.create_index("ix_jobs_last_seen_at", "jobs", ["last_seen_at"])
    op.create_index("ix_jobs_is_active", "jobs", ["is_active"])
    op.create_index("ix_jobs_active_seen", "jobs", ["is_active", "last_seen_at"])
    op.create_index("ix_jobs_ranking_score", "jobs", ["ranking_score"])
    op.create_index(
        "ix_jobs_normalized_company_title",
        "jobs",
        ["normalized_company_name", "normalized_title"],
    )

    # job_source_sightings --------------------------------------------------
    op.create_table(
        "job_source_sightings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_domain", sa.String(length=256), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("apply_url", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sponsor_priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sightings_job", "job_source_sightings", ["job_id"])
    op.create_index("ix_sightings_source_kind", "job_source_sightings", ["source_kind"])
    op.create_index("ix_sightings_job_primary", "job_source_sightings", ["job_id", "is_primary"])
    op.create_index("ix_sightings_domain_kind", "job_source_sightings", ["source_domain", "source_kind"])

    # job_scores ------------------------------------------------------------
    op.create_table(
        "job_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Numeric(6, 3), nullable=False),
        sa.Column("bucket", sa.String(length=16), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("hidden_gem", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("freshness_score", sa.Numeric(6, 3), nullable=True),
        sa.Column("fit_score", sa.Numeric(6, 3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_job_scores_job", "job_scores", ["job_id"])
    op.create_index("ix_job_scores_bucket", "job_scores", ["bucket"])
    op.create_index("ix_job_scores_created_at", "job_scores", ["created_at"])

    # digests ---------------------------------------------------------------
    op.create_table(
        "digests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("digest_type", sa.String(length=32), nullable=False, server_default="'daily'"),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_digests_generated_at", "digests", ["generated_at"])
    op.create_index("ix_digests_digest_type", "digests", ["digest_type"])

    # digest_items ----------------------------------------------------------
    op.create_table(
        "digest_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("digest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("lane", sa.String(length=32), nullable=False, server_default="'fresh'"),
        sa.ForeignKeyConstraint(["digest_id"], ["digests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("digest_id", "job_id", name="uq_digest_job"),
    )
    op.create_index("ix_digest_items_digest", "digest_items", ["digest_id"])
    op.create_index("ix_digest_items_job", "digest_items", ["job_id"])

    # pipeline_events -------------------------------------------------------
    op.create_table(
        "pipeline_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_pipeline_events_event_name", "pipeline_events", ["event_name"])
    op.create_index("ix_pipeline_events_entity", "pipeline_events", ["entity_type", "entity_id"])
    op.create_index("ix_pipeline_events_created_at", "pipeline_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("pipeline_events")
    op.drop_table("digest_items")
    op.drop_table("digests")
    op.drop_table("job_scores")
    op.drop_table("job_source_sightings")
    op.drop_table("jobs")
    op.drop_table("raw_job_events")
    op.drop_table("ingestion_runs")
