"""Application job tracks — `/applications/job-tracks/*` (Phase E1).

User-scoped workflow on **canonical** `jobs` rows. Does not replace `GET /jobs`
(listing pipeline jobs); this is the CRM-style overlay (stages, notes) migrated
from Jobr's separate `jobs` workflow concept.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..schemas.application_job_track import (
    ApplicationJobTrackCreate,
    ApplicationJobTrackListResponse,
    ApplicationJobTrackOut,
    ApplicationJobTrackRescoreRequest,
    ApplicationJobTrackRescoreResponse,
    ApplicationJobTrackUpdate,
)
from ..services import application_job_tracks as tracks_svc
from ..services import profiles as profiles_svc
from ..services import ranker

from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter(prefix="/applications/job-tracks", tags=["application-job-tracks"])


def _out(track) -> ApplicationJobTrackOut:
    return ApplicationJobTrackOut(**tracks_svc.track_to_payload(track))


@router.get("", response_model=ApplicationJobTrackListResponse)
def list_tracks(
    db: DbSession,
    tenant_id: TenantUserId,
    stage: str | None = Query(None, description="Filter by current_stage (exact, normalized)."),
) -> ApplicationJobTrackListResponse:
    rows = tracks_svc.list_tracks(db, user_id=tenant_id, stage=stage)
    items = [_out(t) for t in rows]
    return ApplicationJobTrackListResponse(total=len(items), items=items)


@router.post(
    "",
    response_model=ApplicationJobTrackOut,
    status_code=status.HTTP_201_CREATED,
)
def create_track(
    payload: ApplicationJobTrackCreate,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationJobTrackOut:
    try:
        row = tracks_svc.create_track(
            db,
            user_id=tenant_id,
            canonical_job_id=payload.canonical_job_id,
            current_stage=payload.current_stage,
            notes=payload.notes,
            application_outcome=payload.application_outcome,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="canonical job not found") from None
    except tracks_svc.DuplicateTrackError as dup:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "track_already_exists",
                "existing_id": str(dup.existing.id),
            },
        ) from dup
    return _out(row)


@router.get("/{track_id}", response_model=ApplicationJobTrackOut)
def get_track(
    track_id: uuid.UUID,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationJobTrackOut:
    row = tracks_svc.get_track(db, track_id, user_id=tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="track not found")
    return _out(row)


@router.patch("/{track_id}", response_model=ApplicationJobTrackOut)
def patch_track(
    track_id: uuid.UUID,
    payload: ApplicationJobTrackUpdate,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationJobTrackOut:
    raw = payload.model_dump(exclude_unset=True)
    row = tracks_svc.update_track(
        db,
        track_id,
        user_id=tenant_id,
        patch=raw,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="track not found")
    return _out(row)


@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(
    track_id: uuid.UUID,
    db: DbSession,
    tenant_id: TenantUserId,
) -> None:
    ok = tracks_svc.delete_track(db, track_id, user_id=tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="track not found")


@router.post(
    "/{track_id}/rescore",
    response_model=ApplicationJobTrackRescoreResponse,
    dependencies=[Depends(require_admin_token)],
    summary="Run ranker.rescore_one on the linked canonical job.",
)
def rescore_tracked_job(
    track_id: uuid.UUID,
    payload: ApplicationJobTrackRescoreRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationJobTrackRescoreResponse:
    row = tracks_svc.get_track(db, track_id, user_id=tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="track not found")
    profile = profiles_svc.get_effective(db, payload.profile_slug, uid=tenant_id)
    result = ranker.rescore_one(db, row.canonical_job_id, profile=profile)
    if result is None:
        raise HTTPException(status_code=404, detail="canonical job not found")
    return ApplicationJobTrackRescoreResponse(
        bucket=result.bucket,
        ranking_score=str(result.ranking_score),
        quality_score=str(result.quality_score),
        rationale=(result.rationale or ""),
        hidden_gem=bool(result.hidden_gem),
    )
