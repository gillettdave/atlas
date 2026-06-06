"""collector_schedules — Sprint M.1 timed collect + import + rank.

Mirrors `delivery_schedules` cadence fields; `input_csv_path` is a path
relative to the project repo root (or absolute) pointing at a
SourceRow CSV.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_col, updated_at_col, uuid_pk


class CollectorSchedule(Base):
    __tablename__ = "collector_schedules"

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    cadence: Mapped[str] = mapped_column(String(32), nullable=False)
    hour_utc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minute_utc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    interval_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 5-field cron (minute hour dom month dow), UTC, when cadence=cron
    cron_expression: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # CSV relative to repo root, or "__ingestion_sources__" when use_ingestion_sources.
    input_csv_path: Mapped[str] = mapped_column(Text, nullable=False)

    #: When true, collector loads SourceRow payloads from ingestion_sources;
    #: use :attr:`ingestion_sources_user_id` or fall back to seeded user.
    use_ingestion_sources: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    ingestion_sources_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    headless: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False, default="web3_ats_collector")
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="ats")

    then_import: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    process_pending_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10_000
    )
    then_rank: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rank_profile_slug: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    rank_only_unscored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    rank_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    then_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    digest_type: Mapped[str] = mapped_column(String(32), nullable=False, default="daily")
    digest_fresh_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=48)
    digest_fresh_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    digest_gem_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    digest_per_company_cap: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    digest_profile_slug: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    digest_min_ranking_score: Mapped[str] = mapped_column(
        String(16), nullable=False, default="35"
    )
    digest_gem_min_score: Mapped[str] = mapped_column(
        String(16), nullable=False, default="60"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_ingestion_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    last_digest_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    last_duration_sec: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
