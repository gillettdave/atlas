"""scheduler - Sprint H.

Three responsibilities:

1. **Cadence math**: given a DeliverySchedule, compute `next_run_at` from
   `now` (and `last_run_at` for the `every_n_minutes` cadence). Supports
   `daily`, `hourly`, `every_n_minutes`, and `cron` (5-field UTC via croniter).

2. **Run one schedule**: build a digest with the schedule's config, then
   ship it via the configured channel. Transient digest build failures and
   Slack/email send failures can retry within the same run (see
   ``ATLAS_DELIVERY_SCHEDULE_*`` settings). Always update status columns and
   emit a `pipeline_events.schedule_run` row.

3. **Tick**: atomically pick up all due schedules (SELECT ... FOR UPDATE
   SKIP LOCKED) and run each. Safe to call concurrently from both the
   API endpoint and a background loop.

This module is intentionally synchronous — the background loop in
`app/main.py` wraps it in `asyncio.to_thread` so it doesn't block the
event loop.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from croniter import croniter

from ..config import Settings, get_settings
from ..models.delivery_schedule import DeliverySchedule
from ..models.pipeline_event import PipelineEvent
from . import digest_builder, digest_delivery, feed_alerts


logger = logging.getLogger("atlas.scheduler")


def _delivery_build_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (OperationalError, TimeoutError)):
        return True
    msg = str(exc).lower()
    needles = (
        "timeout",
        "connection reset",
        "connection refused",
        "connection",
        "ssl",
        "pool",
        "too many connections",
        "temporarily unavailable",
        "deadlock",
    )
    return any(n in msg for n in needles)


# ---------------------------------------------------------------------------
# Cadence math
# ---------------------------------------------------------------------------

def compute_next_run(
    schedule: DeliverySchedule, *, now: Optional[datetime] = None
) -> datetime:
    """Return the next scheduled fire time strictly greater than `now`.

    For `every_n_minutes` we anchor off `last_run_at` when available so
    drift stays bounded; otherwise we anchor off `now`.
    """
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
        # If we've fallen behind (e.g. server was down), snap to the next
        # interval tick relative to now rather than replay everything.
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


def next_run_after_failed_attempt(
    schedule: DeliverySchedule,
    exc: BaseException,
    *,
    now: datetime,
    settings: Settings,
) -> datetime:
    """`next_run_at` after a failed `run_schedule` (may advance sooner than cadence)."""
    regular = compute_next_run(schedule, now=now)
    retry_s = float(settings.delivery_schedule_error_retry_seconds)
    if retry_s > 0.0 and _delivery_build_retryable(exc):
        early = now + timedelta(seconds=retry_s)
        return min(regular, early)
    return regular


# ---------------------------------------------------------------------------
# Running one schedule
# ---------------------------------------------------------------------------

@dataclass
class RunOutcome:
    schedule_id: uuid.UUID
    status: str              # "ok" | "error" | "skipped"
    digest_id: Optional[uuid.UUID]
    channel: str
    delivered: bool
    detail: Optional[str]
    duration_ms: int


_ALLOWED_DIGEST_KEYS: set[str] = {
    "digest_type",
    "fresh_hours",
    "fresh_limit",
    "gem_limit",
    "per_company_cap",
    "min_ranking_score",
    "gem_min_score",
    "notes",
    "profile_slug",
    "apply_qualification",
}


def _build_digest_config(
    raw: dict[str, Any],
    *,
    profile_slug: Optional[str] = None,
) -> digest_builder.DigestConfig:
    """Filter/coerce a schedule's digest_config dict into a DigestConfig.

    `profile_slug` on the schedule row takes precedence over any value
    nested under `digest_config` so operators can't accidentally fork
    them out of sync.
    """
    clean: dict[str, Any] = {}
    for k, v in (raw or {}).items():
        if k not in _ALLOWED_DIGEST_KEYS:
            continue
        if k in ("min_ranking_score", "gem_min_score"):
            clean[k] = Decimal(str(v))
        else:
            clean[k] = v
    if profile_slug:
        clean["profile_slug"] = profile_slug
    return digest_builder.DigestConfig(**clean)


def run_schedule(
    db: Session,
    schedule: DeliverySchedule,
    *,
    now: Optional[datetime] = None,
    force: bool = False,
) -> RunOutcome:
    """Execute one schedule: build a digest, ship it, audit.

    Always updates `schedule.last_*` / `next_run_at` and writes a
    `pipeline_events.schedule_run` row. Commits the transaction.

    When `force=False` (the normal tick path), an inactive schedule is
    short-circuited to `skipped` with no digest built. `force=True`
    bypasses the active check (used by the /run-now endpoint).
    """
    started = time.perf_counter()
    now = now or datetime.now(timezone.utc)
    sched_id = schedule.id
    channel = (schedule.channel or "none").lower()

    if not schedule.is_active and not force:
        schedule.last_run_at = now
        schedule.last_status = "skipped"
        schedule.last_error = "schedule is inactive"
        schedule.next_run_at = None
        db.add(
            PipelineEvent(
                entity_type="delivery_schedule",
                entity_id=sched_id,
                event_name="schedule_skipped",
                details={"reason": "inactive", "channel": channel},
            )
        )
        db.commit()
        return RunOutcome(
            schedule_id=sched_id,
            status="skipped",
            digest_id=None,
            channel=channel,
            delivered=False,
            detail="schedule inactive",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    digest_id: Optional[uuid.UUID] = None
    delivered = False
    detail: Optional[str] = None

    try:
        settings = get_settings()
        backoff_s = float(settings.delivery_schedule_retry_backoff_seconds)
        max_digest_extra = int(settings.delivery_schedule_digest_build_extra_attempts)

        cfg = _build_digest_config(
            schedule.digest_config or {},
            profile_slug=schedule.profile_slug,
        )
        built: digest_builder.BuiltDigest | None = None
        for b_idx in range(1 + max_digest_extra):
            try:
                built = digest_builder.build_digest(db, cfg, now=now)
                break
            except BaseException as e:
                db.rollback()
                if (
                    b_idx >= max_digest_extra
                    or not _delivery_build_retryable(e)
                ):
                    raise
                pause = backoff_s * (b_idx + 1)
                logger.warning(
                    "delivery_schedule digest build transient (%s); retry %s/%s "
                    "after %.1fs: %s",
                    type(e).__name__,
                    b_idx + 1,
                    max_digest_extra + 1,
                    pause,
                    str(e)[:200],
                )
                time.sleep(pause)

        if built is None:
            raise RuntimeError("digest build failed unexpectedly after retries")

        digest_id = built.digest.id

        digest_alert_summary = feed_alerts.maybe_digest_top_jobs_alert(
            db, built, source="delivery_schedule"
        )

        if channel in ("slack", "email"):
            max_send_extra = int(settings.delivery_schedule_channel_send_extra_attempts)
            result: Optional[digest_delivery.DeliveryResult] = None
            for send_idx in range(1 + max_send_extra):
                result = digest_delivery.deliver(
                    db,
                    digest_id,
                    channel=channel,
                    webhook_url=schedule.webhook_url,
                    recipients=list(schedule.recipients or []),
                    include_hidden_gems=bool(schedule.include_hidden_gems),
                )
                delivered = bool(result.ok)
                detail = (
                    result.detail
                    or (
                        f"shipped via {channel} to {result.recipient}"
                        if result.ok
                        else f"{channel} send failed"
                    )
                )
                if result.ok:
                    break
                if send_idx < max_send_extra:
                    pause = backoff_s * (send_idx + 1)
                    logger.warning(
                        "delivery_schedule %s %s deliver attempt %s/%s not ok: %.200s "
                        "— retry in %.1fs",
                        sched_id,
                        channel,
                        send_idx + 1,
                        1 + max_send_extra,
                        result.detail or detail or "",
                        pause,
                    )
                    time.sleep(pause)
            if result is None or not result.ok:
                # Digest is persisted; raise to flip schedule status to
                # error. Operator can inspect last_error + reship the
                # stored digest via /digests/{id}/send.
                raise RuntimeError(f"delivery failed: {detail}")
        elif channel == "csv_only":
            detail = "digest built; CSV-only (pull via /digests/{id}/export.csv)"
        else:
            detail = "digest built; channel=none"

        schedule.last_run_at = now
        schedule.last_status = "ok"
        schedule.last_error = None
        schedule.last_digest_id = digest_id
        schedule.next_run_at = compute_next_run(schedule, now=now)

        db.add(
            PipelineEvent(
                entity_type="delivery_schedule",
                entity_id=sched_id,
                event_name="schedule_run",
                details={
                    "status": "ok",
                    "channel": channel,
                    "digest_id": str(digest_id) if digest_id else None,
                    "delivered": delivered,
                    "detail": detail,
                    "fresh_selected": built.stats.fresh_selected,
                    "gem_selected": built.stats.gem_selected,
                    "digest_alert": digest_alert_summary.to_details(),
                },
            )
        )
        db.commit()

        return RunOutcome(
            schedule_id=sched_id,
            status="ok",
            digest_id=digest_id,
            channel=channel,
            delivered=delivered,
            detail=detail,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    except Exception as e:  # noqa: BLE001
        db.rollback()
        # Re-fetch the row to avoid writing on a detached/expired
        # instance after the rollback above.
        fresh = db.get(DeliverySchedule, sched_id)
        if fresh is None:
            return RunOutcome(
                schedule_id=sched_id,
                status="error",
                digest_id=digest_id,
                channel=channel,
                delivered=False,
                detail=f"schedule vanished mid-run: {e}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        fresh.last_run_at = now
        fresh.last_status = "error"
        fresh.last_error = str(e)[:2000]
        fresh.last_digest_id = digest_id
        try:
            settings = get_settings()
            fresh.next_run_at = next_run_after_failed_attempt(
                fresh, e, now=now, settings=settings
            )
        except ValueError:
            fresh.next_run_at = None

        db.add(
            PipelineEvent(
                entity_type="delivery_schedule",
                entity_id=sched_id,
                event_name="schedule_run",
                details={
                    "status": "error",
                    "channel": channel,
                    "digest_id": str(digest_id) if digest_id else None,
                    "error_type": type(e).__name__,
                    "message": str(e)[:500],
                },
            )
        )
        db.commit()

        logger.exception("schedule run failed: id=%s", sched_id)
        return RunOutcome(
            schedule_id=sched_id,
            status="error",
            digest_id=digest_id,
            channel=channel,
            delivered=False,
            detail=str(e)[:500],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


# ---------------------------------------------------------------------------
# Tick: process all due schedules
# ---------------------------------------------------------------------------

def _pick_due(
    db: Session, *, now: datetime, limit: int
) -> list[DeliverySchedule]:
    """Fetch due schedules with FOR UPDATE SKIP LOCKED.

    "Due" means `is_active AND (next_run_at IS NULL OR next_run_at <= now)`.
    Returning them locked prevents a second worker from picking the same
    schedule during the same tick.
    """
    stmt = (
        select(DeliverySchedule)
        .where(DeliverySchedule.is_active.is_(True))
        .where(
            (DeliverySchedule.next_run_at.is_(None))
            | (DeliverySchedule.next_run_at <= now)
        )
        .order_by(DeliverySchedule.next_run_at.asc().nulls_first())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(db.execute(stmt).scalars().all())


def tick(
    db: Session,
    *,
    now: Optional[datetime] = None,
    max_per_tick: int = 25,
) -> list[RunOutcome]:
    """Run every schedule that is due right now. Returns per-schedule outcomes."""
    now = now or datetime.now(timezone.utc)
    due = _pick_due(db, now=now, limit=max_per_tick)
    if not due:
        return []

    outcomes: list[RunOutcome] = []
    # Release the row locks before calling run_schedule. run_schedule
    # does its own commit; holding the lock across it would serialize
    # all runs unnecessarily.
    due_ids = [s.id for s in due]
    db.commit()

    for sid in due_ids:
        schedule = db.get(DeliverySchedule, sid)
        if schedule is None:
            continue
        outcome = run_schedule(db, schedule, now=now, force=False)
        outcomes.append(outcome)

    return outcomes


def ensure_next_run_set(
    db: Session, schedule: DeliverySchedule, *, now: Optional[datetime] = None
) -> None:
    """Populate `next_run_at` if empty. Called after create/update."""
    if schedule.next_run_at is not None or not schedule.is_active:
        return
    try:
        schedule.next_run_at = compute_next_run(schedule, now=now)
    except ValueError:
        # Invalid cadence config — leave next_run_at null; /run-now can
        # still fire it manually.
        schedule.next_run_at = None
