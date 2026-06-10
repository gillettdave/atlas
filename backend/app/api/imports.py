"""Importer / ranker endpoints — drive cleaner_v2 and ranker."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

_log = logging.getLogger("atlas.api.imports")

from urllib.parse import urlparse

from ..models.ingestion_source import IngestionSource
from ..schemas.ingestion import (
    BackfillRequest,
    BackfillResult,
    IngestionSourceCreate,
    IngestionSourceListResponse,
    IngestionSourceOut,
    IngestionSourcesSyncFromCsvRequest,
    IngestionSourcesSyncFromCsvResult,
    ManualJobUrlRequest,
    ManualJobUrlResponse,
    ProcessPendingRequest,
    ProcessPendingResult,
    RescoreRequest,
    RescoreResult,
)
from ..services import manual_job_url as manual_job_svc
from ..services import backfill as backfill_svc
from ..services import importer, profiles as profiles_svc, ranker
from ..services.collector_pipeline import resolve_input_csv_path
from ..services import ingestion_sources_collect as ingestion_src_collect
from ..services import ingestion_sources_list as ingestion_src_list
from ..db import SessionLocal
from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter()


@router.post(
    "/process-pending",
    response_model=ProcessPendingResult,
    dependencies=[Depends(require_admin_token)],
    summary="Run cleaner_v2 over pending raw_job_events.",
)
def process_pending(payload: ProcessPendingRequest, db: DbSession) -> ProcessPendingResult:
    import logging, traceback
    _log = logging.getLogger("atlas.api.imports")
    try:
        stats = importer.process_pending(
            db,
            limit=payload.limit,
            ingestion_run_id=payload.ingestion_run_id,
            intake_max_listing_age_days=payload.intake_max_listing_age_days,
        )
    except Exception as e:
        _log.error("process_pending CRASHED: %s\n%s", e, traceback.format_exc())
        raise
    return ProcessPendingResult(
        processed=stats.processed,
        new_canonical=stats.new_canonical,
        matched_existing=stats.matched_existing,
        possible_duplicate_review=stats.possible_duplicate_review,
        rejected_low_quality=stats.rejected_low_quality,
        failed=stats.failed,
    )


@router.post(
    "/rescore",
    response_model=RescoreResult,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Run the ranker across canonical jobs. Without profile_slug: "
        "scores against the default profile and updates jobs.ranking_score / "
        "quality_score. With profile_slug: scores against that profile and "
        "only writes per-profile job_scores rows."
    ),
)
def rescore(payload: RescoreRequest, db: DbSession) -> RescoreResult:
    profile = None
    if payload.profile_slug:
        profile = profiles_svc.get_by_slug(db, payload.profile_slug)
        if profile is None:
            raise HTTPException(
                status_code=404,
                detail=f"profile not found: {payload.profile_slug!r}",
            )

    stats = ranker.rescore_jobs(
        db,
        provider=payload.provider,
        only_active=payload.only_active,
        only_unscored=payload.only_unscored,
        limit=payload.limit,
        profile=profile,
    )
    return RescoreResult(
        scored=stats.scored,
        failed=stats.failed,
        hidden_gems=stats.hidden_gems,
        by_bucket=stats.by_bucket,
        profile_slug=profile.slug if profile else None,
    )


def _bg_rescore(payload_dict: dict) -> None:
    db = SessionLocal()
    try:
        profile = None
        if payload_dict.get("profile_slug"):
            profile = profiles_svc.get_by_slug(db, payload_dict["profile_slug"])
        ranker.rescore_jobs(
            db,
            provider=payload_dict.get("provider"),
            only_active=payload_dict.get("only_active", True),
            only_unscored=payload_dict.get("only_unscored", False),
            limit=payload_dict.get("limit"),
            profile=profile,
        )
        _log.info("bg_rescore complete")
    except Exception as exc:
        _log.error("bg_rescore failed: %s", exc)
    finally:
        db.close()


@router.post(
    "/rescore-async",
    status_code=202,
    dependencies=[Depends(require_admin_token)],
    summary="Queue a rescore in the background — returns 202 immediately.",
)
def rescore_async(
    payload: RescoreRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    background_tasks.add_task(_bg_rescore, payload.model_dump())
    return {"status": "queued"}


@router.post(
    "/backfill-normalization",
    response_model=BackfillResult,
    dependencies=[Depends(require_admin_token)],
    summary="Re-normalize existing Jobs using their latest RawJobEvent (fills remote_type, employment_type, etc.).",
)
def backfill_normalization(payload: BackfillRequest, db: DbSession) -> BackfillResult:
    stats = backfill_svc.backfill_jobs(
        db,
        only_missing_remote_type=payload.only_missing_remote_type,
        only_active=payload.only_active,
        limit=payload.limit,
        force=payload.force,
        then_rescore=payload.then_rescore,
    )
    return BackfillResult(
        scanned=stats.scanned,
        updated=stats.updated,
        unchanged=stats.unchanged,
        no_raw_event=stats.no_raw_event,
        failed=stats.failed,
        rescored=stats.rescored,
        fields_filled=stats.fields_filled,
    )


# --- Phase C: manual posting URL + DB-backed sources stub -------------------


@router.post(
    "/manual-job-url",
    response_model=ManualJobUrlResponse,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Fetch a job-posting URL, derive title/company/description heuristically, "
        "insert a RawJobEvent (provider manual_job_page), then run importer. "
        "Optionally rescored that job only."
    ),
)
def post_manual_job_url(
    payload: ManualJobUrlRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ManualJobUrlResponse:
    pu = urlparse(payload.url.strip())
    if pu.scheme not in ("http", "https") or not pu.netloc:
        raise HTTPException(status_code=400, detail="url must be absolute http(s)")

    if payload.ingestion_source_id is not None:
        sr = db.get(IngestionSource, payload.ingestion_source_id)
        if sr is None:
            raise HTTPException(status_code=404, detail="ingestion_source not found")
        if sr.user_id != tenant_id:
            raise HTTPException(status_code=403, detail="ingestion_source not owned by tenant")

    r = manual_job_svc.ingest_manual_job_url(
        db,
        page_url=payload.url,
        title_override=payload.title_override,
        company_override=payload.company_override,
        ingest_source_id=payload.ingestion_source_id,
        tenant_user_id=tenant_id,
        then_process=payload.then_process,
        then_rescore=payload.then_rescore,
        profile_slug=payload.profile_slug,
        profile_user_id=tenant_id,
    )
    return ManualJobUrlResponse(
        ingestion_run_id=r.ingestion_run_id,
        raw_event_id=r.raw_event_id,
        fetch_status=r.fetch_status,
        parse_status=r.parse_status,
        job_id=r.job_id,
    )


@router.get(
    "/sources",
    response_model=IngestionSourceListResponse,
    summary="List/search DB-backed ingestion source rows for the current tenant.",
)
def list_ingestion_sources(
    db: DbSession,
    tenant_id: TenantUserId,
    q: str | None = Query(
        default=None,
        max_length=200,
        description="Case-insensitive search across label, notes, ATS/URLs, resolution_type.",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description=(
            "Page size (1–500). Omit to return all matching rows (from offset)—can be heavy."
        ),
    ),
    offset: int = Query(
        default=0,
        ge=0,
        le=1_000_000,
        description="Items to skip. With limit omitted, skips then returns remainder.",
    ),
) -> IngestionSourceListResponse:
    total, rows = ingestion_src_list.list_ingestion_sources(
        db,
        tenant_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    return IngestionSourceListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=rows,
    )


@router.post(
    "/sources",
    response_model=IngestionSourceOut,
    status_code=201,
    dependencies=[Depends(require_admin_token)],
    summary="Create an ingestion_sources row (replaces reliance on CSV-only operator lists).",
)
def create_ingestion_source(
    payload: IngestionSourceCreate,
    db: DbSession,
    tenant_id: TenantUserId,
) -> IngestionSource:
    row = IngestionSource(
        user_id=tenant_id,
        label=payload.label.strip(),
        notes=(payload.notes.strip() if payload.notes else None),
        jobs_page_url=(payload.jobs_page_url.strip() if payload.jobs_page_url else None),
        careers_site_url=(payload.careers_site_url.strip() if payload.careers_site_url else None),
        ats_board_url=(payload.ats_board_url.strip() if payload.ats_board_url else None),
        ats_type=(payload.ats_type.strip() if payload.ats_type else None),
        resolution_type=(payload.resolution_type.strip() if payload.resolution_type else None),
        extra_metadata={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post(
    "/sources/sync-from-csv",
    response_model=IngestionSourcesSyncFromCsvResult,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Upsert ingestion_sources from jobs_targets-, ats_targets-, or explicitly "
        "(csv_format) shaped CSV paths relative to ATLAS_REPO_ROOT / repo root."
    ),
)
def sync_ingestion_sources_from_csv(
    payload: IngestionSourcesSyncFromCsvRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> IngestionSourcesSyncFromCsvResult:
    csv_path = resolve_input_csv_path(payload.csv_path.strip())
    try:
        stats = ingestion_src_collect.sync_jobs_targets_csv(
            db=db,
            user_id=tenant_id,
            csv_path=csv_path,
            limit=payload.limit,
            dry_run=payload.dry_run,
            csv_format=payload.csv_format,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"CSV not found: {payload.csv_path}",
        ) from None
    if stats.get("skipped_unrecognized_csv"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not infer CSV layout — expected **jobs_targets** headers "
                "(e.g. source, profile_url) or **ats_targets** "
                "(company_name + ats_slug + ats_board_url), or pass csv_format explicitly."
            ),
        )
    return IngestionSourcesSyncFromCsvResult(
        total_rows_read=int(stats["total_rows_read"]),
        created=int(stats["created"]),
        updated=int(stats["updated"]),
        skipped_empty_label=int(stats["skipped_empty_label"]),
        dry_run=bool(stats["dry_run"]),
        csv_format_used=str(stats.get("csv_format_used") or "unknown"),
    )
