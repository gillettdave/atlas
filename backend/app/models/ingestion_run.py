"""ingestion_runs — one row per collector/import invocation."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = uuid_pk()

    # Human-readable source identifier, e.g. "jobs_collector_v4"
    source_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Coarse type: "ats", "native_jobs_page", "aggregator", "x_signal", etc.
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # running | success | partial | failed
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False, index=True)

    rows_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    run_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    raw_events = relationship(
        "RawJobEvent",
        back_populates="ingestion_run",
        cascade="all",
        passive_deletes=True,
    )
