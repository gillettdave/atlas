"""Pipeline operator — failures + raw_event inspection (canonical ``raw_job_events``)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from ..schemas.pipeline_operator import (
    OperatorPipelineEventBrief,
    OperatorRawEventDetailResponse,
    OperatorRawEventListItem,
    OperatorRawEventListResponse,
    PipelineOperatorSummaryResponse,
)
from ..services import pipeline_operator as op_svc

from .deps import DbSession, require_admin_token

router = APIRouter()


def _split_csv(raw: str | None) -> list[str] | None:
    if not raw or not str(raw).strip():
        return None
    parts = [x.strip() for x in str(raw).split(",") if x.strip()]
    return parts or None


@router.get(
    "/operator/summary",
    response_model=PipelineOperatorSummaryResponse,
    dependencies=[Depends(require_admin_token)],
    summary="Grouped counts of raw_job_event parse/fetch statuses.",
)
def operator_pipeline_summary(db: DbSession) -> PipelineOperatorSummaryResponse:
    parse_counts, fetch_counts = op_svc.summarize_status_counts(db)
    return PipelineOperatorSummaryResponse(
        parse_status_counts=parse_counts,
        fetch_status_counts=fetch_counts,
    )


@router.get(
    "/operator/raw-events",
    response_model=OperatorRawEventListResponse,
    dependencies=[Depends(require_admin_token)],
    summary="Filterable recent raw_job_events (canonical pipeline queue / failures).",
)
def operator_raw_events(
    db: DbSession,
    hours: int = Query(168, ge=1, le=8760, description="Rolling window (UTC)."),
    limit: int = Query(80, ge=1, le=500),
    failure_focus: bool = Query(
        False,
        description="failed_fetch · failed_parse · rejected · needs_review.",
    ),
    parse_status: str | None = Query(
        None,
        description="Comma-separated parse_status (ignored when failure_focus).",
    ),
    fetch_status: str | None = Query(
        None, description="Comma-separated fetch_status values."
    ),
    provider_contains: str | None = Query(None, description="ILIKE substring on provider."),
) -> OperatorRawEventListResponse:
    ps = _split_csv(parse_status)
    fs = _split_csv(fetch_status)
    total, raws, snames = op_svc.list_recent_raw_events(
        db,
        hours=hours,
        limit=limit,
        failure_focus=failure_focus,
        parse_status=ps,
        fetch_status=fs,
        provider_contains=provider_contains,
    )
    items: list[OperatorRawEventListItem] = []
    for raw in raws:
        items.append(
            OperatorRawEventListItem(
                id=str(raw.id),
                ingestion_run_id=str(raw.ingestion_run_id),
                source_name=snames.get(raw.ingestion_run_id),
                provider=raw.provider,
                source_url=raw.source_url,
                fetch_status=raw.fetch_status,
                parse_status=raw.parse_status,
                created_at=raw.created_at,
                title_hint=op_svc.title_hint(raw.raw_payload),
            )
        )
    return OperatorRawEventListResponse(total=total, limit=limit, items=items)


@router.get(
    "/operator/raw-events/{raw_event_id}",
    response_model=OperatorRawEventDetailResponse,
    dependencies=[Depends(require_admin_token)],
    summary="One raw_job_event: payload, optional HTML excerpt, pipeline_event tail.",
)
def operator_raw_event_detail(
    raw_event_id: uuid.UUID, db: DbSession
) -> OperatorRawEventDetailResponse:
    bundle = op_svc.load_raw_event_detail(db, raw_event_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="raw_job_event not found")
    raw, source_name, events = bundle
    excerpt, total_len, truncated = op_svc.html_excerpt_for_operator(raw)
    pe_out = [
        OperatorPipelineEventBrief(
            id=str(e.id),
            entity_type=e.entity_type,
            entity_id=str(e.entity_id) if e.entity_id else None,
            event_name=e.event_name,
            details=e.details,
            created_at=e.created_at,
        )
        for e in events
    ]
    pl = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
    return OperatorRawEventDetailResponse(
        id=str(raw.id),
        ingestion_run_id=str(raw.ingestion_run_id),
        source_name=source_name,
        provider=raw.provider,
        source_url=raw.source_url,
        fetch_status=raw.fetch_status,
        parse_status=raw.parse_status,
        created_at=raw.created_at,
        raw_payload=pl,
        raw_html_excerpt=excerpt,
        raw_html_total_chars=total_len if total_len else None,
        raw_html_was_truncated=truncated,
        pipeline_events=pe_out,
    )
