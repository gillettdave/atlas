"""job_expiry — daily culling of stale job listings.

Two passes per run:

Soft-expire (is_active → False):
  - Board / aggregator jobs not re-seen in 30 days
  - ATS board jobs not re-seen in 60 days

Hard-delete (row removed):
  - Any job that is_active=False and last_seen_at > 120 days ago
  - Protected: jobs with an application_job_track row (user touched them)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

from ..models.job import Job
from ..models.application_job_track import ApplicationJobTrack

logger = logging.getLogger("atlas.job_expiry")

# Providers whose listings stay live longer (direct ATS boards, not aggregators).
_ATS_PROVIDERS: frozenset[str] = frozenset({
    "greenhouse", "lever", "ashby", "smartrecruiters",
    "workable", "teamtailor", "kula", "native_jobs_page",
    "workday", "recruitee", "binance_native", "oracle_native",
    "jobs_page", "manual_job_page",
})

# Default thresholds (days)
_BOARD_SOFT_DAYS: int = 30
_ATS_SOFT_DAYS: int = 60
_HARD_DELETE_DAYS: int = 120


@dataclass
class ExpiryStats:
    soft_expired_board: int = 0
    soft_expired_ats: int = 0
    hard_deleted: int = 0
    protected_from_delete: int = 0


def expire_stale_jobs(
    db: Session,
    *,
    board_soft_days: int = _BOARD_SOFT_DAYS,
    ats_soft_days: int = _ATS_SOFT_DAYS,
    hard_delete_days: int = _HARD_DELETE_DAYS,
) -> ExpiryStats:
    stats = ExpiryStats()
    now = datetime.now(timezone.utc)

    # ── Soft-expire: board providers ────────────────────────────────────────
    board_cutoff = now - timedelta(days=board_soft_days)
    result = db.execute(
        update(Job)
        .where(
            Job.is_active.is_(True),
            Job.last_seen_at < board_cutoff,
            Job.provider.not_in(_ATS_PROVIDERS),
        )
        .values(is_active=False)
    )
    stats.soft_expired_board = result.rowcount

    # ── Soft-expire: ATS providers ───────────────────────────────────────────
    ats_cutoff = now - timedelta(days=ats_soft_days)
    result = db.execute(
        update(Job)
        .where(
            Job.is_active.is_(True),
            Job.last_seen_at < ats_cutoff,
            Job.provider.in_(_ATS_PROVIDERS),
        )
        .values(is_active=False)
    )
    stats.soft_expired_ats = result.rowcount

    # ── Hard-delete: inactive + old + no user interaction ───────────────────
    hard_cutoff = now - timedelta(days=hard_delete_days)

    # Count protected rows (so we can log them without two passes)
    protected_stmt = (
        select(Job.id)
        .where(
            Job.is_active.is_(False),
            Job.last_seen_at < hard_cutoff,
            exists(
                select(ApplicationJobTrack.id)
                .where(ApplicationJobTrack.job_id == Job.id)
            ),
        )
    )
    stats.protected_from_delete = len(db.execute(protected_stmt).all())

    delete_stmt = (
        delete(Job)
        .where(
            Job.is_active.is_(False),
            Job.last_seen_at < hard_cutoff,
            ~exists(
                select(ApplicationJobTrack.id)
                .where(ApplicationJobTrack.job_id == Job.id)
            ),
        )
    )
    result = db.execute(delete_stmt)
    stats.hard_deleted = result.rowcount

    db.commit()

    logger.info(
        "job_expiry: soft_expired board=%d ats=%d | hard_deleted=%d protected=%d",
        stats.soft_expired_board,
        stats.soft_expired_ats,
        stats.hard_deleted,
        stats.protected_from_delete,
    )
    return stats
