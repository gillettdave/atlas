"""digests — a generated digest batch (daily, weekly, ad-hoc)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow, uuid_pk


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[uuid.UUID] = uuid_pk()

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    # daily | weekly | hidden_gems | custom
    digest_type: Mapped[str] = mapped_column(
        String(32), default="daily", nullable=False, index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    items = relationship(
        "DigestItem",
        back_populates="digest",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DigestItem.rank_position",
    )
