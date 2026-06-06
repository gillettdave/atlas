"""Schemas for job_feedback (Sprint I)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.job_feedback import FEEDBACK_ACTIONS, FEEDBACK_SOURCES


class FeedbackRecordRequest(BaseModel):
    """Request body for POST /jobs/{job_id}/feedback."""

    action: str = Field(
        ..., description=f"one of: {', '.join(FEEDBACK_ACTIONS)}"
    )
    profile_slug: Optional[str] = Field(default=None, max_length=64)
    source: str = Field(default="ui", max_length=32)
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("action")
    @classmethod
    def _action(cls, v: str) -> str:
        low = (v or "").strip().lower()
        if low not in FEEDBACK_ACTIONS:
            raise ValueError(
                f"action must be one of {FEEDBACK_ACTIONS}"
            )
        return low

    @field_validator("source")
    @classmethod
    def _source(cls, v: str) -> str:
        low = (v or "ui").strip().lower()
        if low not in FEEDBACK_SOURCES:
            raise ValueError(
                f"source must be one of {FEEDBACK_SOURCES}"
            )
        return low

    @field_validator("profile_slug")
    @classmethod
    def _slug(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s or None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    profile_id: Optional[uuid.UUID] = None
    profile_slug: Optional[str] = None
    action: str
    source: str
    note: Optional[str] = None
    created_at: datetime


class FeedbackListResponse(BaseModel):
    total: int
    items: list[FeedbackOut]


class FeedbackJobSummary(BaseModel):
    """Compact view used inline on job detail pages.

    `latest_action` is the most recent action for this (job, profile_id).
    `counts` is action -> occurrences (across all profiles if profile_id
    is None in the lookup).
    """

    job_id: uuid.UUID
    profile_id: Optional[uuid.UUID] = None
    latest_action: Optional[str] = None
    latest_source: Optional[str] = None
    latest_at: Optional[datetime] = None
    counts: dict[str, int] = Field(default_factory=dict)
    is_resolved: bool = False
