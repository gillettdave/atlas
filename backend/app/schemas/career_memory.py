"""Pydantic shapes for `/career-memory` (ported from Jobr; Atlas Job UUID linkage)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SourceDocumentResponse(BaseModel):
    """List/summary row; ``preview`` is a prefix of stored ``raw_text``."""

    id: int
    name: str
    content_type: Optional[str]
    ingested_at: Optional[str] = None
    preview: Optional[str] = None


class SourceDocumentDetailResponse(BaseModel):
    """Full document row including stored extracted text."""

    id: int
    name: str
    content_type: Optional[str]
    ingested_at: Optional[str] = None
    raw_text: str
    truncated: bool = False


class SourceDocumentTextIngestRequest(BaseModel):
    name: str
    text: str
    llm_facts: Optional[bool] = Field(
        default=None,
        description="True = LLM facts, False = heuristic only, null = use server default env.",
    )


class CareerFactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_document_id: Optional[int] = None
    fact_text: str
    fact_type: str
    verification_state: str
    confidence_score: float
    source_trace: Optional[str]
    is_core_proof_point: int
    text_edited_at: Optional[datetime] = None


class CareerFactUpdateRequest(BaseModel):
    fact_text: Optional[str] = None
    verification_state: Optional[str] = None
    is_core_proof_point: Optional[int] = None


class TimelineEntryResponse(BaseModel):
    id: int
    source_document_id: Optional[int]
    title: str
    company: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    summary: Optional[str] = None
    status: str
    confidence_score: float
    conflict_group: Optional[str] = None
    source_trace: Optional[str] = None
    created_at: Optional[str] = None


class TimelineEntryUpdateRequest(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None


class ProfileQuestionResponse(BaseModel):
    """Question row; linkage to Atlas pipeline job uses UUID."""

    id: int
    canonical_job_id: Optional[uuid.UUID] = None
    job_title: Optional[str] = None
    job_company: Optional[str] = None
    question_text: str
    question_type: str
    status: str
    priority: str


class ProfileAnswerCreateRequest(BaseModel):
    answer_text: str


class ProfileQuestionStatusUpdateRequest(BaseModel):
    status: str


class DiscoveryProfileResponse(BaseModel):
    profile_name: str
    role_keywords: list[str]
    adjacency_keywords: list[str]
    seniority_keywords: list[str]
    avoid_keywords: list[str]
    confidence_score: float
    generated_from_facts: int
    updated_at: Optional[str] = None


class CareerMemoryExportResponse(BaseModel):
    markdown: str
