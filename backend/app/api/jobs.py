"""Canonical job endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from ..models.job import Job
from ..models.job_score import JobScore
from ..models.job_source_sighting import JobSourceSighting
from ..models.pipeline_event import PipelineEvent
from ..models.raw_job_event import RawJobEvent
from ..schemas.feedback import (
    FeedbackJobSummary,
    FeedbackListResponse,
    FeedbackOut,
    FeedbackRecordRequest,
)
from ..schemas.job import (
    DuplicateReviewOut,
    JobDetail,
    JobListResponse,
    JobOut,
    ReviewCandidateView,
    ReviewDetail,
    ReviewResolveRequest,
    ReviewResolveResponse,
    SetPrimarySourceRequest,
)
from ..services import feedback as feedback_svc
from ..services import profiles as profiles_svc
from ..services import qualification as qualification_svc
from ..services import review as review_svc
from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter()

_QUAL_PREFETCH_MULT = 25
_QUAL_PREFETCH_MIN = 200
_QUAL_PREFETCH_CAP = 5000


def _jobs_rows_to_job_out_list(
    db: DbSession,
    rows_orm: list[Job],
    *,
    profile,
    profile_scores_joined: bool,
    qualifies_map: Optional[dict[uuid.UUID, bool]],
) -> list[JobOut]:
    if not rows_orm:
        return []

    def _attach_qual(o: JobOut, job_id: uuid.UUID) -> JobOut:
        if qualifies_map is not None and job_id in qualifies_map:
            return o.model_copy(update={"qualifies": qualifies_map[job_id]})
        return o

    items: list[JobOut] = []
    if profile_scores_joined and profile:
        id_list = [r.id for r in rows_orm]
        overlay_stmt = (
            select(
                JobScore.job_id,
                JobScore.score,
                JobScore.bucket,
                JobScore.rationale,
            )
            .distinct(JobScore.job_id)
            .where(
                JobScore.profile_id == profile.id,
                JobScore.job_id.in_(id_list),
            )
            .order_by(JobScore.job_id, JobScore.created_at.desc())
        )
        overlay = {
            row[0]: (row[1], row[2]) for row in db.execute(overlay_stmt).all()
        }
        for r in rows_orm:
            out = JobOut.model_validate(r)
            if r.id in overlay:
                score, _bucket = overlay[r.id]
                out.ranking_score = score
            items.append(_attach_qual(out, r.id))
    else:
        for r in rows_orm:
            out = JobOut.model_validate(r)
            items.append(_attach_qual(out, r.id))
    return items


@router.get(
    "",
    response_model=JobListResponse,
    summary="List canonical jobs.",
)
def list_jobs(
    db: DbSession,
    user_id: TenantUserId,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = True,
    provider: Optional[str] = None,
    company: Optional[str] = Query(
        None, description="Partial match against company_name (case-insensitive)."
    ),
    min_score: Optional[float] = None,
    order: str = Query("last_seen", pattern="^(last_seen|first_seen|ranking|quality)$"),
    profile_slug: Optional[str] = Query(
        None,
        description=(
            "If set, overlay per-profile ranking/quality scores on each "
            "returned job (latest job_scores row for that profile). "
            "Filtering on min_score and ordering by ranking/quality then "
            "use the profile score."
        ),
    ),
    first_seen_after: Optional[datetime] = Query(
        None,
        description="Jobs with first_seen_at >= this time (UTC if naive).",
    ),
    q: Optional[str] = Query(
        None,
        description="Full-text search against title and company_name (case-insensitive).",
    ),
    remote_type: Optional[str] = Query(
        None,
        description="Filter by remote_type value, e.g. 'remote', 'hybrid', 'onsite'. Use 'null' to match jobs where remote_type IS NULL.",
    ),
    apply_qualification: bool = Query(
        False,
        description="Restrict to rows that pass the tenant's saved qualification rules.",
    ),
    include_qualification: bool = Query(
        False,
        description='Add "qualifies" on each item using saved rules without filtering.',
    ),
) -> JobListResponse:
    if apply_qualification and offset != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="offset must be 0 when apply_qualification is true.",
        )
    profile_score_col = None
    profile_bucket_col = None
    profile = None

    if profile_slug:
        profile = profiles_svc.get_by_slug(db, profile_slug)
        if profile is None:
            raise HTTPException(
                status_code=404, detail=f"profile not found: {profile_slug!r}"
            )
        # Default profile shares jobs.ranking_score / quality_score with v1,
        # so we can avoid the subquery for free.
        if not profile.is_default:
            latest_scores = (
                select(
                    JobScore.job_id,
                    JobScore.score.label("profile_score"),
                    JobScore.bucket.label("profile_bucket"),
                )
                .distinct(JobScore.job_id)
                .where(JobScore.profile_id == profile.id)
                .order_by(JobScore.job_id, JobScore.created_at.desc())
                .subquery()
            )
            profile_score_col = latest_scores.c.profile_score
            profile_bucket_col = latest_scores.c.profile_bucket

    base = select(Job)
    count_base = select(func.count(Job.id))

    filters = []
    if active_only:
        filters.append(Job.is_active.is_(True))
    if provider:
        filters.append(Job.provider == provider)
    if company:
        filters.append(Job.company_name.ilike(f"%{company}%"))
    if q:
        pattern = f"%{q}%"
        filters.append(
            or_(Job.title.ilike(pattern), Job.company_name.ilike(pattern))
        )
    if remote_type is not None:
        if remote_type.lower() == "null":
            filters.append(Job.remote_type.is_(None))
        else:
            filters.append(Job.remote_type.ilike(remote_type))
    if first_seen_after is not None:
        fs = first_seen_after
        if fs.tzinfo is None:
            fs = fs.replace(tzinfo=timezone.utc)
        filters.append(Job.first_seen_at >= fs)

    score_expr = profile_score_col if profile_score_col is not None else Job.ranking_score
    if min_score is not None:
        filters.append(score_expr >= min_score)

    if profile_score_col is not None:
        base = base.outerjoin(
            latest_scores, latest_scores.c.job_id == Job.id
        )
        count_base = count_base.outerjoin(
            latest_scores, latest_scores.c.job_id == Job.id
        )

    for f in filters:
        base = base.where(f)
        count_base = count_base.where(f)

    order_col = {
        "last_seen": Job.last_seen_at.desc(),
        "first_seen": Job.first_seen_at.desc(),
        "ranking": score_expr.desc().nulls_last(),
        "quality": (
            profile_score_col.desc().nulls_last()
            if profile_score_col is not None
            else Job.quality_score.desc()
        ),
    }[order]

    fetch_limit = limit
    fetch_offset = offset
    if apply_qualification:
        fetch_limit = min(
            _QUAL_PREFETCH_CAP, max(_QUAL_PREFETCH_MIN, limit * _QUAL_PREFETCH_MULT)
        )
        fetch_offset = 0

    total = db.execute(count_base).scalar_one()
    rows_raw = db.execute(
        base.order_by(order_col).limit(fetch_limit).offset(fetch_offset)
    ).scalars().all()
    rows_orm = list(rows_raw)

    q_pool_scanned = None
    q_excluded = None
    offset_out = offset
    qualifies_map: Optional[dict[uuid.UUID, bool]] = None

    if apply_qualification:
        q_pool_scanned = len(rows_orm)
        qualified_rows, q_excluded = qualification_svc.filter_jobs_by_qualification(
            db,
            user_id=user_id,
            jobs=rows_orm,
            profile_slug=profile_slug,
        )
        total = len(qualified_rows)
        rows_orm = qualified_rows[:limit]
        offset_out = 0
        qualifies_map = {r.id: True for r in rows_orm}
    elif include_qualification:
        qualifies_map = qualification_svc.qualification_pass_map(
            db,
            user_id=user_id,
            jobs=rows_orm,
            profile_slug=profile_slug,
        )

    items = _jobs_rows_to_job_out_list(
        db,
        rows_orm,
        profile=profile,
        profile_scores_joined=profile_score_col is not None,
        qualifies_map=qualifies_map,
    )

    return JobListResponse(
        total=total,
        limit=limit,
        offset=offset_out,
        items=items,
        qualification_pool_scanned=q_pool_scanned,
        qualification_excluded_count=q_excluded,
    )


@router.get(
    "/review/duplicates",
    response_model=list[DuplicateReviewOut],
    dependencies=[Depends(require_admin_token)],
    summary="Raw events waiting for human duplicate review.",
)
def list_duplicate_review(
    db: DbSession,
    limit: int = Query(100, ge=1, le=1000),
) -> list[DuplicateReviewOut]:
    # Pull raw events in needs_review state, latest first.
    stmt = (
        select(RawJobEvent)
        .where(RawJobEvent.parse_status == "needs_review")
        .order_by(RawJobEvent.created_at.desc())
        .limit(limit)
    )
    raws = list(db.execute(stmt).scalars().all())
    if not raws:
        return []

    # Pull the matching pipeline_events to recover candidate ids + reason.
    ev_stmt = (
        select(PipelineEvent)
        .where(
            PipelineEvent.entity_type == "raw_job_event",
            PipelineEvent.event_name == "needs_review",
            PipelineEvent.entity_id.in_([r.id for r in raws]),
        )
    )
    events_by_raw: dict[uuid.UUID, PipelineEvent] = {}
    for e in db.execute(ev_stmt).scalars().all():
        if e.entity_id is not None:
            events_by_raw.setdefault(e.entity_id, e)

    # We need normalized company/title — compute on the fly rather than store.
    from ..services.cleaner_v2 import normalize_raw_event

    out: list[DuplicateReviewOut] = []
    for r in raws:
        cand = normalize_raw_event(r)
        ev = events_by_raw.get(r.id)
        details = ev.details if ev and ev.details else {}
        candidate_ids: list[uuid.UUID] = []
        for s in details.get("candidates", []) or []:
            try:
                candidate_ids.append(uuid.UUID(s))
            except (ValueError, TypeError):
                continue
        out.append(
            DuplicateReviewOut(
                raw_event_id=r.id,
                provider=r.provider,
                source_url=r.source_url,
                normalized_company=cand.normalized_company_name if cand else "",
                normalized_title=cand.normalized_title if cand else "",
                candidate_job_ids=candidate_ids,
                reason=(details.get("reason") or "").strip() or "tier_match",
                created_at=r.created_at,
            )
        )
    return out


@router.get(
    "/review/{raw_event_id}",
    response_model=ReviewDetail,
    dependencies=[Depends(require_admin_token)],
    summary="Fetch a needs_review raw_job_event with its candidate jobs.",
)
def review_detail(raw_event_id: uuid.UUID, db: DbSession) -> ReviewDetail:
    try:
        raw, candidate, jobs, extra = review_svc.get_review_detail(db, raw_event_id)
    except review_svc.ReviewError as e:
        raise HTTPException(status_code=404, detail=str(e))

    incoming = ReviewCandidateView(
        provider=raw.provider,
        source_url=raw.source_url,
        company_name=(candidate.company_name if candidate else None),
        title=(candidate.title if candidate else None),
        location=(candidate.location if candidate else None),
        remote_type=(candidate.remote_type if candidate else None),
        apply_url=(candidate.apply_url if candidate else None),
        employment_type=(candidate.employment_type if candidate else None),
        salary_text=(candidate.salary_text if candidate else None),
        description_clean=(candidate.description_clean if candidate else None),
    )
    return ReviewDetail(
        raw_event_id=raw.id,
        created_at=raw.created_at,
        parse_status=raw.parse_status,
        reason=extra.get("reason") or "",
        tier=extra.get("tier"),
        incoming=incoming,
        candidates=[JobOut.model_validate(j) for j in jobs],
    )


@router.post(
    "/review/{raw_event_id}/resolve",
    response_model=ReviewResolveResponse,
    dependencies=[Depends(require_admin_token)],
    summary="Resolve a needs_review raw event: merge into a job, promote as new, or reject.",
)
def review_resolve(
    raw_event_id: uuid.UUID,
    payload: ReviewResolveRequest,
    db: DbSession,
) -> ReviewResolveResponse:
    try:
        action = review_svc.ReviewAction(payload.action)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"action must be one of: merge, promote, reject (got {payload.action!r})",
        )
    try:
        result = review_svc.resolve(
            db,
            raw_event_id=raw_event_id,
            action=action,
            target_job_id=payload.target_job_id,
            note=payload.note,
            rescore=payload.rescore,
        )
    except review_svc.ReviewError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return ReviewResolveResponse(
        raw_event_id=result.raw_event_id,
        action=result.action,
        job_id=result.job_id,
        rescored=result.rescored,
    )


@router.get(
    "/{job_id}",
    response_model=JobDetail,
    summary="Canonical job detail including sightings and scores.",
)
def get_job(job_id: uuid.UUID, db: DbSession) -> JobDetail:
    stmt = (
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.sightings), selectinload(Job.scores))
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDetail.model_validate(job)


@router.post(
    "/{job_id}/set-primary-source",
    response_model=JobDetail,
    dependencies=[Depends(require_admin_token)],
    summary="Mark one sighting as the primary apply link for a job.",
)
def set_primary_source(
    job_id: uuid.UUID,
    payload: SetPrimarySourceRequest,
    db: DbSession,
) -> JobDetail:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    target = db.get(JobSourceSighting, payload.sighting_id)
    if target is None or target.job_id != job.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sighting does not belong to this job",
        )

    # Clear previous primary, set new one.
    sightings = (
        db.execute(
            select(JobSourceSighting).where(JobSourceSighting.job_id == job.id)
        )
        .scalars()
        .all()
    )
    for s in sightings:
        s.is_primary = (s.id == target.id)

    if target.apply_url:
        job.apply_url = target.apply_url
    db.commit()

    # Return fresh detail.
    return get_job(job.id, db)


# ---------------------------------------------------------------------------
# Feedback (Sprint I)
# ---------------------------------------------------------------------------

def _feedback_out(fb, db) -> FeedbackOut:
    """Attach profile_slug for the UI. Cheap lookup; cached via SA identity map."""
    slug = None
    if fb.profile_id is not None:
        p = profiles_svc.get_by_id(db, fb.profile_id)
        slug = p.slug if p else None
    return FeedbackOut(
        id=fb.id,
        job_id=fb.job_id,
        profile_id=fb.profile_id,
        profile_slug=slug,
        action=fb.action,
        source=fb.source,
        note=fb.note,
        created_at=fb.created_at,
    )


@router.post(
    "/{job_id}/feedback",
    response_model=FeedbackOut,
    dependencies=[Depends(require_admin_token)],
    status_code=201,
    summary="Record one feedback event on a job.",
)
def record_feedback(
    job_id: uuid.UUID,
    payload: FeedbackRecordRequest,
    db: DbSession,
) -> FeedbackOut:
    try:
        result = feedback_svc.record(
            db,
            job_id=job_id,
            action=payload.action,
            profile_slug=payload.profile_slug,
            source=payload.source,
            note=payload.note,
        )
    except feedback_svc.FeedbackError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _feedback_out(result.feedback, db)


@router.get(
    "/{job_id}/feedback",
    response_model=FeedbackListResponse,
    summary="List feedback events recorded on a job.",
)
def list_job_feedback(
    job_id: uuid.UUID,
    db: DbSession,
    profile_slug: Optional[str] = Query(
        default=None,
        description="Filter to one profile. Omit for all profiles.",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> FeedbackListResponse:
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")

    profile_id = None
    if profile_slug:
        p = profiles_svc.get_by_slug(db, profile_slug)
        if p is None:
            raise HTTPException(
                status_code=404, detail=f"profile not found: {profile_slug!r}"
            )
        profile_id = p.id

    total, items = feedback_svc.list_feedback(
        db, job_id=job_id, profile_id=profile_id, limit=limit, offset=offset
    )
    return FeedbackListResponse(
        total=total, items=[_feedback_out(fb, db) for fb in items]
    )


@router.get(
    "/{job_id}/feedback/summary",
    response_model=FeedbackJobSummary,
    summary="Compact feedback rollup for a job (latest action + counts).",
)
def job_feedback_summary(
    job_id: uuid.UUID,
    db: DbSession,
    profile_slug: Optional[str] = Query(default=None),
) -> FeedbackJobSummary:
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")

    profile_id = None
    if profile_slug:
        p = profiles_svc.get_by_slug(db, profile_slug)
        if p is None:
            raise HTTPException(
                status_code=404, detail=f"profile not found: {profile_slug!r}"
            )
        profile_id = p.id

    return FeedbackJobSummary.model_validate(
        feedback_svc.summary_for_job(db, job_id=job_id, profile_id=profile_id)
    )
