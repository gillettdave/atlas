"""Delivery schedule endpoints (Sprint H)."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.delivery_schedule import DeliverySchedule
from ..schemas.schedule import (
    ScheduleCreate,
    ScheduleListResponse,
    ScheduleOut,
    ScheduleRunResult,
    ScheduleUpdate,
    TickResult,
    validate_schedule_cadence_fields,
)
from ..services import scheduler as scheduler_svc
from .deps import DbSession, require_admin_token

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_by_id(db: Session, schedule_id: uuid.UUID) -> DeliverySchedule:
    s = db.get(DeliverySchedule, schedule_id)
    if s is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return s


def _assign(schedule: DeliverySchedule, body: dict[str, Any]) -> None:
    """Copy provided fields onto the ORM row. Skips None / unset keys."""
    for k, v in body.items():
        if v is None and k not in {"profile_slug", "webhook_url", "last_error"}:
            # For most fields, None on PATCH means "don't change". But we
            # explicitly let the caller clear profile_slug / webhook_url
            # by sending them as null in the body (handled below).
            continue
        setattr(schedule, k, v)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ScheduleListResponse,
    summary="List delivery schedules.",
)
def list_schedules(
    db: DbSession,
    only_active: bool = Query(False),
) -> ScheduleListResponse:
    stmt = select(DeliverySchedule)
    if only_active:
        stmt = stmt.where(DeliverySchedule.is_active.is_(True))
    stmt = stmt.order_by(
        DeliverySchedule.is_active.desc(),
        DeliverySchedule.next_run_at.asc().nulls_last(),
        DeliverySchedule.name.asc(),
    )
    items = list(db.execute(stmt).scalars().all())
    total = int(
        db.execute(select(func.count(DeliverySchedule.id))).scalar_one() or 0
    )
    return ScheduleListResponse(
        total=total, items=[ScheduleOut.model_validate(s) for s in items]
    )


@router.post(
    "",
    response_model=ScheduleOut,
    dependencies=[Depends(require_admin_token)],
    status_code=201,
    summary="Create a delivery schedule.",
)
def create_schedule(payload: ScheduleCreate, db: DbSession) -> ScheduleOut:
    schedule = DeliverySchedule(
        name=payload.name.strip(),
        cadence=payload.cadence,
        hour_utc=payload.hour_utc,
        minute_utc=payload.minute_utc,
        interval_minutes=payload.interval_minutes,
        cron_expression=(payload.cron_expression or None),
        profile_slug=(payload.profile_slug or None),
        digest_config=dict(payload.digest_config or {}),
        channel=payload.channel,
        webhook_url=(payload.webhook_url or None),
        recipients=list(payload.recipients or []),
        include_hidden_gems=bool(payload.include_hidden_gems),
        is_active=bool(payload.is_active),
    )
    db.add(schedule)
    try:
        db.flush()
        scheduler_svc.ensure_next_run_set(db, schedule)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"failed to create schedule: {e.orig}",
        ) from e
    db.refresh(schedule)
    return ScheduleOut.model_validate(schedule)


@router.get(
    "/{schedule_id}",
    response_model=ScheduleOut,
    summary="Get a schedule by id.",
)
def get_schedule(schedule_id: uuid.UUID, db: DbSession) -> ScheduleOut:
    return ScheduleOut.model_validate(_get_by_id(db, schedule_id))


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleOut,
    dependencies=[Depends(require_admin_token)],
    summary="Update a schedule (partial).",
)
def update_schedule(
    schedule_id: uuid.UUID, payload: ScheduleUpdate, db: DbSession
) -> ScheduleOut:
    schedule = _get_by_id(db, schedule_id)
    data = payload.model_dump(exclude_unset=True)

    cadence_related = {
        "cadence",
        "hour_utc",
        "minute_utc",
        "interval_minutes",
        "cron_expression",
        "is_active",
    }
    touches_cadence = any(k in data for k in cadence_related)

    for key, value in data.items():
        setattr(schedule, key, value)

    try:
        validate_schedule_cadence_fields(
            cadence=schedule.cadence,
            hour_utc=schedule.hour_utc,
            minute_utc=schedule.minute_utc,
            interval_minutes=schedule.interval_minutes,
            cron_expression=schedule.cron_expression,
            channel=schedule.channel,
            recipients=list(schedule.recipients or []),
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        db.flush()
        if touches_cadence:
            # Recompute the next fire time to reflect the new cadence
            # (or clear it when the schedule was just deactivated).
            if schedule.is_active:
                try:
                    schedule.next_run_at = scheduler_svc.compute_next_run(
                        schedule
                    )
                except ValueError as e:
                    raise HTTPException(
                        status_code=400, detail=str(e)
                    ) from e
            else:
                schedule.next_run_at = None
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=400, detail=f"failed to update schedule: {e.orig}"
        ) from e
    db.refresh(schedule)
    return ScheduleOut.model_validate(schedule)


@router.delete(
    "/{schedule_id}",
    dependencies=[Depends(require_admin_token)],
    status_code=204,
    summary="Delete a schedule.",
)
def delete_schedule(schedule_id: uuid.UUID, db: DbSession) -> None:
    schedule = _get_by_id(db, schedule_id)
    db.delete(schedule)
    db.commit()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@router.post(
    "/{schedule_id}/run-now",
    response_model=ScheduleRunResult,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Fire a schedule immediately (even if inactive or not due). "
        "Still updates last_* and next_run_at."
    ),
)
def run_now(schedule_id: uuid.UUID, db: DbSession) -> ScheduleRunResult:
    schedule = _get_by_id(db, schedule_id)
    outcome = scheduler_svc.run_schedule(db, schedule, force=True)
    return ScheduleRunResult(
        schedule_id=outcome.schedule_id,
        status=outcome.status,
        digest_id=outcome.digest_id,
        channel=outcome.channel,
        delivered=outcome.delivered,
        detail=outcome.detail,
        duration_ms=outcome.duration_ms,
    )


@router.post(
    "/tick",
    response_model=TickResult,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Process all schedules whose next_run_at has arrived. Safe to "
        "invoke repeatedly (SELECT ... FOR UPDATE SKIP LOCKED)."
    ),
)
def tick_now(
    db: DbSession, max_per_tick: int = Query(25, ge=1, le=200)
) -> TickResult:
    outcomes = scheduler_svc.tick(db, max_per_tick=max_per_tick)
    return TickResult(
        processed=len(outcomes),
        ok=sum(1 for o in outcomes if o.status == "ok"),
        error=sum(1 for o in outcomes if o.status == "error"),
        skipped=sum(1 for o in outcomes if o.status == "skipped"),
        results=[
            ScheduleRunResult(
                schedule_id=o.schedule_id,
                status=o.status,
                digest_id=o.digest_id,
                channel=o.channel,
                delivered=o.delivered,
                detail=o.detail,
                duration_ms=o.duration_ms,
            )
            for o in outcomes
        ],
    )
