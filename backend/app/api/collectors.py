"""Collector-facing endpoints.

Collectors POST raw records here. They do NOT dedupe. They do NOT call
cleaner_v2. They just emit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from ..models.ingestion_run import IngestionRun
from ..models.raw_job_event import RawJobEvent
from ..schemas.ingestion import (
    BulkIngestResult,
    BulkRawJobEventCreate,
    IngestionRunCreate,
    IngestionRunOut,
)
from .deps import DbSession, require_admin_token

router = APIRouter()


@router.get(
    "/runs",
    response_model=list[IngestionRunOut],
    summary="List recent ingestion_runs (newest first).",
)
def list_runs(
    db: DbSession,
    limit: int = Query(20, ge=1, le=200),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="running | success | partial | failed",
    ),
) -> list[IngestionRunOut]:
    stmt = select(IngestionRun)
    if status_filter:
        stmt = stmt.where(IngestionRun.status == status_filter)
    stmt = stmt.order_by(IngestionRun.started_at.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [IngestionRunOut.model_validate(r) for r in rows]


@router.post(
    "/run",
    response_model=IngestionRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_token)],
    summary="Open a new ingestion_run for a collector.",
)
def open_run(payload: IngestionRunCreate, db: DbSession) -> IngestionRunOut:
    run = IngestionRun(
        source_name=payload.source_name,
        source_type=payload.source_type,
        run_metadata=payload.metadata,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return IngestionRunOut.model_validate(run)


@router.post(
    "/raw-events",
    response_model=BulkIngestResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_token)],
    summary="Bulk-submit raw_job_events from a collector.",
)
def submit_raw_events(payload: BulkRawJobEventCreate, db: DbSession) -> BulkIngestResult:
    # Resolve or create the ingestion run.
    if payload.ingestion_run_id is not None:
        run = db.get(IngestionRun, payload.ingestion_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="ingestion_run not found")
    else:
        if not (payload.source_name and payload.source_type):
            raise HTTPException(
                status_code=400,
                detail="source_name and source_type are required when ingestion_run_id is not provided",
            )
        run = IngestionRun(
            source_name=payload.source_name,
            source_type=payload.source_type,
            run_metadata=payload.metadata,
            status="running",
        )
        db.add(run)
        db.flush()

    event_ids: list = []
    failed = 0

    for ev in payload.events:
        try:
            row = RawJobEvent(
                ingestion_run_id=run.id,
                provider=ev.provider,
                source_url=ev.source_url,
                raw_payload=ev.raw_payload,
                raw_html=ev.raw_html,
                fetch_status=ev.fetch_status or "fetched",
                parse_status="pending",
            )
            db.add(row)
            db.flush()
            event_ids.append(row.id)
        except Exception:  # noqa: BLE001
            failed += 1

    inserted = len(event_ids)
    run.rows_seen = (run.rows_seen or 0) + inserted + failed
    run.rows_failed = (run.rows_failed or 0) + failed

    if payload.finalize:
        run.status = "success" if failed == 0 else "partial"
        run.completed_at = datetime.now(timezone.utc)

    db.commit()

    return BulkIngestResult(
        ingestion_run_id=run.id,
        inserted=inserted,
        failed=failed,
        event_ids=event_ids,
    )


@router.post(
    "/run/{run_id}/finalize",
    response_model=IngestionRunOut,
    dependencies=[Depends(require_admin_token)],
    summary="Close an ingestion_run and stamp completed_at.",
)
def finalize_run(run_id, db: DbSession) -> IngestionRunOut:
    run = db.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ingestion_run not found")
    run.status = "success" if (run.rows_failed or 0) == 0 else "partial"
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return IngestionRunOut.model_validate(run)
