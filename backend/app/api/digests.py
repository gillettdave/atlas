"""Digest endpoints.

- GET  /digests/preview          on-the-fly ranking, not persisted
- POST /digests/generate         builds + persists a Digest + DigestItems
- GET  /digests                  list recent digests (summary + item count)
- GET  /digests/{digest_id}      full digest with items and jobs
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response

_log = logging.getLogger("atlas.api.digests")
from sqlalchemy import select

from ..models.job import Job
from ..schemas.digest import (
    DigestDetail,
    DigestDetailItem,
    DigestGenerateRequest,
    DigestListResponse,
    DigestPreviewItem,
    DigestPreviewResponse,
    DigestSendRequest,
    DigestSendResponse,
    DigestStatsOut,
    DigestSummary,
)
from ..schemas.job import JobOut
from ..services import digest_builder, digest_delivery, feed_alerts
from ..services.digest_builder import DigestConfig
from ..db import SessionLocal
from .deps import DbSession, require_admin_token

router = APIRouter()


# ---------------------------------------------------------------------------
# Preview (live, not persisted)
# ---------------------------------------------------------------------------

@router.get(
    "/preview",
    response_model=DigestPreviewResponse,
    summary="Preview the next digest on the fly (does not persist).",
)
def preview(
    db: DbSession,
    fresh_hours: int = Query(48, ge=1, le=168),
    fresh_limit: int = Query(15, ge=1, le=100),
    gem_limit: int = Query(10, ge=1, le=100),
) -> DigestPreviewResponse:
    now = datetime.now(timezone.utc)
    fresh_cutoff = now - timedelta(hours=fresh_hours)

    fresh_stmt = (
        select(Job)
        .where(Job.is_active.is_(True), Job.first_seen_at >= fresh_cutoff)
        .order_by(Job.ranking_score.desc(), Job.first_seen_at.desc())
        .limit(fresh_limit)
    )
    gem_stmt = (
        select(Job)
        .where(Job.is_active.is_(True), Job.first_seen_at < fresh_cutoff)
        .order_by(Job.ranking_score.desc(), Job.last_seen_at.desc())
        .limit(gem_limit)
    )

    fresh_rows = db.execute(fresh_stmt).scalars().all()
    gem_rows = db.execute(gem_stmt).scalars().all()

    fresh_items = [
        DigestPreviewItem(
            job=JobOut.model_validate(j),
            lane="fresh",
            reason="recent_high_score",
            rank_position=i + 1,
        )
        for i, j in enumerate(fresh_rows)
    ]
    gem_items = [
        DigestPreviewItem(
            job=JobOut.model_validate(j),
            lane="hidden_gem",
            reason="older_but_strong",
            rank_position=i + 1,
        )
        for i, j in enumerate(gem_rows)
    ]
    return DigestPreviewResponse(
        generated_at=now,
        fresh=fresh_items,
        hidden_gems=gem_items,
    )


# ---------------------------------------------------------------------------
# Persisted build
# ---------------------------------------------------------------------------

def _built_to_detail(built: digest_builder.BuiltDigest) -> DigestDetail:
    fresh = [
        DigestDetailItem(
            job=JobOut.model_validate(i.job),
            lane=i.lane,
            reason=i.reason,
            rank_position=i.rank_position,
        )
        for i in built.fresh_items
    ]
    gems = [
        DigestDetailItem(
            job=JobOut.model_validate(i.job),
            lane=i.lane,
            reason=i.reason,
            rank_position=i.rank_position,
        )
        for i in built.gem_items
    ]
    return DigestDetail(
        id=built.digest.id,
        generated_at=built.digest.generated_at,
        digest_type=built.digest.digest_type,
        notes=built.digest.notes,
        fresh=fresh,
        hidden_gems=gems,
        stats=DigestStatsOut(
            fresh_selected=built.stats.fresh_selected,
            gem_selected=built.stats.gem_selected,
            fresh_candidates=built.stats.fresh_candidates,
            gem_candidates=built.stats.gem_candidates,
            dropped_by_cap=built.stats.dropped_by_cap,
            excluded_by_feedback=built.stats.excluded_by_feedback,
            excluded_by_qualification=built.stats.excluded_by_qualification,
        ),
    )


@router.post(
    "/generate",
    response_model=DigestDetail,
    dependencies=[Depends(require_admin_token)],
    summary="Build and persist a Digest + DigestItems using the current ranker state.",
)
def generate(payload: DigestGenerateRequest, db: DbSession) -> DigestDetail:
    cfg = DigestConfig(
        digest_type=payload.digest_type,
        fresh_hours=payload.fresh_hours,
        fresh_limit=payload.fresh_limit,
        gem_limit=payload.gem_limit,
        per_company_cap=payload.per_company_cap,
        profile_slug=payload.profile_slug,
        apply_qualification=payload.apply_qualification,
        use_llm_qualification=payload.use_llm_qualification,
        min_ranking_score=Decimal(str(payload.min_ranking_score)),
        gem_min_score=Decimal(str(payload.gem_min_score)),
        notes=payload.notes,
    )
    built = digest_builder.build_digest(db, cfg)
    feed_alerts.maybe_digest_top_jobs_alert(db, built, source="digest_generate_admin")
    db.commit()
    return _built_to_detail(built)


def _bg_generate_digest(payload_dict: dict) -> None:
    db = SessionLocal()
    try:
        cfg = DigestConfig(
            digest_type=payload_dict.get("digest_type", "daily"),
            fresh_hours=payload_dict.get("fresh_hours", 48),
            fresh_limit=payload_dict.get("fresh_limit", 15),
            gem_limit=payload_dict.get("gem_limit", 10),
            per_company_cap=payload_dict.get("per_company_cap", 2),
            profile_slug=payload_dict.get("profile_slug"),
            apply_qualification=payload_dict.get("apply_qualification", True),
            use_llm_qualification=payload_dict.get("use_llm_qualification", False),
            min_ranking_score=Decimal(str(payload_dict.get("min_ranking_score", 0))),
            gem_min_score=Decimal(str(payload_dict.get("gem_min_score", 0))),
            notes=payload_dict.get("notes"),
        )
        built = digest_builder.build_digest(db, cfg)
        feed_alerts.maybe_digest_top_jobs_alert(db, built, source="digest_generate_async")
        db.commit()
        _log.info("bg_generate_digest complete")
    except Exception as exc:
        _log.error("bg_generate_digest failed: %s", exc)
    finally:
        db.close()


@router.post(
    "/generate-async",
    status_code=202,
    dependencies=[Depends(require_admin_token)],
    summary="Queue a digest build in the background — returns 202 immediately.",
)
def generate_async(
    payload: DigestGenerateRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    background_tasks.add_task(_bg_generate_digest, payload.model_dump())
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=DigestListResponse,
    summary="List recent digests (newest first).",
)
def list_digests(
    db: DbSession,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DigestListResponse:
    rows, total = digest_builder.list_digests(db, limit=limit, offset=offset)
    items = [
        DigestSummary(
            id=d.id,
            generated_at=d.generated_at,
            digest_type=d.digest_type,
            notes=d.notes,
            item_count=n,
        )
        for d, n in rows
    ]
    return DigestListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{digest_id}/export.csv",
    dependencies=[Depends(require_admin_token)],
    summary="Download a digest as a CSV file.",
)
def export_csv(digest_id: uuid.UUID, db: DbSession) -> Response:
    try:
        data, filename = digest_delivery.export_csv(db, digest_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/{digest_id}/send",
    response_model=DigestSendResponse,
    dependencies=[Depends(require_admin_token)],
    summary="Send a digest to Slack (webhook) or email (SMTP).",
)
def send_digest(
    digest_id: uuid.UUID,
    payload: DigestSendRequest,
    db: DbSession,
) -> DigestSendResponse:
    try:
        result = digest_delivery.deliver(
            db,
            digest_id,
            channel=payload.channel,
            webhook_url=payload.webhook_url,
            recipients=payload.recipients,
            include_hidden_gems=payload.include_hidden_gems,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DigestSendResponse(
        digest_id=digest_id,
        channel=result.channel,
        recipient=result.recipient,
        ok=result.ok,
        sent_at=result.sent_at,
        item_count=result.item_count,
        detail=result.detail,
    )


@router.get(
    "/{digest_id}",
    response_model=DigestDetail,
    summary="Get a persisted digest with its items (joined to jobs).",
)
def get_digest(digest_id: uuid.UUID, db: DbSession) -> DigestDetail:
    result = digest_builder.get_digest_with_items(db, digest_id)
    if result is None:
        raise HTTPException(status_code=404, detail="digest not found")

    digest, rows = result
    fresh: list[DigestDetailItem] = []
    gems: list[DigestDetailItem] = []
    for item, job in rows:
        detail = DigestDetailItem(
            job=JobOut.model_validate(job),
            lane=item.lane,
            reason=item.reason,
            rank_position=item.rank_position,
        )
        if item.lane == "hidden_gem":
            gems.append(detail)
        else:
            fresh.append(detail)

    fresh.sort(key=lambda i: i.rank_position)
    gems.sort(key=lambda i: i.rank_position)

    return DigestDetail(
        id=digest.id,
        generated_at=digest.generated_at,
        digest_type=digest.digest_type,
        notes=digest.notes,
        fresh=fresh,
        hidden_gems=gems,
        stats=None,
    )
