"""Unified application-job intake — `POST /applications/jobs/intake` (Phase E1+).

Bridges Jobr-style `POST /jobs/intake` (URL or pasted body) onto the Atlas
canonical pipeline (`manual_job_page` RawJobEvent → importer).

Registered before `application_packages` so `/jobs/intake` is not mistaken for `{job_id}`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..models.ingestion_source import IngestionSource
from ..schemas.application_job_intake import (
    ApplicationJobIntakeRequest,
    ApplicationJobIntakeResponse,
)
from ..services import application_job_tracks as tracks_svc
from ..services import manual_job_url as manual_job_svc

from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter(prefix="/applications", tags=["applications"])


def _maybe_track(
    db: DbSession,
    *,
    tenant_id: uuid.UUID,
    canonical_job_id: uuid.UUID | None,
    create: bool,
    stage: str,
    notes: str | None,
) -> tuple[uuid.UUID | None, bool]:
    if not create or canonical_job_id is None:
        return None, False
    try:
        row = tracks_svc.create_track(
            db,
            user_id=tenant_id,
            canonical_job_id=canonical_job_id,
            current_stage=stage,
            notes=notes,
        )
        return row.id, False
    except LookupError:
        return None, False
    except tracks_svc.DuplicateTrackError as dup:
        return dup.existing.id, True


@router.post(
    "/jobs/intake",
    response_model=ApplicationJobIntakeResponse,
    summary="Unified intake — URL fetch or pasted text → canonical pipeline.",
    dependencies=[Depends(require_admin_token)],
)
def application_job_intake(
    payload: ApplicationJobIntakeRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationJobIntakeResponse:
    if payload.ingestion_source_id is not None:
        sr = db.get(IngestionSource, payload.ingestion_source_id)
        if sr is None:
            raise HTTPException(status_code=404, detail="ingestion_source not found")
        if sr.user_id != tenant_id:
            raise HTTPException(status_code=403, detail="ingestion_source not owned by tenant")

    if payload.url is not None:
        url_str = str(payload.url).strip()
        result = manual_job_svc.ingest_manual_job_url(
            db,
            page_url=url_str,
            title_override=payload.title_override,
            company_override=payload.company_override,
            ingest_source_id=payload.ingestion_source_id,
            tenant_user_id=tenant_id,
            then_process=payload.then_process,
            then_rescore=payload.then_rescore,
            profile_slug=payload.profile_slug,
            profile_user_id=tenant_id,
        )
    else:
        text = (payload.manual_text or "").strip()
        assert text  # guarded by pydantic validator
        result = manual_job_svc.ingest_pasted_manual_job(
            db,
            manual_text=text,
            source_label=payload.source_name,
            title_override=payload.title_override,
            company_override=payload.company_override,
            ingest_source_id=payload.ingestion_source_id,
            tenant_user_id=tenant_id,
            then_process=payload.then_process,
            then_rescore=payload.then_rescore,
            profile_slug=payload.profile_slug,
            profile_user_id=tenant_id,
        )

    track_id, existed = _maybe_track(
        db,
        tenant_id=tenant_id,
        canonical_job_id=result.job_id,
        create=payload.create_application_track,
        stage=payload.track_stage,
        notes=payload.track_notes,
    )
    return ApplicationJobIntakeResponse(
        ingestion_run_id=result.ingestion_run_id,
        raw_event_id=result.raw_event_id,
        fetch_status=result.fetch_status,
        parse_status=result.parse_status,
        job_id=result.job_id,
        application_track_id=track_id,
        track_was_existing=existed,
    )
