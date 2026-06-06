"""Pydantic models for `/qualification/*` (Qualification MVP)."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class QualificationRules(BaseModel):
    """Deterministic gates on canonical ``jobs`` rows.

    All fields are optional; **empty / omitted** means that axis does not filter.
    """

    model_config = ConfigDict(extra="ignore")

    min_ranking_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Fail if effective ranking score is strictly below this.",
    )
    remote_types_allowed: Optional[list[str]] = Field(
        default=None,
        description="If non-empty, job.remote_type must match one (case-insensitive).",
    )
    title_or_description_must_contain_any: Optional[list[str]] = Field(
        default=None,
        description="If non-empty, at least one phrase must appear in title or description (case-insensitive).",
    )
    block_if_text_contains_any: Optional[list[str]] = Field(
        default=None,
        description="If any phrase appears in title, company, or description, fail.",
    )
    company_name_block_substrings: Optional[list[str]] = Field(
        default=None,
        description="If any substring appears in company_name, fail (case-insensitive).",
    )


class QualificationSettingsOut(BaseModel):
    rules: QualificationRules


class QualificationEvaluateRequest(BaseModel):
    job_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    profile_slug: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Use per-profile job_scores score when not the default profile.",
    )
    rules_override: Optional[QualificationRules] = Field(
        default=None,
        description="If set, do not read saved settings from the DB for this call.",
    )


class QualificationEvalItem(BaseModel):
    job_id: uuid.UUID
    passed: bool
    reasons_failed: list[str] = Field(default_factory=list)


class QualificationEvaluateResponse(BaseModel):
    evaluated: int
    items: list[QualificationEvalItem]
