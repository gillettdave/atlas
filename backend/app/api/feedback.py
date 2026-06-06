"""Global feedback endpoints (Sprint I).

Per-job POST / GET live under `/jobs/{id}/feedback` (see api/jobs.py).
This router exposes cross-job views used by the admin UI log page.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..models.job_feedback import FEEDBACK_ACTIONS
from ..schemas.feedback import FeedbackListResponse, FeedbackOut
from ..services import feedback as feedback_svc
from ..services import profiles as profiles_svc
from .deps import DbSession

router = APIRouter()


def _out(fb, db) -> FeedbackOut:
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


@router.get(
    "",
    response_model=FeedbackListResponse,
    summary="Recent feedback events across all jobs/profiles.",
)
def list_feedback(
    db: DbSession,
    profile_slug: Optional[str] = Query(default=None),
    action: Optional[str] = Query(
        default=None,
        description=f"Filter to one action: {', '.join(FEEDBACK_ACTIONS)}",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> FeedbackListResponse:
    profile_id = None
    if profile_slug:
        p = profiles_svc.get_by_slug(db, profile_slug)
        if p is None:
            raise HTTPException(
                status_code=404, detail=f"profile not found: {profile_slug!r}"
            )
        profile_id = p.id

    if action and action not in FEEDBACK_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"action must be one of {FEEDBACK_ACTIONS}",
        )

    total, items = feedback_svc.list_feedback(
        db,
        profile_id=profile_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return FeedbackListResponse(
        total=total, items=[_out(fb, db) for fb in items]
    )
