"""GET /collection/status — feed freshness and collection schedule info.

Used by the mobile app to show "Jobs last updated X hours ago · Next update in Yh"
without exposing internal scheduler controls to end users.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..api.deps import get_db
from ..config import get_settings
from ..models.board_collection_log import BoardCollectionLog
from ..models.job import Job

router = APIRouter(prefix="/collection", tags=["collection"])


class CollectionStatusResponse(BaseModel):
    # When the most recent board was last collected
    last_collected_at: Optional[_dt.datetime]
    # Next scheduled daily run (UTC)
    next_run_at: Optional[_dt.datetime]
    # Total active jobs in DB
    total_active_jobs: int
    # Boards collected in last 24h
    boards_collected_24h: int
    # Boards that are fresh (within freshness window)
    boards_fresh: int
    # Boards blocklisted due to repeated timeouts
    boards_blocklisted: int
    # Total boards known
    boards_total: int
    # Human-readable status
    status: str  # "ok" | "never_run" | "collection_disabled"


@router.get("/status", response_model=CollectionStatusResponse)
def get_collection_status(db: Session = Depends(get_db)) -> CollectionStatusResponse:
    settings = get_settings()
    now = _dt.datetime.now(_dt.timezone.utc)
    freshness_days = settings.ats_board_freshness_days
    max_timeouts = settings.ats_board_max_consecutive_timeouts

    # Most recent collection across all boards
    last_collected = db.scalar(
        select(func.max(BoardCollectionLog.last_collected_at))
    )

    # Board counts
    all_entries = db.scalars(select(BoardCollectionLog)).all()
    boards_total = len(all_entries)
    boards_fresh = sum(1 for e in all_entries if e.is_fresh(freshness_days))
    boards_blocklisted = sum(1 for e in all_entries if e.is_blocklisted(max_timeouts))

    # Boards collected in last 24h
    cutoff_24h = now - _dt.timedelta(hours=24)
    boards_24h = sum(
        1 for e in all_entries
        if e.last_collected_at and (
            e.last_collected_at.replace(tzinfo=_dt.timezone.utc)
            if e.last_collected_at.tzinfo is None
            else e.last_collected_at
        ) >= cutoff_24h
    )

    # Total active jobs
    total_active = db.scalar(
        select(func.count()).where(Job.is_active.is_(True))
    ) or 0

    # Next scheduled run
    next_run_at: Optional[_dt.datetime] = None
    if settings.collection_enabled:
        hour = settings.collection_hour_utc
        minute = settings.collection_minute_utc
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += _dt.timedelta(days=1)
        next_run_at = target

    # Status
    if not settings.collection_enabled:
        status = "collection_disabled"
    elif last_collected is None:
        status = "never_run"
    else:
        status = "ok"

    return CollectionStatusResponse(
        last_collected_at=last_collected,
        next_run_at=next_run_at,
        total_active_jobs=total_active,
        boards_collected_24h=boards_24h,
        boards_fresh=boards_fresh,
        boards_blocklisted=boards_blocklisted,
        boards_total=boards_total,
        status=status,
    )
