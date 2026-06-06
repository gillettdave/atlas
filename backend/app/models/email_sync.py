"""email_sync_sources / events — Gmail IMAP intake (Jobr port)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class EmailSyncSource(Base):
    __tablename__ = "email_sync_sources"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "label_name",
            name="uq_email_sync_sources_user_provider_label",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False,
    )

    events = relationship(
        "EmailSyncEvent",
        back_populates="source",
        cascade="all, delete-orphan",
    )


class EmailSyncEvent(Base):
    __tablename__ = "email_sync_events"

    id: Mapped[uuid.UUID] = uuid_pk()

    email_sync_source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("email_sync_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider_message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    canonical_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )

    source = relationship("EmailSyncSource", back_populates="events")
