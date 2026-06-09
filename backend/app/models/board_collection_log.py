"""BoardCollectionLog — tracks last collection time per ATS board URL."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BoardCollectionLog(Base):
    __tablename__ = "board_collection_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ats_board_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ats_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Freshness tracking
    last_collected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Stall tracking
    consecutive_timeouts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_timeout_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Lifetime stats
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_board_collection_log_ats_board_url", "ats_board_url"),
        Index("ix_board_collection_log_last_collected_at", "last_collected_at"),
        Index("ix_board_collection_log_ats_type", "ats_type"),
    )

    def is_fresh(self, freshness_days: int = 3) -> bool:
        """Return True if this board was collected within the freshness window."""
        if self.last_collected_at is None:
            return False
        now = datetime.now(timezone.utc)
        lc = self.last_collected_at
        if lc.tzinfo is None:
            lc = lc.replace(tzinfo=timezone.utc)
        return (now - lc).total_seconds() < freshness_days * 86400

    def is_blocklisted(self, max_consecutive_timeouts: int = 5) -> bool:
        """Return True if this board has timed out too many times in a row."""
        return self.consecutive_timeouts >= max_consecutive_timeouts

    def __repr__(self) -> str:
        return (
            f"<BoardCollectionLog url={self.ats_board_url!r} "
            f"last={self.last_collected_at} timeouts={self.consecutive_timeouts}>"
        )
