"""Email intake API (Gmail IMAP) — Atlas port."""

from __future__ import annotations

import uuid as uuid_module
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field

from ..db import SessionLocal
from ..services import email_intake_svc as email_svc

from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter(prefix="/email", tags=["email-intake"])


class EmailSourceRequest(BaseModel):
    provider: str = Field(default="gmail_imap", max_length=32)
    label_name: str = Field(..., min_length=1, max_length=256)
    source_name: Optional[str] = Field(default=None, max_length=256)
    enabled: bool = True
    cadence_minutes: int = Field(default=60, ge=5, le=1440)


def _task_sync(source_id: uuid_module.UUID, user_id: uuid_module.UUID) -> None:
    db = SessionLocal()
    try:
        email_svc.run_email_sync(db, source_id=source_id, user_id=user_id)
    finally:
        db.close()


@router.post("/sources", dependencies=[Depends(require_admin_token)])
def email_upsert_source(
    payload: EmailSourceRequest,
    db: DbSession,
    tenant_id: TenantUserId,
):
    row = email_svc.upsert_email_source(
        db,
        user_id=tenant_id,
        provider=payload.provider,
        label_name=payload.label_name,
        source_name=payload.source_name,
        enabled=payload.enabled,
        cadence_minutes=payload.cadence_minutes,
    )
    return {
        "id": str(row.id),
        "provider": row.provider,
        "label_name": row.label_name,
        "enabled": row.enabled,
        "cadence_minutes": row.cadence_minutes,
        "next_sync_at": row.next_sync_at.isoformat() if row.next_sync_at else None,
    }


@router.get("/sources")
def email_list_sources(db: DbSession, tenant_id: TenantUserId, limit: int = Query(100, ge=1, le=500)):
    rows = email_svc.list_email_sources(db, user_id=tenant_id, limit=limit)
    items = []
    for r in rows:
        items.append(
            {
                "id": str(r.id),
                "provider": r.provider,
                "label_name": r.label_name,
                "enabled": r.enabled,
                "cadence_minutes": r.cadence_minutes,
                "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
                "next_sync_at": r.next_sync_at.isoformat() if r.next_sync_at else None,
                "last_error": r.last_error,
            }
        )
    return {"total": len(items), "items": items}


@router.get("/events")
def email_list_events(
    db: DbSession,
    tenant_id: TenantUserId,
    source_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    sid = None
    if source_id:
        try:
            sid = uuid_module.UUID(source_id)
        except ValueError:
            sid = None
    rows = email_svc.list_email_events(db, user_id=tenant_id, source_id=sid, limit=limit)
    items = []
    for ev in rows:
        items.append(
            {
                "id": str(ev.id),
                "email_sync_source_id": str(ev.email_sync_source_id),
                "status": ev.status,
                "detail": ev.detail,
                "canonical_job_id": str(ev.canonical_job_id) if ev.canonical_job_id else None,
                "created_at": ev.created_at.isoformat(),
            }
        )
    return {"total": len(items), "items": items}


@router.post("/sources/{source_id}/sync-now", dependencies=[Depends(require_admin_token)])
def email_sync_now(
    source_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: TenantUserId,
):
    try:
        sid = uuid_module.UUID(source_id)
    except ValueError:
        return {"ok": False, "detail": "bad uuid"}
    background_tasks.add_task(_task_sync, sid, tenant_id)
    return {"ok": True, "source_id": str(sid), "queued": True}


def _task_run_explicit(user_id: uuid_module.UUID, ids: list[uuid_module.UUID]) -> None:
    db = SessionLocal()
    try:
        for eid in ids:
            email_svc.run_email_sync(db, source_id=eid, user_id=user_id)
    finally:
        db.close()


@router.post("/run-due", dependencies=[Depends(require_admin_token)])
def email_run_due(
    background_tasks: BackgroundTasks,
    tenant_id: TenantUserId,
    limit: int = Query(20, ge=1, le=200),
):
    db = SessionLocal()
    try:
        due = email_svc.list_due_email_source_ids(db, user_id=tenant_id, limit=limit)
    finally:
        db.close()
    background_tasks.add_task(_task_run_explicit, tenant_id, due)
    return {"queued": True, "due_source_ids": [str(i) for i in due], "due_count": len(due)}
