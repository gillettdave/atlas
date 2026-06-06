"""Schemas for canonical jobs, sightings, scores."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class JobSightingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_domain: str
    source_kind: str
    source_url: str
    provider: Optional[str] = None
    apply_url: Optional[str] = None
    is_primary: bool
    source_priority: int
    sponsor_priority: int
    discovered_at: datetime


class JobScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    score: Decimal
    bucket: str
    rationale: Optional[str] = None
    hidden_gem: bool
    freshness_score: Optional[Decimal] = None
    fit_score: Optional[Decimal] = None
    created_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    external_job_id: Optional[str] = None
    company_name: str
    title: str
    location: Optional[str] = None
    remote_type: Optional[str] = None
    apply_url: str
    salary_text: Optional[str] = None
    employment_type: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool
    quality_score: Decimal
    ranking_score: Decimal
    qualifies: Optional[bool] = Field(
        default=None,
        description="Populated when listing with include_qualification or after apply_qualification.",
    )


class JobDetail(JobOut):
    description_clean: Optional[str] = None
    sightings: list[JobSightingOut] = Field(default_factory=list)
    scores: list[JobScoreOut] = Field(default_factory=list)


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[JobOut]
    qualification_pool_scanned: Optional[int] = Field(
        default=None,
        description="Jobs examined before qualification filter (apply_qualification only).",
    )
    qualification_excluded_count: Optional[int] = Field(
        default=None,
        description="Jobs dropped by qualification within the scanned pool.",
    )


class SetPrimarySourceRequest(BaseModel):
    sighting_id: uuid.UUID


class DuplicateReviewOut(BaseModel):
    """A raw_job_event flagged for human review against a candidate job."""
    raw_event_id: uuid.UUID
    provider: str
    source_url: str
    normalized_company: str
    normalized_title: str
    candidate_job_ids: list[uuid.UUID]
    reason: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Review queue — detail + resolve (Sprint E)
# ---------------------------------------------------------------------------

class ReviewCandidateView(BaseModel):
    """A minimal view of the incoming raw event for the review UI."""

    provider: str
    source_url: str
    company_name: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    remote_type: Optional[str] = None
    apply_url: Optional[str] = None
    employment_type: Optional[str] = None
    salary_text: Optional[str] = None
    description_clean: Optional[str] = None


class ReviewDetail(BaseModel):
    raw_event_id: uuid.UUID
    created_at: datetime
    parse_status: str
    reason: str
    tier: Optional[str] = None
    incoming: ReviewCandidateView
    candidates: list[JobOut] = Field(default_factory=list)


class ReviewResolveRequest(BaseModel):
    action: str = Field(description="merge | promote | reject")
    target_job_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Required when action == merge. Ignored otherwise.",
    )
    note: Optional[str] = Field(default=None, max_length=2048)
    rescore: bool = True


class ReviewResolveResponse(BaseModel):
    raw_event_id: uuid.UUID
    action: str
    job_id: Optional[uuid.UUID] = None
    rescored: bool = False
