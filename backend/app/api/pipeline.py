"""Pipeline monitoring / stats endpoints.

Read-only rollups intended to power the admin UI's Home page:
- job counts by bucket
- queue depths (pending raw events, needs_review)
- latest ingestion run + latest digest summary
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func, select

from ..models.digest import Digest
from ..models.digest_item import DigestItem
from ..models.ingestion_run import IngestionRun
from ..models.job import Job
from ..models.pipeline_event import PipelineEvent
from ..models.raw_job_event import RawJobEvent
from ..services import collector_pipeline as capline
from ..config import get_settings
from .deps import DbSession, require_admin_token

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas (kept local — these are UI rollups, not core domain types)
# ---------------------------------------------------------------------------

class JobBucketCounts(BaseModel):
    total: int
    top: int
    strong: int
    maybe: int
    skip: int


class RunSummary(BaseModel):
    id: str
    source_name: str
    source_type: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    rows_seen: int
    rows_inserted: int
    rows_failed: int


class DigestSummaryMini(BaseModel):
    id: str
    generated_at: datetime
    digest_type: str
    item_count: int


class PipelineStats(BaseModel):
    jobs_active: JobBucketCounts
    pending_raw_events: int
    needs_review: int
    latest_run: Optional[RunSummary] = None
    latest_digest: Optional[DigestSummaryMini] = None


class PipelineEventOut(BaseModel):
    id: str
    entity_type: str
    entity_id: Optional[str] = None
    event_name: str
    details: Optional[dict] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.get(
    "/events",
    response_model=list[PipelineEventOut],
    summary="Recent pipeline_events (filter by event_name / entity_type).",
)
def list_pipeline_events(
    db: DbSession,
    event_name: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 30,
) -> list[PipelineEventOut]:
    stmt = select(PipelineEvent)
    if event_name:
        stmt = stmt.where(PipelineEvent.event_name == event_name)
    if entity_type:
        stmt = stmt.where(PipelineEvent.entity_type == entity_type)
    stmt = stmt.order_by(PipelineEvent.created_at.desc()).limit(min(limit, 200))
    rows = db.execute(stmt).scalars().all()
    return [
        PipelineEventOut(
            id=str(r.id),
            entity_type=r.entity_type,
            entity_id=str(r.entity_id) if r.entity_id else None,
            event_name=r.event_name,
            details=r.details,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get(
    "/stats",
    response_model=PipelineStats,
    summary="Rollup of jobs, queues, latest run and latest digest.",
)
def stats(db: DbSession) -> PipelineStats:
    top_c = func.count(case((Job.ranking_score >= 75, 1)))
    strong_c = func.count(
        case(((Job.ranking_score >= 55) & (Job.ranking_score < 75), 1))
    )
    maybe_c = func.count(
        case(((Job.ranking_score >= 35) & (Job.ranking_score < 55), 1))
    )
    skip_c = func.count(case((Job.ranking_score < 35, 1)))

    row = db.execute(
        select(
            func.count(Job.id), top_c, strong_c, maybe_c, skip_c,
        ).where(Job.is_active.is_(True))
    ).one()
    total, top, strong, maybe, skip = (int(v or 0) for v in row)
    buckets = JobBucketCounts(
        total=total, top=top, strong=strong, maybe=maybe, skip=skip
    )

    pending = int(
        db.execute(
            select(func.count(RawJobEvent.id))
            .where(RawJobEvent.parse_status == "pending")
        ).scalar_one() or 0
    )
    review = int(
        db.execute(
            select(func.count(RawJobEvent.id))
            .where(RawJobEvent.parse_status == "needs_review")
        ).scalar_one() or 0
    )

    latest_run_row = db.execute(
        select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    latest_run = None
    if latest_run_row is not None:
        latest_run = RunSummary(
            id=str(latest_run_row.id),
            source_name=latest_run_row.source_name,
            source_type=latest_run_row.source_type,
            started_at=latest_run_row.started_at,
            completed_at=latest_run_row.completed_at,
            status=latest_run_row.status,
            rows_seen=latest_run_row.rows_seen or 0,
            rows_inserted=latest_run_row.rows_inserted or 0,
            rows_failed=latest_run_row.rows_failed or 0,
        )

    latest_digest_row = db.execute(
        select(Digest).order_by(Digest.generated_at.desc()).limit(1)
    ).scalar_one_or_none()
    latest_digest = None
    if latest_digest_row is not None:
        item_count = int(
            db.execute(
                select(func.count(DigestItem.id))
                .where(DigestItem.digest_id == latest_digest_row.id)
            ).scalar_one() or 0
        )
        latest_digest = DigestSummaryMini(
            id=str(latest_digest_row.id),
            generated_at=latest_digest_row.generated_at,
            digest_type=latest_digest_row.digest_type,
            item_count=item_count,
        )

    return PipelineStats(
        jobs_active=buckets,
        pending_raw_events=pending,
        needs_review=review,
        latest_run=latest_run,
        latest_digest=latest_digest,
    )


# ---------------------------------------------------------------------------
# 1-click "Find Jobs" endpoint
# ---------------------------------------------------------------------------

class FindJobsResult(BaseModel):
    ok: bool
    new_jobs: int
    duration_sec: float
    digest_id: Optional[str] = None
    error: Optional[str] = None


@router.post(
    "/find-jobs",
    response_model=FindJobsResult,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "1-click: collect from all enabled sources → import → rank → digest. "
        "Returns immediately with results. Runs synchronously (may take 30–120s)."
    ),
)
def find_jobs(db: DbSession) -> FindJobsResult:
    """Trigger a full collect+import+rank+digest cycle with zero configuration.

    Uses all enabled aggregators (RemoteOK, We Work Remotely) plus any per-company
    sources configured in ingestion_sources. Generates a 'daily' digest automatically.
    """
    s = get_settings()
    capline.clear_cancel()
    res = capline.run_collector_pipeline(
        input_csv=None,
        sources=None,
        then_import=True,
        then_rank=True,
        then_digest=s.find_jobs_then_digest,
        digest_type="daily",
        digest_fresh_hours=s.find_jobs_digest_fresh_hours,
        digest_fresh_limit=20,
        digest_gem_limit=10,
        source_name="find_jobs",
        source_type="aggregator",
    )
    return FindJobsResult(
        ok=res.ok,
        new_jobs=res.new_canonical or 0,
        duration_sec=res.duration_sec or 0.0,
        digest_id=str(res.digest_id) if res.digest_id else None,
        error=res.error,
    )


class PipelineStatusResult(BaseModel):
    running: bool
    cancel_requested: bool


@router.get(
    "/status",
    response_model=PipelineStatusResult,
    summary="Check whether a pipeline run is currently in progress.",
)
def pipeline_status() -> PipelineStatusResult:
    return PipelineStatusResult(
        running=capline.is_running(),
        cancel_requested=capline.is_cancel_requested(),
    )


class CancelResult(BaseModel):
    ok: bool
    message: str


@router.post(
    "/cancel",
    response_model=CancelResult,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Request early termination of the running pipeline. "
        "Collection stops; import → rank → digest still run on whatever was collected."
    ),
)
def cancel_pipeline() -> CancelResult:
    if not capline.is_running():
        return CancelResult(ok=False, message="no pipeline is currently running")
    capline.request_cancel()
    return CancelResult(ok=True, message="cancel requested — pipeline will finish after current source")
