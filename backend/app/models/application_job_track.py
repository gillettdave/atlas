"""application_job_tracks — user-scoped workflow row on canonical `jobs` (Phase E1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class ApplicationJobTrack(Base):
    """Links a tenant to a canonical Job with CRM-style stage and notes."""

    __tablename__ = "application_job_tracks"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "canonical_job_id",
            name="uq_application_job_tracks_user_job",
        ),
        CheckConstraint(
            "application_outcome IS NULL OR application_outcome IN ("
            "'rejected', 'interviewing', 'offered', 'hired', 'withdrawn')",
            name="ck_application_job_tracks_outcome",
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # interested | shortlisted | drafting | applied | interviewing | … (free-ish string column)
    current_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="interested")

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Optional terminal / reporting outcome (W6). Independent of free-text ``current_stage``.
    application_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    #: Last time ``current_stage`` changed (UTC).
    stage_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    job = relationship("Job", back_populates="application_tracks")