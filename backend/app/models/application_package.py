"""application_packages — tailored résumé / CL / notes per canonical job (Phase D)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class ApplicationPackage(Base):
    __tablename__ = "application_packages"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "job_id",
            "version",
            name="uq_application_packages_user_job_version",
        ),
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

    version: Mapped[int] = mapped_column(Integer, nullable=False)

    strategy_notes: Mapped[str] = mapped_column(Text, nullable=False)
    resume_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    cover_letter_markdown: Mapped[str] = mapped_column(Text, nullable=False)

    generation_tone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    generation_emphasis: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    evidence_used_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    job = relationship("Job", back_populates="application_packages")
