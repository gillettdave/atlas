"""raw_job_events — every raw record pulled by a collector.

This is the durable source of truth before cleaning / canonicalization.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class RawJobEvent(Base):
    __tablename__ = "raw_job_events"

    id: Mapped[uuid.UUID] = uuid_pk()

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # fetched | failed_fetch
    fetch_status: Mapped[str] = mapped_column(
        String(32), default="fetched", nullable=False, index=True
    )
    # pending | parsed | failed_parse | normalized | deduped | stored |
    # scored | digest_eligible | needs_review | rejected
    parse_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    ingestion_run = relationship("IngestionRun", back_populates="raw_events")
