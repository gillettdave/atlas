"""job_scores — scoring history for a canonical job."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class JobScore(Base):
    __tablename__ = "job_scores"

    id: Mapped[uuid.UUID] = uuid_pk()

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Sprint G: nullable profile id. NULL == legacy global default.
    profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    # top | strong | maybe | skip
    bucket: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hidden_gem: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    freshness_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    fit_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3), nullable=True)

    # LLM qualification scoring — populated lazily at digest-time
    qualification_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qualification_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    qualification_scored_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    description_hash_at_scoring: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    job = relationship("Job", back_populates="scores")
