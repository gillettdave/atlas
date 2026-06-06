"""Operator-configured ingestion source rows (replaces CSV-only workflows over time).

Phase C stub — list/create; collectors may reference these IDs later.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_col, updated_at_col, uuid_pk


class IngestionSource(Base):
    __tablename__ = "ingestion_sources"

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    label: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    jobs_page_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    careers_site_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ats_board_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ats_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resolution_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
