"""Application packages API schemas (Phase D)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApplicationPackageGenerateRequest(BaseModel):
    tone: str = Field(default="balanced", description="balanced | concise | executive | technical")
    emphasis: list[str] = Field(default_factory=list, description="Optional themes for copy.")
    generation_source: str | None = Field(
        default=None,
        description="Optional provenance marker (e.g. operator label).",
    )


class ApplicationPackageSaveRequest(BaseModel):
    resume_markdown: str
    cover_letter_markdown: str
    strategy_notes: str
    evidence_used_summary: str | None = None


class ApplicationPackageOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    user_id: uuid.UUID
    version: int
    strategy_notes: str
    resume_markdown: str
    cover_letter_markdown: str
    generation_tone: str | None
    generation_emphasis: str | None
    generation_source: str | None
    evidence_used_summary: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplicationPackageListResponse(BaseModel):
    total: int
    items: list[ApplicationPackageOut]
