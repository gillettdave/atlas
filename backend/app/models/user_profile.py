"""user_profiles — personalized ranker configurations (Sprint G).

A profile stores per-component weight multipliers and extra vocabulary
that flex the Ranker v2 scorer. Per owning user, exactly one profile
carries ``is_default = true`` and is used when no profile is specified.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_col, updated_at_col, uuid_pk


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Weight multipliers keyed by ranker component name. Unknown keys
    # are ignored; missing keys default to 1.0. See services/ranker.py
    # for the canonical list.
    weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    # Extra vocabulary layered over the global Web3 lists.
    strong_keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    weak_keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # Words/phrases that penalise a job when found in title/company/desc.
    negative_keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    # Ranker v2: sparse TF–IDF reference + suggested terms (see ranker_text.py).
    ranker_text_signals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    preferred_remote: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    min_score_threshold: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
