"""pipeline_events — operational log trail for any entity.

Intentionally generic: no FK to a specific entity. `entity_type` + `entity_id`
let us log against ingestion_runs, raw_job_events, jobs, digests, etc.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow, uuid_pk


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    __table_args__ = (
        Index("ix_pipeline_events_entity", "entity_type", "entity_id"),
        Index("ix_pipeline_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    event_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
