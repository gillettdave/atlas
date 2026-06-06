"""CRM dashboard router — aggregated tracks + watchlist."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..schemas.application_dashboard import ApplicationDashboardResponse
from ..services import application_dashboard as dashboard_svc
from .deps import DbSession, TenantUserId

router = APIRouter()


@router.get(
    "/dashboard",
    response_model=ApplicationDashboardResponse,
    summary="CRM-style dashboard buckets over canonical jobs + tracks.",
)
def applications_dashboard(
    db: DbSession,
    tenant_id: TenantUserId,
    profile_slug: Optional[str] = Query(
        default=None,
        description="Overlay ranker scores from this profile (default profile uses canonical snapshots).",
    ),
    q: Optional[str] = Query(
        default=None,
        description="Search across title, company, stage, outcome, and notes.",
    ),
    application_outcomes: Optional[str] = Query(
        default=None,
        description=(
            "Comma-separated outcome filter — "
            "`unset`, `rejected`, `interviewing`, `offered`, `hired`, `withdrawn`. "
            "Omit or empty ⇒ no filtering."
        ),
    ),
    include_untracked: bool = Query(
        default=False,
        description="Include high-ranked jobs with no CRM track.",
    ),
    untracked_limit: int = Query(25, ge=0, le=100),
    untracked_min_score: Decimal = Query(Decimal("55"), ge=0, le=100),
) -> ApplicationDashboardResponse:
    try:
        outcome_want = dashboard_svc.parse_dashboard_outcome_filter(application_outcomes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return dashboard_svc.build_dashboard(
        db,
        user_id=tenant_id,
        profile_slug=profile_slug,
        q=q,
        include_untracked=include_untracked,
        untracked_limit=untracked_limit,
        untracked_min_score=untracked_min_score,
        application_outcomes_filter=outcome_want,
    )
