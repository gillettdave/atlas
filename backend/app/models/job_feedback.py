"""job_feedback - Sprint I append-only event log.

One row = one user reaction to a job under a specific profile. The
ranker and digest builder read aggregate views of this log; they never
mutate it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_col, uuid_pk


# Canonical action vocabulary. Anything not in here is rejected at the
# schema layer so the DB stays clean.
FEEDBACK_ACTIONS: tuple[str, ...] = (
    "saved",
    "dismissed",
    "applied",
    "interviewed",
    "rejected",
    "clicked",
)

# Which actions count as "resolved" (the user is done with this job).
# Used by the digest builder to hide these from future digests.
RESOLUTION_ACTIONS: frozenset[str] = frozenset(
    {"dismissed", "applied", "interviewed", "rejected"}
)

FEEDBACK_SOURCES: tuple[str, ...] = ("ui", "email_click", "slack_reaction", "api")


class JobFeedback(Base):
    __tablename__ = "job_feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ui"
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
