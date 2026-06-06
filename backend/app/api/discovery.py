"""Discovery API — compat with Jobr ``/discovery/*`` (PostgreSQL-backed)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field

from ..db import SessionLocal
from ..services import job_discovery as disc_svc

from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter(prefix="/discovery", tags=["discovery"])


def _task_run_discovery(
    *,
    seed_id: uuid.UUID,
    user_id: uuid.UUID,
    profile_slug: str | None,
) -> None:
    db = SessionLocal()
    try:
        disc_svc.run_seed_discovery(db, seed_id=seed_id, user_id=user_id, profile_slug=profile_slug)
    finally:
        db.close()


class DiscoveryEnqueueRequest(BaseModel):
    seed_urls: list[str] = Field(..., min_length=1)
    source_name: Optional[str] = None
    cadence_hours: int = Field(default=24, ge=1, le=336)
    max_depth: int = Field(default=1, ge=0, le=3)
    max_pages: int = Field(default=15, ge=1, le=100)
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    mode: str = Field(default="balanced")
    profile_slug: Optional[str] = Field(
        default=None,
        description="Ranker profile for downstream ingest overlays.",
    )


@router.post("/seeds", dependencies=[Depends(require_admin_token)])
def enqueue_seeds(
    payload: DiscoveryEnqueueRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    tenant_id: TenantUserId,
):
    seeds = disc_svc.create_seeds_from_payload(
        db,
        user_id=tenant_id,
        seed_urls=payload.seed_urls,
        source_name=payload.source_name,
        cadence_hours=payload.cadence_hours,
        max_depth=payload.max_depth,
        max_pages=payload.max_pages,
        include_domains=payload.include_domains,
        exclude_domains=payload.exclude_domains,
        mode=payload.mode,
    )
    out = []
    for s in seeds:
        background_tasks.add_task(
            _task_run_discovery,
            seed_id=s.id,
            user_id=tenant_id,
            profile_slug=payload.profile_slug,
        )
        out.append(
            {
                "seed_id": str(s.id),
                "seed_url": s.seed_url,
                "status": s.status,
                "cadence_hours": s.cadence_hours,
                "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
                "profile_slug": payload.profile_slug,
            }
        )
    return out


@router.get("/seeds")
def list_discovery_seeds(
    db: DbSession,
    tenant_id: TenantUserId,
    limit: int = Query(50, ge=1, le=200),
):
    rows = disc_svc.list_seeds(db, user_id=tenant_id, limit=limit)
    items = []
    for s in rows:
        items.append(
            {
                "id": str(s.id),
                "seed_url": s.seed_url,
                "source_name": s.source_name,
                "status": s.status,
                "enabled": s.enabled,
                "cadence_hours": s.cadence_hours,
                "max_depth": s.max_depth,
                "max_pages": s.max_pages,
                "discovered_count": s.discovered_count,
                "last_error": s.last_error,
                "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
                "created_at": s.created_at.isoformat(),
            }
        )
    return {"total": len(items), "items": items}


@router.post("/seeds/{seed_id}/pause", dependencies=[Depends(require_admin_token)])
def pause_discovery_seed(seed_id: uuid.UUID, db: DbSession, tenant_id: TenantUserId):
    s = disc_svc.pause_seed(db, user_id=tenant_id, seed_id=seed_id)
    if not s:
        return {"ok": False, "detail": "not_found"}
    return {"ok": True, "status": s.status}


@router.post("/seeds/{seed_id}/cancel", dependencies=[Depends(require_admin_token)])
def cancel_discovery_seed(seed_id: uuid.UUID, db: DbSession, tenant_id: TenantUserId):
    s = disc_svc.cancel_seed(db, user_id=tenant_id, seed_id=seed_id)
    if not s:
        return {"ok": False, "detail": "not_found"}
    return {"ok": True, "status": s.status}


@router.get("/queue")
def discovery_queue(
    db: DbSession,
    tenant_id: TenantUserId,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    return disc_svc.list_queue_rows(db, user_id=tenant_id, limit=limit, status_filter=status)


def _task_run_due(user_id: uuid.UUID, profile_slug: str | None, seed_ids: list[uuid.UUID]) -> None:
    db = SessionLocal()
    try:
        for sid in seed_ids:
            disc_svc.run_seed_discovery(db, seed_id=sid, user_id=user_id, profile_slug=profile_slug)
    finally:
        db.close()


@router.post("/run-due", dependencies=[Depends(require_admin_token)])
def discovery_run_due(
    background_tasks: BackgroundTasks,
    tenant_id: TenantUserId,
    limit: int = Query(20, ge=1, le=100),
    profile_slug: Optional[str] = None,
):
    db = SessionLocal()
    try:
        due = disc_svc.list_due_seed_ids(db, user_id=tenant_id, limit=limit)
    finally:
        db.close()
    background_tasks.add_task(_task_run_due, tenant_id, profile_slug, due)
    return {"started_seed_ids": [str(i) for i in due], "started_count": len(due), "queued": True}


@router.post("/cancel-all", dependencies=[Depends(require_admin_token)])
def cancel_all_discovery(db: DbSession, tenant_id: TenantUserId):
    return disc_svc.cancel_all_running(db, user_id=tenant_id)
