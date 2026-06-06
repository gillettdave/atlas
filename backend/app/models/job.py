"""jobs — canonical, user-visible job listings.

Exactly one row per real-world opening. Duplicate source discoveries live
in job_source_sightings instead of creating additional visible jobs.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_job_id",
            name="uq_jobs_provider_external_id",
        ),
        Index("ix_jobs_active_seen", "is_active", "last_seen_at"),
        Index("ix_jobs_ranking_score", "ranking_score"),
        Index("ix_jobs_normalized_company_title", "normalized_company_name", "normalized_title"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_job_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_company_name: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)

    location: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    remote_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    apply_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # Pre-canonicalized apply_url for Tier-1 matching. Unique to prevent
    # duplicate visible jobs with the same canonical apply link.
    canonical_apply_url: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, index=True
    )

    description_clean: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    salary_text: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    quality_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), default=Decimal("0"), nullable=False
    )
    ranking_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), default=Decimal("0"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    sightings = relationship(
        "JobSourceSighting",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    scores = relationship(
        "JobScore",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    application_packages = relationship(
        "ApplicationPackage",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    application_tracks = relationship(
        "ApplicationJobTrack",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
