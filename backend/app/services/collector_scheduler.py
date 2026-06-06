"""collector_scheduler — Sprint M.1: timed collection pipeline.

Reuses the same cadence math as `services.scheduler` (daily / hourly /
every_n_minutes / cron UTC) against `CollectorSchedule` rows. Each run executes
`collector_pipeline.run_collector_pipeline` in-process (can take minutes;
do not set interval too short).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from croniter import croniter

from ..config import Settings, get_settings
from ..constants import SEEDED_LOCAL_USER_ID
from ..models.collector_schedule import CollectorSchedule
from ..models.pipeline_event import PipelineEvent
from . import collector_pipeline as capline
from . import ingestion_sources_collect as ingestion_src_collect


logger = logging.getLogger("atlas.collector_scheduler")


def _collector_schedule_pipeline_retryable(res: capline.CollectorPipelineResult) -> bool:
    """Avoid a second full pipeline if an ingestion run exists (partial progress)."""

    if res.ok or not res.error:
        return False
    if res.ingestion_run_id is not None:
        return False
    err = (res.error or "").lower()
    needles = (
        "connect",
        "timeout",
        "remote",
        "disconnect",
        "broken pipe",
        "503",
        "502",
        "504",
        "429",
        "reset",
        "temporary",
        "refused",
        "unavailable",
        "pooltimeout",
        "readtimeout",
        "writetimeout",
        "readerror",
        "writeerror",
        "not reachable",
        "connection",
    )
    return any(n in err for n in needles)


def compute_next_run(
    schedule: CollectorSchedule, *, now: Optional[datetime] = None
) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cadence = (schedule.cadence or "").lower()
    if cadence == "daily":
        hour = int(schedule.hour_utc or 0)
        minute = int(schedule.minute_utc or 0)
        candidate = now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate
    if cadence == "hourly":
        minute = int(schedule.minute_utc or 0)
        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(hours=1)
        return candidate
    if cadence == "every_n_minutes":
        interval = max(int(schedule.interval_minutes or 1), 1)
        anchor = schedule.last_run_at or now
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        candidate = anchor + timedelta(minutes=interval)
        if candidate <= now:
            candidate = now + timedelta(minutes=interval)
        return candidate
    if cadence == "cron":
        expr = (schedule.cron_expression or "").strip()
        if not expr:
            raise ValueError("cadence=cron requires cron_expression")
        if not croniter.is_valid(expr):
            raise ValueError(f"invalid cron_expression: {expr!r}")
        base = now.astimezone(timezone.utc).replace(tzinfo=None)
        itr = croniter(expr, base)
        nxt = itr.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        else:
            nxt = nxt.astimezone(timezone.utc)
        return nxt
    raise ValueError(f"unknown cadence: {schedule.cadence!r}")


def next_run_after_collector_error(
    schedule: CollectorSchedule,
    res: capline.CollectorPipelineResult,
    *,
    now: datetime,
    settings: Settings,
) -> datetime:
    """Next fire after a failed run (may advance sooner than cadence if transient)."""
    regular = compute_next_run(schedule, now=now)
    retry_s = float(settings.collector_schedule_error_retry_seconds)
    if retry_s > 0.0 and _collector_schedule_pipeline_retryable(res):
        early = now + timedelta(seconds=retry_s)
        return min(regular, early)
    return regular


@dataclass
class CollectorRunOutcome:
    schedule_id: uuid.UUID
    status: str  # "ok" | "error" | "skipped"
    detail: Optional[str]
    duration_ms: int
    ingestion_run_id: Optional[uuid.UUID] = None
    digest_id: Optional[uuid.UUID] = None


def ensure_next_run_set(
    db: Session, schedule: CollectorSchedule, *, now: Optional[datetime] = None
) -> None:
    if schedule.next_run_at is not None or not schedule.is_active:
        return
    try:
        schedule.next_run_at = compute_next_run(schedule, now=now)
    except ValueError:
        schedule.next_run_at = None


def run_schedule(
    db: Session,
    schedule: CollectorSchedule,
    *,
    now: Optional[datetime] = None,
    force: bool = False,
) -> CollectorRunOutcome:
    started = time.perf_counter()
    now = now or datetime.now(timezone.utc)
    sid = schedule.id
    if not schedule.is_active and not force:
        schedule.last_run_at = now
        schedule.last_status = "skipped"
        schedule.last_error = "schedule is inactive"
        schedule.next_run_at = None
        db.add(
            PipelineEvent(
                entity_type="collector_schedule",
                entity_id=sid,
                event_name="collector_skipped",
                details={"reason": "inactive"},
            )
        )
        db.commit()
        return CollectorRunOutcome(
            schedule_id=sid,
            status="skipped",
            detail="inactive",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    path: Optional[Path] = None
    preloaded: Optional[list] = None
    in_label = ""
    if schedule.use_ingestion_sources:
        uid = schedule.ingestion_sources_user_id or SEEDED_LOCAL_USER_ID
        preloaded = ingestion_src_collect.load_source_rows_from_db(
            db,
            uid,
            limit=schedule.source_limit,
        )
        in_label = "ingestion_sources"
    else:
        path = capline.resolve_input_csv_path(schedule.input_csv_path)

    settings = get_settings()
    max_extra = int(settings.collector_schedule_extra_run_attempts)
    base_wait = float(settings.collector_schedule_retry_backoff_seconds)

    def _run_pipeline() -> capline.CollectorPipelineResult:
        return capline.run_collector_pipeline(
            input_csv=path,
            sources=preloaded,
            input_label=in_label,
            source_limit=schedule.source_limit if not schedule.use_ingestion_sources else None,
            headless=bool(schedule.headless),
            batch_size=int(schedule.batch_size or 50),
            source_name=schedule.source_name or "web3_ats_collector",
            source_type=schedule.source_type or "ats",
            then_import=bool(schedule.then_import),
            process_pending_limit=int(schedule.process_pending_limit or 10_000),
            then_rank=bool(schedule.then_rank),
            rank_profile_slug=schedule.rank_profile_slug,
            rank_only_unscored=bool(schedule.rank_only_unscored),
            rank_limit=schedule.rank_limit,
            then_digest=bool(schedule.then_digest),
            digest_type=schedule.digest_type or "daily",
            digest_fresh_hours=int(schedule.digest_fresh_hours or 48),
            digest_fresh_limit=int(schedule.digest_fresh_limit or 15),
            digest_gem_limit=int(schedule.digest_gem_limit or 10),
            digest_per_company_cap=int(schedule.digest_per_company_cap or 3),
            digest_min_ranking_score=schedule.digest_min_ranking_score or "35",
            digest_gem_min_score=schedule.digest_gem_min_score or "60",
            digest_profile_slug=schedule.digest_profile_slug,
            progress_log=True,
        )

    res = _run_pipeline()
    extra_done = 0
    while (
        (not res.ok or res.error)
        and extra_done < max_extra
        and _collector_schedule_pipeline_retryable(res)
    ):
        extra_done += 1
        pause = base_wait * extra_done
        logger.warning(
            "collector_schedule %s transient pipeline error; full retry %s/%s "
            "after %.1fs pause: %.200s",
            sid,
            extra_done,
            max_extra,
            pause,
            res.error or "",
        )
        time.sleep(pause)
        res = _run_pipeline()

    ms = int((time.perf_counter() - started) * 1000)
    if not res.ok or res.error:
        return _mark_error(db, schedule, now, res, started, sid)

    schedule.last_run_at = now
    schedule.last_status = "ok"
    schedule.last_error = None
    schedule.last_ingestion_run_id = res.ingestion_run_id
    schedule.last_digest_id = res.digest_id
    schedule.last_duration_sec = res.duration_sec
    try:
        schedule.next_run_at = compute_next_run(schedule, now=now)
    except ValueError:
        schedule.next_run_at = None

    db.add(
        PipelineEvent(
            entity_type="collector_schedule",
            entity_id=sid,
            event_name="collector_run",
            details={
                "status": "ok",
                "ingestion_run_id": str(res.ingestion_run_id)
                if res.ingestion_run_id
                else None,
                "digest_id": str(res.digest_id) if res.digest_id else None,
                "sources_with_records": res.sources_with_records,
                "records_inserted": res.records_inserted,
                "import_processed": res.import_processed,
                "rank_scored": res.rank_scored,
                "duration_sec": res.duration_sec,
            },
        )
    )
    db.commit()
    return CollectorRunOutcome(
        schedule_id=sid,
        status="ok",
        detail="pipeline completed",
        duration_ms=ms,
        ingestion_run_id=res.ingestion_run_id,
        digest_id=res.digest_id,
    )


def _mark_error(
    db: Session,
    schedule: CollectorSchedule,
    now: datetime,
    res: capline.CollectorPipelineResult,
    started: float,
    sid: uuid.UUID,
) -> CollectorRunOutcome:
    ms = int((time.perf_counter() - started) * 1000)
    err = (res.error or "pipeline error")[:2000]
    schedule.last_run_at = now
    schedule.last_status = "error"
    schedule.last_error = err
    if res.ingestion_run_id:
        schedule.last_ingestion_run_id = res.ingestion_run_id
    if res.digest_id:
        schedule.last_digest_id = res.digest_id
    schedule.last_duration_sec = res.duration_sec
    try:
        schedule.next_run_at = next_run_after_collector_error(
            schedule, res, now=now, settings=get_settings()
        )
    except ValueError:
        schedule.next_run_at = None
    db.add(
        PipelineEvent(
            entity_type="collector_schedule",
            entity_id=sid,
            event_name="collector_run",
            details={"status": "error", "message": err[:500], **res.to_details()},
        )
    )
    db.commit()
    logger.error("collector schedule failed: %s", err)
    return CollectorRunOutcome(
        schedule_id=sid, status="error", detail=err[:200], duration_ms=ms
    )


def _pick_due(
    db: Session, *, now: datetime, limit: int
) -> list[CollectorSchedule]:
    stmt = (
        select(CollectorSchedule)
        .where(CollectorSchedule.is_active.is_(True))
        .where(
            (CollectorSchedule.next_run_at.is_(None))
            | (CollectorSchedule.next_run_at <= now)
        )
        .order_by(CollectorSchedule.next_run_at.asc().nulls_first())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(db.execute(stmt).scalars().all())


def tick(
    db: Session,
    *,
    now: Optional[datetime] = None,
    max_per_tick: int = 2,
) -> list[CollectorRunOutcome]:
    now = now or datetime.now(timezone.utc)
    due = _pick_due(db, now=now, limit=max_per_tick)
    if not due:
        return []
    due_ids = [s.id for s in due]
    db.commit()
    out: list[CollectorRunOutcome] = []
    for i in due_ids:
        row = db.get(CollectorSchedule, i)
        if row is None:
            continue
        out.append(run_schedule(db, row, now=now, force=False))
    return out
