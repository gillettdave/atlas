"""digest_items — ordered entries within a digest."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, uuid_pk


class DigestItem(Base):
    __tablename__ = "digest_items"
    __table_args__ = (
        UniqueConstraint("digest_id", "job_id", name="uq_digest_job"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    digest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("digests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # fresh | hidden_gem | resurfaced | custom
    lane: Mapped[str] = mapped_column(String(32), default="fresh", nullable=False)

    digest = relationship("Digest", back_populates="items")
    job = relationship("Job")
