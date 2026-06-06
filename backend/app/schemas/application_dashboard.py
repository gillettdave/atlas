"""Response models for CRM-style dashboard (`/applications/dashboard`)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

PipelineLane = Literal["active", "post_apply", "closed", "needs_attention"]


class DashboardTrackRow(BaseModel):
    """One application track + excerpt + overlay score (Jobr-era dashboard analogue)."""

    id: uuid.UUID
    canonical_job_id: uuid.UUID
    current_stage: str
    application_outcome: Optional[str] = Field(
        default=None,
        description="Structured CRM outcome when set (W6).",
    )
    notes: Optional[str] = None
    stage_changed_at: Optional[datetime] = Field(
        default=None, description="Last time current_stage changed (UTC)."
    )
    job_title: Optional[str] = None
    job_company_name: Optional[str] = None
    job_apply_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    pipeline_lane: PipelineLane = Field(
        description="Swim-lane bucket: ``application_outcome`` dominates when set; else derived from ``current_stage``.",
    )

    effective_ranking_score: Decimal = Field(description="Uses profile overlay when configured.")
    effective_bucket: Optional[str] = Field(
        default=None,
        description="Latest ranker bucket for the chosen profile when available.",
    )
    rationale: Optional[str] = Field(
        default=None, description="Latest score rationale for that profile snapshot."
    )


class UntrackedJobRow(BaseModel):
    """High-scoring canonical job with no CRM track yet."""

    job_id: uuid.UUID
    title: str
    company_name: str
    apply_url: str
    ranking_score: Decimal
    last_seen_at: datetime


class ApplicationDashboardResponse(BaseModel):
    total_tracked: int
    profile_slug: Optional[str] = None
    lanes: dict[str, list[DashboardTrackRow]] = Field(
        description="Keys: active | post_apply | closed | needs_attention",
    )
    lane_counts: dict[str, int] = Field(
        description="Counts per lane (same keys as `lanes`).",
    )
    untracked_candidates: list[UntrackedJobRow] = Field(
        default_factory=list,
        description="Active jobs scoring above threshold with no track for this tenant.",
    )
