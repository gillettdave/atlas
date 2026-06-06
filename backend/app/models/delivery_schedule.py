"""delivery_schedules - Sprint H scheduler rows.

A schedule tells the loop three things:
  1. WHEN to fire (cadence + cadence-specific fields)
  2. WHAT to build (digest_config dict passed to digest_builder.DigestConfig)
  3. WHERE to ship it (channel + recipients/webhook)

Each successful or failed fire updates the status columns so operators
can see at a glance what happened on the last tick.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_col, updated_at_col, uuid_pk


class DeliverySchedule(Base):
    __tablename__ = "delivery_schedules"

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    # One of: "daily" | "hourly" | "every_n_minutes" | "cron"
    cadence: Mapped[str] = mapped_column(String(32), nullable=False)
    hour_utc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minute_utc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    interval_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # 5-field cron (minute hour dom month dow), interpreted in UTC, when cadence=cron
    cron_expression: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Ranker profile used when building the digest (None = default).
    profile_slug: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # Passed straight into DigestConfig; unknown keys ignored.
    digest_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    # One of: "slack" | "email" | "csv_only" | "none"
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    webhook_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recipients: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    include_hidden_gems: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
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
    last_digest_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("digests.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
