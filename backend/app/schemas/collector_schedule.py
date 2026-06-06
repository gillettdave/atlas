"""Pydantic models for collector_schedules (Sprint M.1)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Self

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CADENCES: tuple[str, ...] = ("daily", "hourly", "every_n_minutes", "cron")


def validate_collector_cadence_fields(
    *,
    cadence: str,
    hour_utc: Optional[int],
    minute_utc: Optional[int],
    interval_minutes: Optional[int],
    cron_expression: Optional[str],
) -> None:
    """Shared rules for create + full-row PATCH validation."""
    c = cadence.lower()
    if c in ("daily", "hourly") and minute_utc is None:
        minute_utc = 0
    if c == "daily":
        if hour_utc is None:
            raise ValueError("cadence=daily requires hour_utc (0-23)")
    elif c == "hourly":
        pass
    elif c == "every_n_minutes":
        if not interval_minutes:
            raise ValueError("cadence=every_n_minutes requires interval_minutes")
    elif c == "cron":
        expr = (cron_expression or "").strip()
        if not expr:
            raise ValueError("cadence=cron requires cron_expression")
        if not croniter.is_valid(expr):
            raise ValueError(f"invalid cron_expression: {expr!r}")


class CollectorScheduleCreate(BaseModel):
    name: str = Field(max_length=128)
    cadence: str = Field(description="daily | hourly | every_n_minutes | cron")
    hour_utc: Optional[int] = Field(default=None, ge=0, le=23)
    minute_utc: Optional[int] = Field(default=None, ge=0, le=59)
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=10_080)
    cron_expression: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Required when cadence=cron; standard 5-field cron, UTC.",
    )

    use_ingestion_sources: bool = Field(
        default=False,
        description=(
            "When true, collectors load ingestion_sources rows; optional "
            "ingestion_sources_user_id picks tenant (omit → seeded). CSV ignored."
        ),
    )
    input_csv_path: str = Field(
        default="",
        max_length=2048,
        description=(
            "Path relative to repo root or absolute. Required unless "
            "use_ingestion_sources (may be omitted; stored as __ingestion_sources__)."
        ),
    )
    source_limit: Optional[int] = Field(default=None, ge=1, le=50_000)
    batch_size: int = Field(default=50, ge=1, le=2000)
    headless: bool = True
    source_name: str = Field(default="web3_ats_collector", max_length=128)
    source_type: str = Field(default="ats", max_length=64)
    then_import: bool = True
    process_pending_limit: int = Field(default=10_000, ge=1, le=100_000)
    then_rank: bool = True
    rank_profile_slug: Optional[str] = Field(default=None, max_length=64)
    rank_only_unscored: bool = False
    rank_limit: Optional[int] = Field(default=None, ge=1, le=100_000)
    then_digest: bool = False
    digest_type: str = Field(default="daily", max_length=32)
    digest_fresh_hours: int = Field(default=48, ge=1, le=336)
    digest_fresh_limit: int = Field(default=15, ge=0, le=200)
    digest_gem_limit: int = Field(default=10, ge=0, le=200)
    digest_per_company_cap: int = Field(default=3, ge=1, le=20)
    digest_profile_slug: Optional[str] = Field(default=None, max_length=64)
    digest_min_ranking_score: str = Field(default="35", max_length=16)
    digest_gem_min_score: str = Field(default="60", max_length=16)
    is_active: bool = True
    ingestion_sources_user_id: Optional[uuid.UUID] = Field(
        default=None,
        description="With use_ingestion_sources: which user's rows (null → seeded).",
    )

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("name is required")
        return s

    @field_validator("cadence")
    @classmethod
    def _cadence(cls, v: str) -> str:
        low = v.strip().lower()
        if low not in CADENCES:
            raise ValueError(f"cadence must be one of {CADENCES}")
        return low

    @field_validator("cron_expression")
    @classmethod
    def _cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @model_validator(mode="after")
    def _cadence_fields(self) -> "CollectorScheduleCreate":
        if self.cadence == "daily":
            if self.minute_utc is None:
                self.minute_utc = 0
        elif self.cadence == "hourly":
            if self.minute_utc is None:
                self.minute_utc = 0
        validate_collector_cadence_fields(
            cadence=self.cadence,
            hour_utc=self.hour_utc,
            minute_utc=self.minute_utc,
            interval_minutes=self.interval_minutes,
            cron_expression=self.cron_expression,
        )
        if self.use_ingestion_sources:
            if not self.input_csv_path.strip():
                object.__setattr__(self, "input_csv_path", "__ingestion_sources__")
        elif not self.input_csv_path.strip():
            raise ValueError(
                "input_csv_path is required unless use_ingestion_sources=true"
            )
        return self


class CollectorScheduleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    cadence: Optional[str] = None
    hour_utc: Optional[int] = None
    minute_utc: Optional[int] = None
    interval_minutes: Optional[int] = None
    cron_expression: Optional[str] = Field(default=None, max_length=512)
    input_csv_path: Optional[str] = None
    source_limit: Optional[int] = None
    batch_size: Optional[int] = None
    headless: Optional[bool] = None
    source_name: Optional[str] = None
    source_type: Optional[str] = None
    then_import: Optional[bool] = None
    process_pending_limit: Optional[int] = None
    then_rank: Optional[bool] = None
    rank_profile_slug: Optional[str] = None
    rank_only_unscored: Optional[bool] = None
    rank_limit: Optional[int] = None
    then_digest: Optional[bool] = None
    digest_type: Optional[str] = None
    digest_fresh_hours: Optional[int] = None
    digest_fresh_limit: Optional[int] = None
    digest_gem_limit: Optional[int] = None
    digest_per_company_cap: Optional[int] = None
    digest_profile_slug: Optional[str] = None
    digest_min_ranking_score: Optional[str] = None
    digest_gem_min_score: Optional[str] = None
    is_active: Optional[bool] = None
    use_ingestion_sources: Optional[bool] = None
    ingestion_sources_user_id: Optional[uuid.UUID] = None

    @field_validator("cadence")
    @classmethod
    def _cadence(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        low = v.strip().lower()
        if low not in CADENCES:
            raise ValueError(f"cadence must be one of {CADENCES}")
        return low

    @field_validator("cron_expression")
    @classmethod
    def _cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s or None


class CollectorScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    cadence: str
    hour_utc: Optional[int] = None
    minute_utc: Optional[int] = None
    interval_minutes: Optional[int] = None
    cron_expression: Optional[str] = None
    use_ingestion_sources: bool = False
    ingestion_sources_user_id: Optional[uuid.UUID] = None
    input_csv_path: str
    source_limit: Optional[int] = None
    batch_size: int
    headless: bool
    source_name: str
    source_type: str
    then_import: bool
    process_pending_limit: int
    then_rank: bool
    rank_profile_slug: Optional[str] = None
    rank_only_unscored: bool
    rank_limit: Optional[int] = None
    then_digest: bool
    digest_type: str
    digest_fresh_hours: int
    digest_fresh_limit: int
    digest_gem_limit: int
    digest_per_company_cap: int
    digest_profile_slug: Optional[str] = None
    digest_min_ranking_score: str
    digest_gem_min_score: str
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_ingestion_run_id: Optional[uuid.UUID] = None
    last_digest_id: Optional[uuid.UUID] = None
    last_duration_sec: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class CollectorScheduleListResponse(BaseModel):
    total: int
    items: list[CollectorScheduleOut]


class CollectorRunResult(BaseModel):
    schedule_id: uuid.UUID
    status: str
    detail: Optional[str] = None
    duration_ms: int
    ingestion_run_id: Optional[uuid.UUID] = None
    digest_id: Optional[uuid.UUID] = None


class CollectorTickResult(BaseModel):
    processed: int
    outcomes: list[CollectorRunResult]


class CollectorPipelineRequest(BaseModel):
    use_ingestion_sources: bool = False
    ingestion_sources_user_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Whose ingestion_sources to use (admin); default: Bearer tenant.",
    )
    input_csv_path: str = Field(default="", max_length=2048)
    source_limit: Optional[int] = None
    headless: bool = True
    batch_size: int = 50
    source_name: str = "web3_ats_adhoc"
    source_type: str = "ats"
    then_import: bool = True
    process_pending_limit: int = 10_000
    then_rank: bool = True
    rank_profile_slug: Optional[str] = None
    rank_only_unscored: bool = False
    rank_limit: Optional[int] = None
    then_digest: bool = False
    digest_type: str = "daily"
    digest_fresh_hours: int = 48
    digest_fresh_limit: int = 15
    digest_gem_limit: int = 10
    digest_per_company_cap: int = 3
    digest_profile_slug: Optional[str] = None
    digest_min_ranking_score: str = "35"
    digest_gem_min_score: str = "60"
    intake_max_listing_age_days: Optional[int] = Field(
        default=None,
        ge=0,
        le=366,
        description=(
            "Import step only. Omit/null: ATLAS_INTAKE_MAX_LISTING_AGE_DAYS. "
            "0: disable gate for this run. 1-366: max listing age in days."
        ),
    )

    @model_validator(mode="after")
    def _ensure_csv_or_db(self) -> Self:
        if self.use_ingestion_sources:
            return self
        if not self.input_csv_path.strip():
            raise ValueError(
                "input_csv_path required when use_ingestion_sources=false"
            )
        return self


class CollectorPipelineResultOut(BaseModel):
    ok: bool
    error: Optional[str] = None
    duration_sec: float = 0.0
    input_csv: str
    sources_attempted: int = 0
    sources_with_records: int = 0
    records_inserted: int = 0
    import_processed: Optional[int] = None
    new_canonical: Optional[int] = None
    rank_scored: Optional[int] = None
    ingestion_run_id: Optional[uuid.UUID] = None
    digest_id: Optional[uuid.UUID] = None
    by_provider: dict[str, int] = Field(default_factory=dict)
