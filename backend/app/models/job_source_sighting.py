"""job_source_sightings — every place a canonical job was found.

Keeps duplicate discoveries addressable for future sponsored routing
(e.g. prefer a partner / premium apply link over a generic one).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class JobSourceSighting(Base):
    __tablename__ = "job_source_sightings"
    __table_args__ = (
        Index("ix_sightings_job_primary", "job_id", "is_primary"),
        Index("ix_sightings_domain_kind", "source_domain", "source_kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_domain: Mapped[str] = mapped_column(String(256), nullable=False)
    # e.g. ats_greenhouse | ats_lever | ats_ashby | aggregator_jobstash |
    #      company_careers | native_jobs_page | partner_board
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    apply_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sponsor_priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    job = relationship("Job", back_populates="sightings")
