"""user_job_scores — current best score per (user, job) pair.

Unlike job_scores (append-only audit log), this table stores exactly one
row per (user_id, job_id) — updated in-place on each rescore. The digest
builder reads from here; job_scores is kept as the audit trail.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow, uuid_pk


class UserJobScore(Base):
    __tablename__ = "user_job_scores"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_user_job_scores_user_job"),
        Index("ix_user_job_scores_user_score", "user_id", "score"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    score: Mapped[float] = mapped_column(Float, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    profile_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hidden_gem: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="skip")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
