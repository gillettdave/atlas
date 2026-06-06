"""Schemas for digests and digest items."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .job import JobOut


class DigestItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    digest_id: uuid.UUID
    job_id: uuid.UUID
    rank_position: int
    reason: Optional[str] = None
    lane: str


class DigestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generated_at: datetime
    digest_type: str
    notes: Optional[str] = None


class DigestPreviewItem(BaseModel):
    job: JobOut
    lane: str
    reason: Optional[str] = None
    rank_position: int


class DigestPreviewResponse(BaseModel):
    generated_at: datetime
    fresh: list[DigestPreviewItem]
    hidden_gems: list[DigestPreviewItem]


# ---------------------------------------------------------------------------
# Persisted digest generation (Sprint C)
# ---------------------------------------------------------------------------

class DigestGenerateRequest(BaseModel):
    """Knobs for POST /digests/generate. All fields optional."""

    digest_type: str = Field(
        default="daily",
        description="daily | weekly | hidden_gems | custom",
        max_length=32,
    )
    fresh_hours: int = Field(default=48, ge=1, le=24 * 14)
    fresh_limit: int = Field(default=15, ge=0, le=200)
    gem_limit: int = Field(default=10, ge=0, le=200)
    per_company_cap: int = Field(default=3, ge=1, le=20)
    min_ranking_score: Decimal = Field(default=Decimal("35"), ge=0, le=100)
    gem_min_score: Decimal = Field(default=Decimal("60"), ge=0, le=100)
    notes: Optional[str] = Field(default=None, max_length=4096)
    profile_slug: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "Feedback scope for the digest. When set, jobs the user has "
            "already resolved (dismissed/applied/rejected/interviewed) "
            "under this profile are excluded. Omit to use the default "
            "profile."
        ),
    )
    apply_qualification: bool = Field(
        default=True,
        description=(
            "When True (default), exclude candidates that fail saved "
            "`/qualification` rules, using the same profile score overlay as evaluate."
        ),
    )
    use_llm_qualification: bool = Field(
        default=True,
        description=(
            "When True (default), score each candidate with LLM qualification "
            "scoring against the user's approved career facts. Jobs scoring < 3/10 "
            "are excluded. Results are cached per (job, profile) for 7 days."
        ),
    )


class DigestDetailItem(BaseModel):
    """A DigestItem joined to its Job for the detail response."""

    job: JobOut
    lane: str
    reason: Optional[str] = None
    rank_position: int


class DigestStatsOut(BaseModel):
    fresh_selected: int
    gem_selected: int
    fresh_candidates: int
    gem_candidates: int
    dropped_by_cap: int
    excluded_by_feedback: int = 0
    excluded_by_qualification: int = 0


class DigestDetail(BaseModel):
    id: uuid.UUID
    generated_at: datetime
    digest_type: str
    notes: Optional[str] = None
    fresh: list[DigestDetailItem]
    hidden_gems: list[DigestDetailItem]
    stats: Optional[DigestStatsOut] = None


class DigestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generated_at: datetime
    digest_type: str
    notes: Optional[str] = None
    item_count: int


class DigestListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DigestSummary]


# ---------------------------------------------------------------------------
# Delivery (Sprint F)
# ---------------------------------------------------------------------------

class DigestSendRequest(BaseModel):
    channel: str = Field(description="slack | email")
    webhook_url: Optional[str] = Field(
        default=None,
        description="Override ATLAS_SLACK_WEBHOOK_URL for this send (slack only).",
    )
    recipients: list[str] = Field(
        default_factory=list,
        description="Email recipients (required for channel=email).",
    )
    include_hidden_gems: bool = True


class DigestSendResponse(BaseModel):
    digest_id: uuid.UUID
    channel: str
    recipient: str
    ok: bool
    sent_at: datetime
    item_count: int
    detail: Optional[str] = None
