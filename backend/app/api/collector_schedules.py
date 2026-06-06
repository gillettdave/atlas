"""Collector schedule API — Sprint M.1."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.collector_schedule import CollectorSchedule
from ..schemas.collector_schedule import (
    CollectorPipelineRequest,
    CollectorPipelineResultOut,
    CollectorRunResult,
    CollectorScheduleCreate,
    CollectorScheduleListResponse,
    CollectorScheduleOut,
    CollectorScheduleUpdate,
    CollectorTickResult,
    validate_collector_cadence_fields,
)
from ..services import collector_pipeline as capline
from ..services import collector_scheduler as csched
from ..services import ingestion_sources_collect as ingestion_src_collect
from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter()


def _get_by_id(db: Session, schedule_id: uuid.UUID) -> CollectorSchedule:
    s = db.get(CollectorSchedule, schedule_id)
    if s is None:
        raise HTTPException(status_code=404, detail="collector schedule not found")
    return s


_NULLABLE_PATCH = frozenset(
    {
        "rank_profile_slug",
        "rank_limit",
        "source_limit",
        "digest_profile_slug",
        "ingestion_sources_user_id",
    }
)


def _assign(s: CollectorSchedule, body: dict[str, Any]) -> None:
    for k, v in body.items():
        if v is None and k not in _NULLABLE_PATCH:
            continue
        setattr(s, k, v)


# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=CollectorScheduleListResponse,
    summary="List collector schedules.",
)
def list_collector_schedules(
    db: DbSession,
    only_active: bool = Query(False),
) -> CollectorScheduleListResponse:
    stmt = select(CollectorSchedule)
    if only_active:
        stmt = stmt.where(CollectorSchedule.is_active.is_(True))
    stmt = stmt.order_by(
        CollectorSchedule.is_active.desc(),
        CollectorSchedule.next_run_at.asc().nulls_last(),
        CollectorSchedule.name.asc(),
    )
    items = list(db.execute(stmt).scalars().all())
    total = int(
        db.execute(select(func.count(CollectorSchedule.id))).scalar_one() or 0
    )
    return CollectorScheduleListResponse(
        total=total, items=[CollectorScheduleOut.model_validate(s) for s in items]
    )


@router.post(
    "/tick",
    response_model=CollectorTickResult,
    dependencies=[Depends(require_admin_token)],
    summary="Process all due collector schedules now.",
)
def tick_collector_schedules(
    db: DbSession,
    max_per_tick: int = Query(
        2, ge=1, le=50, description="Max schedules per tick."
    ),
) -> CollectorTickResult:
    outcomes = csched.tick(db, max_per_tick=max_per_tick)
    return CollectorTickResult(
        processed=len(outcomes),
        outcomes=[
            CollectorRunResult(
                schedule_id=o.schedule_id,
                status=o.status,
                detail=o.detail,
                duration_ms=o.duration_ms,
                ingestion_run_id=o.ingestion_run_id,
                digest_id=o.digest_id,
            )
            for o in outcomes
        ],
    )


@router.post(
    "/pipeline",
    response_model=CollectorPipelineResultOut,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Run the collect+import+rank pipeline once (no schedule row). "
        "Paths are relative to ATLAS_REPO_ROOT or repo auto-detect."
    ),
)
def run_pipeline_adhoc(
    payload: CollectorPipelineRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> CollectorPipelineResultOut:
    kw = dict(
        source_limit=payload.source_limit,
        headless=payload.headless,
        batch_size=payload.batch_size,
        source_name=payload.source_name,
        source_type=payload.source_type,
        then_import=payload.then_import,
        process_pending_limit=payload.process_pending_limit,
        then_rank=payload.then_rank,
        rank_profile_slug=payload.rank_profile_slug,
        rank_only_unscored=payload.rank_only_unscored,
        rank_limit=payload.rank_limit,
        then_digest=payload.then_digest,
        digest_type=payload.digest_type,
        digest_fresh_hours=payload.digest_fresh_hours,
        digest_fresh_limit=payload.digest_fresh_limit,
        digest_gem_limit=payload.digest_gem_limit,
        digest_per_company_cap=payload.digest_per_company_cap,
        digest_min_ranking_score=payload.digest_min_ranking_score,
        digest_gem_min_score=payload.digest_gem_min_score,
        digest_profile_slug=payload.digest_profile_slug,
        intake_max_listing_age_days=payload.intake_max_listing_age_days,
    )

    eff_uid = payload.ingestion_sources_user_id or tenant_id

    if payload.use_ingestion_sources:
        loaded = ingestion_src_collect.load_source_rows_from_db(
            db,
            eff_uid,
            limit=payload.source_limit,
        )
        if not loaded:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No collectable ingestion_sources rows for that user — sync CSV "
                    "first (`POST /imports/sources/sync-from-csv`), or check "
                    "ingestion_sources_user_id / Bearer tenant."
                ),
            )
        res = capline.run_collector_pipeline(
            input_csv=None,
            sources=loaded,
            input_label="ingestion_sources",
            **kw,
        )
    else:
        p = capline.resolve_input_csv_path(payload.input_csv_path)
        res = capline.run_collector_pipeline(input_csv=p, **kw)
    return CollectorPipelineResultOut(
        ok=res.ok,
        error=res.error,
        duration_sec=res.duration_sec,
        input_csv=res.input_csv,
        sources_attempted=res.sources_attempted,
        sources_with_records=res.sources_with_records,
        records_inserted=res.records_inserted,
        import_processed=res.import_processed,
        new_canonical=res.new_canonical,
        rank_scored=res.rank_scored,
        ingestion_run_id=res.ingestion_run_id,
        digest_id=res.digest_id,
        by_provider=res.by_provider,
    )


@router.post(
    "",
    response_model=CollectorScheduleOut,
    dependencies=[Depends(require_admin_token)],
    status_code=201,
    summary="Create a collector schedule.",
)
def create_collector_schedule(
    payload: CollectorScheduleCreate, db: DbSession
) -> CollectorScheduleOut:
    row = CollectorSchedule(
        name=payload.name,
        cadence=payload.cadence,
        hour_utc=payload.hour_utc,
        minute_utc=payload.minute_utc,
        interval_minutes=payload.interval_minutes,
        cron_expression=(payload.cron_expression or None),
        input_csv_path=payload.input_csv_path.strip(),
        use_ingestion_sources=payload.use_ingestion_sources,
        ingestion_sources_user_id=payload.ingestion_sources_user_id,
        source_limit=payload.source_limit,
        batch_size=payload.batch_size,
        headless=payload.headless,
        source_name=payload.source_name,
        source_type=payload.source_type,
        then_import=payload.then_import,
        process_pending_limit=payload.process_pending_limit,
        then_rank=payload.then_rank,
        rank_profile_slug=payload.rank_profile_slug,
        rank_only_unscored=payload.rank_only_unscored,
        rank_limit=payload.rank_limit,
        then_digest=payload.then_digest,
        digest_type=payload.digest_type,
        digest_fresh_hours=payload.digest_fresh_hours,
        digest_fresh_limit=payload.digest_fresh_limit,
        digest_gem_limit=payload.digest_gem_limit,
        digest_per_company_cap=payload.digest_per_company_cap,
        digest_profile_slug=payload.digest_profile_slug,
        digest_min_ranking_score=payload.digest_min_ranking_score,
        digest_gem_min_score=payload.digest_gem_min_score,
        is_active=payload.is_active,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="schedule name already exists"
        ) from e
    db.refresh(row)
    csched.ensure_next_run_set(db, row)
    db.commit()
    db.refresh(row)
    return CollectorScheduleOut.model_validate(row)


@router.get(
    "/{schedule_id}",
    response_model=CollectorScheduleOut,
    summary="Get a collector schedule by id.",
)
def get_collector_schedule(
    schedule_id: uuid.UUID, db: DbSession
) -> CollectorScheduleOut:
    return CollectorScheduleOut.model_validate(_get_by_id(db, schedule_id))


@router.patch(
    "/{schedule_id}",
    response_model=CollectorScheduleOut,
    dependencies=[Depends(require_admin_token)],
    summary="Update a collector schedule.",
)
def update_collector_schedule(
    schedule_id: uuid.UUID, payload: CollectorScheduleUpdate, db: DbSession
) -> CollectorScheduleOut:
    row = _get_by_id(db, schedule_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    _assign(row, data)
    try:
        validate_collector_cadence_fields(
            cadence=row.cadence,
            hour_utc=row.hour_utc,
            minute_utc=row.minute_utc,
            interval_minutes=row.interval_minutes,
            cron_expression=row.cron_expression,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e

    cadence_related = {
        "cadence",
        "hour_utc",
        "minute_utc",
        "interval_minutes",
        "cron_expression",
        "is_active",
    }
    touches_schedule = any(k in data for k in cadence_related)
    try:
        if touches_schedule:
            if row.is_active:
                try:
                    row.next_run_at = csched.compute_next_run(row)
                except ValueError as e:
                    db.rollback()
                    raise HTTPException(status_code=400, detail=str(e)) from e
            else:
                row.next_run_at = None
        else:
            csched.ensure_next_run_set(db, row)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="schedule name already exists"
        ) from e
    db.refresh(row)
    return CollectorScheduleOut.model_validate(row)


@router.delete(
    "/{schedule_id}",
    dependencies=[Depends(require_admin_token)],
    status_code=204,
    summary="Delete a collector schedule.",
)
def delete_collector_schedule(schedule_id: uuid.UUID, db: DbSession) -> None:
    row = _get_by_id(db, schedule_id)
    db.delete(row)
    db.commit()


@router.post(
    "/{schedule_id}/run-now",
    response_model=CollectorRunResult,
    dependencies=[Depends(require_admin_token)],
    summary="Run a collector schedule immediately (force).",
)
def run_collector_schedule_now(
    schedule_id: uuid.UUID, db: DbSession
) -> CollectorRunResult:
    row = _get_by_id(db, schedule_id)
    out = csched.run_schedule(db, row, force=True)
    return CollectorRunResult(
        schedule_id=out.schedule_id,
        status=out.status,
        detail=out.detail,
        duration_ms=out.duration_ms,
        ingestion_run_id=out.ingestion_run_id,
        digest_id=out.digest_id,
    )

