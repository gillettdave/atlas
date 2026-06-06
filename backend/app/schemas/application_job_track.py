"""Pydantic models for `/applications/job-tracks` (Phase E1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ApplicationOutcomeLiteral = Literal[
    "rejected", "interviewing", "offered", "hired", "withdrawn"
]


class ApplicationJobTrackCreate(BaseModel):
    canonical_job_id: uuid.UUID = Field(description="Atlas canonical `jobs.id` UUID.")
    current_stage: str = Field(default="interested", max_length=64)
    notes: Optional[str] = None
    application_outcome: Optional[ApplicationOutcomeLiteral] = Field(
        default=None,
        description="Structured CRM outcome (W6). Omit for NULL.",
    )


class ApplicationJobTrackUpdate(BaseModel):
    current_stage: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = None
    application_outcome: Optional[ApplicationOutcomeLiteral | Literal[""]] = Field(
        default=None,
        description="Omit unchanged; empty string clears; else enum value.",
    )


class ApplicationJobTrackOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    canonical_job_id: uuid.UUID
    current_stage: str
    application_outcome: Optional[str] = None
    notes: Optional[str]
    stage_changed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    job_title: Optional[str] = None
    job_company_name: Optional[str] = None
    job_apply_url: Optional[str] = None

    model_config = {"from_attributes": True}


class ApplicationJobTrackListResponse(BaseModel):
    total: int
    items: list[ApplicationJobTrackOut]


class ApplicationJobTrackRescoreRequest(BaseModel):
    profile_slug: Optional[str] = Field(
        default=None,
        description="Ranker profile; default profile if omitted.",
    )


class ApplicationJobTrackRescoreResponse(BaseModel):
    bucket: str
    ranking_score: str
    quality_score: str
    rationale: str
    hidden_gem: bool
