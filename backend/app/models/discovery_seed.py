"""discovery_seeds — crawl seeds for outbound job discovery."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class DiscoverySeed(Base):
    __tablename__ = "discovery_seeds"

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stop_requested: Mapped[str | None] = mapped_column(String(16), nullable=True)

    cadence_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=15)

    max_listing_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unknown_age_policy: Mapped[str | None] = mapped_column(String(32), nullable=True)

    include_domains: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    exclude_domains: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    discovery_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced")
    override_out_of_profile: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    events = relationship(
        "DiscoveryEvent",
        back_populates="seed",
        cascade="all, delete-orphan",
    )
