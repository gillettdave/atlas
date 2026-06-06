"""Schemas for delivery_schedules (Sprint H)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CADENCES: tuple[str, ...] = ("daily", "hourly", "every_n_minutes", "cron")
CHANNELS: tuple[str, ...] = ("slack", "email", "csv_only", "none")


def validate_schedule_cadence_fields(
    *,
    cadence: str,
    hour_utc: Optional[int],
    minute_utc: Optional[int],
    interval_minutes: Optional[int],
    cron_expression: Optional[str],
    channel: str,
    recipients: list[str],
) -> None:
    """Shared rules for create + post-PATCH row state."""
    if cadence in ("daily", "hourly") and minute_utc is None:
        minute_utc = 0
    if cadence == "daily":
        if hour_utc is None:
            raise ValueError("cadence=daily requires hour_utc (0-23)")
        if minute_utc is None:
            minute_utc = 0
    elif cadence == "hourly":
        if minute_utc is None:
            minute_utc = 0
    elif cadence == "every_n_minutes":
        if not interval_minutes:
            raise ValueError("cadence=every_n_minutes requires interval_minutes")
    elif cadence == "cron":
        expr = (cron_expression or "").strip()
        if not expr:
            raise ValueError("cadence=cron requires cron_expression")
        if not croniter.is_valid(expr):
            raise ValueError(f"invalid cron_expression: {expr!r}")
    if channel == "email" and not recipients:
        raise ValueError("channel=email requires at least one recipient")


class ScheduleBase(BaseModel):
    """Shared fields + cadence validation."""

    name: str = Field(..., max_length=128)
    cadence: str = Field(
        ..., description="daily | hourly | every_n_minutes | cron"
    )
    hour_utc: Optional[int] = Field(default=None, ge=0, le=23)
    minute_utc: Optional[int] = Field(default=None, ge=0, le=59)
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)
    cron_expression: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Required when cadence=cron; standard 5-field cron, UTC.",
    )

    profile_slug: Optional[str] = Field(default=None, max_length=64)
    digest_config: dict[str, Any] = Field(default_factory=dict)

    channel: str = Field(..., description="slack | email | csv_only | none")
    webhook_url: Optional[str] = Field(default=None, max_length=2048)
    recipients: list[str] = Field(default_factory=list)
    include_hidden_gems: bool = True

    is_active: bool = True

    @field_validator("cadence")
    @classmethod
    def _cadence(cls, v: str) -> str:
        low = v.strip().lower()
        if low not in CADENCES:
            raise ValueError(f"cadence must be one of {CADENCES}")
        return low

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: str) -> str:
        low = v.strip().lower()
        if low not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}")
        return low

    @field_validator("cron_expression")
    @classmethod
    def _cron_expr(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for r in v or []:
            if not isinstance(r, str):
                raise ValueError("recipients must be strings")
            s = r.strip()
            if s and s not in cleaned:
                cleaned.append(s)
        return cleaned

    @model_validator(mode="after")
    def _cadence_fields(self):
        if self.cadence == "daily":
            if self.minute_utc is None:
                self.minute_utc = 0
        elif self.cadence == "hourly":
            if self.minute_utc is None:
                self.minute_utc = 0
        validate_schedule_cadence_fields(
            cadence=self.cadence,
            hour_utc=self.hour_utc,
            minute_utc=self.minute_utc,
            interval_minutes=self.interval_minutes,
            cron_expression=self.cron_expression,
            channel=self.channel,
            recipients=list(self.recipients or []),
        )
        return self


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    """All fields optional (partial update). Uses explicit validators."""

    name: Optional[str] = Field(default=None, max_length=128)
    cadence: Optional[str] = None
    hour_utc: Optional[int] = Field(default=None, ge=0, le=23)
    minute_utc: Optional[int] = Field(default=None, ge=0, le=59)
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)
    cron_expression: Optional[str] = Field(default=None, max_length=512)

    profile_slug: Optional[str] = Field(default=None, max_length=64)
    digest_config: Optional[dict[str, Any]] = None

    channel: Optional[str] = None
    webhook_url: Optional[str] = Field(default=None, max_length=2048)
    recipients: Optional[list[str]] = None
    include_hidden_gems: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("cadence")
    @classmethod
    def _cadence(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        low = v.strip().lower()
        if low not in CADENCES:
            raise ValueError(f"cadence must be one of {CADENCES}")
        return low

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        low = v.strip().lower()
        if low not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}")
        return low

    @field_validator("cron_expression")
    @classmethod
    def _cron_expr(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        cleaned: list[str] = []
        for r in v:
            if not isinstance(r, str):
                raise ValueError("recipients must be strings")
            s = r.strip()
            if s and s not in cleaned:
                cleaned.append(s)
        return cleaned


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    cadence: str
    hour_utc: Optional[int] = None
    minute_utc: Optional[int] = None
    interval_minutes: Optional[int] = None
    cron_expression: Optional[str] = None
    profile_slug: Optional[str] = None
    digest_config: dict[str, Any]
    channel: str
    webhook_url: Optional[str] = None
    recipients: list[str]
    include_hidden_gems: bool
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_digest_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(BaseModel):
    total: int
    items: list[ScheduleOut]


class ScheduleRunResult(BaseModel):
    """Result of one run of a schedule (either via /run-now or tick)."""

    schedule_id: uuid.UUID
    status: str  # ok | error | skipped
    digest_id: Optional[uuid.UUID] = None
    channel: str
    delivered: bool
    detail: Optional[str] = None
    duration_ms: int


class TickResult(BaseModel):
    processed: int
    ok: int
    error: int
    skipped: int
    results: list[ScheduleRunResult]
