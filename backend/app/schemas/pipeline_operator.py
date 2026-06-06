"""Operators — pipeline / raw-event inspection (read-only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class PipelineOperatorSummaryResponse(BaseModel):
    """Counts grouped by raw_job_event statuses (global, not tenant-filtered)."""

    parse_status_counts: dict[str, int]
    fetch_status_counts: dict[str, int]


class OperatorRawEventListItem(BaseModel):
    """One row for recent raw events table."""

    id: str
    ingestion_run_id: str
    source_name: Optional[str] = None
    provider: str
    source_url: str
    fetch_status: str
    parse_status: str
    created_at: datetime
    title_hint: Optional[str] = None


class OperatorRawEventListResponse(BaseModel):
    total: int = Field(ge=0)
    limit: int
    items: list[OperatorRawEventListItem]


class OperatorPipelineEventBrief(BaseModel):
    id: str
    entity_type: str
    entity_id: Optional[str] = None
    event_name: str
    details: Optional[dict[str, Any]] = None
    created_at: datetime


class OperatorRawEventDetailResponse(BaseModel):
    id: str
    ingestion_run_id: str
    source_name: Optional[str] = None
    provider: str
    source_url: str
    fetch_status: str
    parse_status: str
    created_at: datetime
    raw_payload: dict[str, Any]
    raw_html_excerpt: Optional[str] = None
    raw_html_total_chars: Optional[int] = None
    raw_html_was_truncated: bool = False
    pipeline_events: list[OperatorPipelineEventBrief] = Field(default_factory=list)

