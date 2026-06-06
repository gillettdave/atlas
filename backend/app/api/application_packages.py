"""Application packages — `/applications/jobs/{job_id}/packages/*` (Phase D slice)."""
from __future__ import annotations


import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..models.application_package import ApplicationPackage
from ..models.job import Job
from ..schemas.application_packages import (
    ApplicationPackageGenerateRequest,
    ApplicationPackageListResponse,
    ApplicationPackageOut,
    ApplicationPackageSaveRequest,
)
from ..services import application_packages as packages_svc

from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter(prefix="/applications", tags=["applications"])


def _get_job(db: DbSession, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post(
    "/jobs/{job_id}/packages/generate",
    response_model=ApplicationPackageOut,
    status_code=201,
    dependencies=[Depends(require_admin_token)],
    summary="Template-generate résumé/CL/strategy drafts from canonical job + career memory + ranker score.",
)
def generate_package_for_job(
    job_id: uuid.UUID,
    payload: ApplicationPackageGenerateRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationPackage:
    job = _get_job(db, job_id)
    return packages_svc.generate_application_package(
        db,
        job,
        user_id=tenant_id,
        tone=payload.tone,
        emphasis=payload.emphasis,
        generation_source=payload.generation_source,
    )


@router.get(
    "/jobs/{job_id}/packages",
    response_model=ApplicationPackageListResponse,
    summary="List package versions saved for this job (tenant scope).",
)
def list_packages(
    job_id: uuid.UUID,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationPackageListResponse:
    _ = _get_job(db, job_id)
    rows = packages_svc.list_for_job(db, job_id, user_id=tenant_id)
    return ApplicationPackageListResponse(total=len(rows), items=rows)


@router.get(
    "/jobs/{job_id}/packages/{package_id}",
    response_model=ApplicationPackageOut,
    summary="Fetch one package version.",
)
def get_package(
    job_id: uuid.UUID,
    package_id: uuid.UUID,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationPackage:
    pkg = packages_svc.get_one(db, job_id, package_id, user_id=tenant_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="package not found")
    return pkg


@router.post(
    "/jobs/{job_id}/packages/save-version",
    response_model=ApplicationPackageOut,
    status_code=201,
    dependencies=[Depends(require_admin_token)],
    summary="Persist a new version from edited markdown (no regeneration).",
)
def save_package_version(
    job_id: uuid.UUID,
    payload: ApplicationPackageSaveRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> ApplicationPackage:
    _ = _get_job(db, job_id)
    return packages_svc.save_edited_version(
        db,
        job_id,
        user_id=tenant_id,
        resume_markdown=payload.resume_markdown,
        cover_letter_markdown=payload.cover_letter_markdown,
        strategy_notes=payload.strategy_notes,
        evidence_used_summary=payload.evidence_used_summary,
    )


@router.get(
    "/jobs/{job_id}/packages/{package_id}/export/docx-zip",
    summary="ZIP of resume, cover-letter, and strategy Word files (from stored markdown).",
    response_class=Response,
)
def export_package_docx_zip(
    job_id: uuid.UUID,
    package_id: uuid.UUID,
    db: DbSession,
    tenant_id: TenantUserId,
) -> Response:
    """Tenant-scoped; no admin gate (same visibility as GET package row)."""
    _ = _get_job(db, job_id)
    pkg = packages_svc.get_one(db, job_id, package_id, user_id=tenant_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="package not found")

    blob, fname = packages_svc.export_docx_zip_bytes(pkg)
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


_DOCX_MEDIA = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document"
)


@router.get(
    "/jobs/{job_id}/packages/{package_id}/export/docx/{part_slug}",
    summary="Single Word file (résumé, cover letter, or strategy) from stored markdown.",
    response_class=Response,
)
def export_package_docx_single(
    job_id: uuid.UUID,
    package_id: uuid.UUID,
    part_slug: str,
    db: DbSession,
    tenant_id: TenantUserId,
) -> Response:
    """Path segment: ``resume`` | ``cover-letter`` | ``strategy``."""
    slug_map = {
        "resume": "resume",
        "cover-letter": "cover_letter",
        "strategy": "strategy",
    }
    if part_slug not in slug_map:
        raise HTTPException(
            status_code=404,
            detail="invalid part (use resume, cover-letter, or strategy)",
        )
    _ = _get_job(db, job_id)
    pkg = packages_svc.get_one(db, job_id, package_id, user_id=tenant_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="package not found")

    blob, fname = packages_svc.export_docx_single_bytes(pkg, slug_map[part_slug])
    return Response(
        content=blob,
        media_type=_DOCX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
