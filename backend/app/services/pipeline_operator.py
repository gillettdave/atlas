"""Operator inspection — canonical ``raw_job_events`` + pipeline log tail."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..models.ingestion_run import IngestionRun
from ..models.pipeline_event import PipelineEvent
from ..models.raw_job_event import RawJobEvent

HTML_DETAIL_MAX_CHARS = 48_000


def summarize_status_counts(db: Session) -> tuple[dict[str, int], dict[str, int]]:
    rows_p = db.execute(
        select(RawJobEvent.parse_status, func.count(RawJobEvent.id)).group_by(
            RawJobEvent.parse_status
        )
    ).all()
    rows_f = db.execute(
        select(RawJobEvent.fetch_status, func.count(RawJobEvent.id)).group_by(
            RawJobEvent.fetch_status
        )
    ).all()
    parse_counts = {str(s): int(c) for s, c in rows_p}
    fetch_counts = {str(s): int(c) for s, c in rows_f}
    return parse_counts, fetch_counts


def title_hint(raw_payload: dict[str, Any] | None) -> str | None:
    """Best-effort short label from heterogeneous collector payloads."""
    if not isinstance(raw_payload, dict):
        return None
    for key in ("job_title", "title", "position_title", "normalized_title"):
        v = raw_payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:200]
    ext = raw_payload.get("extracted")
    if isinstance(ext, dict):
        for k in ("job_title", "title"):
            vv = ext.get(k)
            if isinstance(vv, str) and vv.strip():
                return vv.strip()[:200]
    return None


def list_recent_raw_events(
    db: Session,
    *,
    hours: int,
    limit: int,
    failure_focus: bool,
    parse_status: list[str] | None,
    fetch_status: list[str] | None,
    provider_contains: str | None,
) -> tuple[int, list[RawJobEvent], dict[uuid.UUID, str | None]]:
    """Return ``(total matching window, page rows, source_name per ingestion_run_id)``."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    conditions: list[Any] = [RawJobEvent.created_at >= cutoff]

    if failure_focus:
        conditions.append(
            or_(
                RawJobEvent.fetch_status == "failed_fetch",
                RawJobEvent.parse_status.in_(
                    ["failed_parse", "rejected", "needs_review"]
                ),
            )
        )
    else:
        if parse_status:
            conditions.append(RawJobEvent.parse_status.in_(parse_status))
        if fetch_status:
            conditions.append(RawJobEvent.fetch_status.in_(fetch_status))

    if provider_contains and provider_contains.strip():
        conditions.append(
            RawJobEvent.provider.ilike(f"%{provider_contains.strip()}%")
        )

    filt = and_(*conditions)

    count_q = (
        select(func.count(RawJobEvent.id))
        .select_from(RawJobEvent)
        .outerjoin(IngestionRun, RawJobEvent.ingestion_run_id == IngestionRun.id)
        .where(filt)
    )
    total = int(db.execute(count_q).scalar_one() or 0)

    page_q = (
        select(RawJobEvent, IngestionRun.source_name)
        .outerjoin(IngestionRun, RawJobEvent.ingestion_run_id == IngestionRun.id)
        .where(filt)
        .order_by(RawJobEvent.created_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    tuples = db.execute(page_q).all()

    rows: list[RawJobEvent] = []
    snames: dict[uuid.UUID, str | None] = {}
    for raw, src in tuples:
        rows.append(raw)
        snames[raw.ingestion_run_id] = src
    return total, rows, snames


def pipeline_events_for_raw(db: Session, raw_id: uuid.UUID, *, limit: int = 45) -> list:
    stmt = (
        select(PipelineEvent)
        .where(
            PipelineEvent.entity_type == "raw_job_event",
            PipelineEvent.entity_id == raw_id,
        )
        .order_by(PipelineEvent.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    return list(db.scalars(stmt).all())


def load_raw_event_detail(
    db: Session, raw_id: uuid.UUID
) -> tuple[RawJobEvent, str | None, list] | None:
    """Return ``(raw, ingestion source_name, pipeline_event rows)`` or ``None``."""
    raw = db.get(RawJobEvent, raw_id)
    if raw is None:
        return None
    run = db.get(IngestionRun, raw.ingestion_run_id)
    src = run.source_name if run else None
    evs = pipeline_events_for_raw(db, raw.id)
    return raw, src, evs


def html_excerpt_for_operator(raw: RawJobEvent) -> tuple[str | None, int, bool]:
    """Return ``(excerpt or None, total_len, truncated)``."""
    html = raw.raw_html
    if not html:
        return None, 0, False
    n = len(html)
    if n <= HTML_DETAIL_MAX_CHARS:
        return html, n, False
    return html[:HTML_DETAIL_MAX_CHARS], n, True
