"""Qualification rules — deterministic filter over canonical jobs (roadmap §3 MVP)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..schemas.qualification import (
    QualificationEvaluateRequest,
    QualificationEvaluateResponse,
    QualificationSettingsOut,
)
from ..services import qualification as qualification_svc
from .deps import DbSession, TenantUserId, require_admin_token

router = APIRouter()


@router.get(
    "/settings",
    response_model=QualificationSettingsOut,
    summary="Load saved qualification rules JSON for the tenant user.",
)
def get_qualification_settings(
    db: DbSession,
    user_id: TenantUserId,
) -> QualificationSettingsOut:
    raw = qualification_svc.get_settings_dict(db, user_id=user_id)
    rules = qualification_svc.rules_from_dict(raw)
    return QualificationSettingsOut(rules=rules)


@router.put(
    "/settings",
    dependencies=[Depends(require_admin_token)],
    response_model=QualificationSettingsOut,
    summary="Replace saved qualification rules (requires X-Admin-Token).",
)
def put_qualification_settings(
    db: DbSession,
    user_id: TenantUserId,
    body: QualificationSettingsOut,
) -> QualificationSettingsOut:
    qualification_svc.upsert_settings(db, user_id=user_id, rules=body.rules)
    return body


@router.post(
    "/evaluate",
    response_model=QualificationEvaluateResponse,
    summary="Evaluate jobs against saved rules (or a one-off rules_override).",
)
def post_qualification_evaluate(
    db: DbSession,
    user_id: TenantUserId,
    body: QualificationEvaluateRequest,
) -> QualificationEvaluateResponse:
    if body.rules_override is not None:
        rules = body.rules_override
    else:
        raw = qualification_svc.get_settings_dict(db, user_id=user_id)
        rules = qualification_svc.rules_from_dict(raw)
    items = qualification_svc.evaluate_job_ids(
        db,
        user_id=user_id,
        job_ids=body.job_ids,
        rules=rules,
        profile_slug=body.profile_slug,
    )
    return QualificationEvaluateResponse(evaluated=len(items), items=items)
