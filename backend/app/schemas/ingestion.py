"""Schemas for ingestion runs and raw job events."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class IngestionRunCreate(BaseModel):
    source_name: str = Field(..., max_length=128)
    source_type: str = Field(..., max_length=64)
    metadata: Optional[dict[str, Any]] = None


class IngestionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_name: str
    source_type: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    rows_seen: int
    rows_inserted: int
    rows_failed: int


class RawJobEventCreate(BaseModel):
    """A single raw record emitted by a collector.

    Collectors should dump *whatever they got* into raw_payload.
    Cleaner_v2 decides what's canonical.
    """
    provider: str = Field(..., max_length=64)
    source_url: str
    raw_payload: dict[str, Any]
    raw_html: Optional[str] = None
    fetch_status: str = "fetched"


class RawJobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ingestion_run_id: uuid.UUID
    provider: str
    source_url: str
    fetch_status: str
    parse_status: str
    created_at: datetime


class BulkRawJobEventCreate(BaseModel):
    """Submit many raw events under one ingestion_run."""
    ingestion_run_id: Optional[uuid.UUID] = None
    # If ingestion_run_id is not provided, one will be created from these:
    source_name: Optional[str] = None
    source_type: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    events: list[RawJobEventCreate]

    # If True, mark the ingestion_run completed after this batch.
    finalize: bool = False


class BulkIngestResult(BaseModel):
    ingestion_run_id: uuid.UUID
    inserted: int
    failed: int
    event_ids: list[uuid.UUID]


class ProcessPendingRequest(BaseModel):
    """Drive the importer/cleaner over queued raw events."""
    limit: int = Field(default=500, ge=1, le=10_000)
    ingestion_run_id: Optional[uuid.UUID] = None
    intake_max_listing_age_days: Optional[int] = Field(
        default=None,
        ge=0,
        le=366,
        description=(
            "Optional override for this request only. Omit or null: use "
            "ATLAS_INTAKE_MAX_LISTING_AGE_DAYS. 0: disable listing-age gate. "
            "1-366: max age in days when a listing date is parsed from raw_payload."
        ),
    )


class ProcessPendingResult(BaseModel):
    processed: int
    new_canonical: int
    matched_existing: int
    possible_duplicate_review: int
    rejected_low_quality: int
    failed: int


class RescoreRequest(BaseModel):
    """Trigger Ranker across canonical jobs."""
    provider: Optional[str] = Field(
        default=None,
        description="If set, only rescore jobs from this provider (e.g. 'greenhouse').",
    )
    only_active: bool = True
    only_unscored: bool = Field(
        default=False,
        description="If true, only score jobs with ranking_score=0 and quality_score=0.",
    )
    limit: Optional[int] = Field(default=None, ge=1, le=50_000)
    profile_slug: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "If set, score against this profile and write per-profile "
            "job_scores rows. Omit to score the default profile."
        ),
    )


class RescoreResult(BaseModel):
    scored: int
    failed: int
    hidden_gems: int
    by_bucket: dict[str, int]
    profile_slug: Optional[str] = None


class BackfillRequest(BaseModel):
    """Backfill normalization on existing Jobs using their latest raw event."""
    only_missing_remote_type: bool = Field(
        default=True,
        description="If true, only touch jobs with remote_type IS NULL.",
    )
    only_active: bool = True
    force: bool = Field(
        default=False,
        description="If true, overwrite existing non-null normalized fields too.",
    )
    then_rescore: bool = Field(
        default=True,
        description="If true, rescore any job touched by the backfill.",
    )
    limit: Optional[int] = Field(default=None, ge=1, le=50_000)


class BackfillResult(BaseModel):
    scanned: int
    updated: int
    unchanged: int
    no_raw_event: int
    failed: int
    rescored: int
    fields_filled: dict[str, int]


# --- Phase C: manual URL + ingestion_sources registry -------------------


class ManualJobUrlRequest(BaseModel):
    """Fetch a job posting URL and emit a raw_job_event (cleaner + importer)."""

    url: str = Field(..., min_length=8, max_length=4000)
    title_override: Optional[str] = Field(default=None, max_length=512)
    company_override: Optional[str] = Field(default=None, max_length=256)
    ingestion_source_id: Optional[uuid.UUID] = None
    then_process: bool = Field(default=True, description="Run cleaner/importer on this run.")
    then_rescore: bool = Field(
        default=True,
        description="If a job row was written, rescore just that listing.",
    )
    profile_slug: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Ranker profile slug (default profile if omitted).",
    )


class ManualJobUrlResponse(BaseModel):
    ingestion_run_id: uuid.UUID
    raw_event_id: uuid.UUID
    fetch_status: str
    parse_status: Optional[str] = None
    job_id: Optional[uuid.UUID] = None


class IngestionSourceCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = None
    jobs_page_url: Optional[str] = Field(default=None, max_length=4000)
    careers_site_url: Optional[str] = Field(default=None, max_length=4000)
    ats_board_url: Optional[str] = Field(default=None, max_length=4000)
    ats_type: Optional[str] = Field(default=None, max_length=64)
    resolution_type: Optional[str] = Field(default=None, max_length=64)


class IngestionSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    label: str
    notes: Optional[str]
    jobs_page_url: Optional[str]
    careers_site_url: Optional[str]
    ats_board_url: Optional[str]
    ats_type: Optional[str]
    resolution_type: Optional[str]
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class IngestionSourceListResponse(BaseModel):
    total: int = Field(description="Matching rows for this tenant (respects optional search `q`).")
    limit: int | None = Field(
        default=None,
        description="Page size requested; None means unrestricted (all matches from offset).",
    )
    offset: int = Field(default=0, description="Offset applied by the API for this payload.")
    items: list[IngestionSourceOut]


class IngestionSourcesSyncFromCsvRequest(BaseModel):
    """Bulk upsert ``ingestion_sources`` from resolver CSV."""

    csv_path: str = Field(..., min_length=1, max_length=2048)
    csv_format: Literal["auto", "jobs_targets", "ats_targets"] = Field(
        default="auto",
        description=(
            "auto: detect from headers. Else force parser — **ats_targets** is the "
            "narrow export (company_name, ats_type, ats_slug, ats_board_url, …)."
        ),
    )
    limit: Optional[int] = Field(default=None, ge=1, le=500_000)
    dry_run: bool = False


class IngestionSourcesSyncFromCsvResult(BaseModel):
    total_rows_read: int
    created: int
    updated: int
    skipped_empty_label: int
    dry_run: bool
    csv_format_used: str
