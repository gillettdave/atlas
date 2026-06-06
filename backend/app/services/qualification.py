"""Qualification rules engine — filter jobs against saved JSON rules (MVP, no LLM)."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.job import Job
from ..models.job_score import JobScore
from ..models.user_profile import UserProfile
from ..models.user_qualification_settings import UserQualificationSettings
from ..schemas.qualification import QualificationEvalItem, QualificationRules
from . import profiles as profiles_svc


def _norm_list(items: Optional[list[str]]) -> list[str]:
    if not items:
        return []
    return [x.strip() for x in items if x and str(x).strip()]


def rules_from_dict(raw: dict[str, Any] | None) -> QualificationRules:
    if not raw:
        return QualificationRules()
    return QualificationRules.model_validate(raw)


def get_settings_dict(db: Session, *, user_id: uuid.UUID) -> dict[str, Any]:
    row = db.scalar(
        select(UserQualificationSettings).where(
            UserQualificationSettings.user_id == user_id
        )
    )
    if row is None:
        return {}
    return dict(row.rules or {})


def upsert_settings(
    db: Session,
    *,
    user_id: uuid.UUID,
    rules: QualificationRules,
) -> None:
    payload = rules.model_dump(exclude_none=True)
    row = db.scalar(
        select(UserQualificationSettings).where(
            UserQualificationSettings.user_id == user_id
        )
    )
    if row is None:
        row = UserQualificationSettings(user_id=user_id, rules=payload)
        db.add(row)
    else:
        row.rules = payload
    db.commit()


def _effective_ranking(
    db: Session,
    job: Job,
    *,
    profile: Optional[UserProfile],
) -> Optional[Decimal]:
    if profile is None or profile.is_default:
        return job.ranking_score
    row = db.execute(
        select(JobScore.score)
        .where(
            JobScore.job_id == job.id,
            JobScore.profile_id == profile.id,
        )
        .order_by(JobScore.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row


def _haystack(job: Job) -> str:
    parts = [
        job.title or "",
        job.company_name or "",
        job.description_clean or "",
    ]
    return "\n".join(parts).lower()


def job_passes(
    job: Job,
    *,
    ranking_score: Optional[Decimal],
    rules: QualificationRules,
) -> tuple[bool, list[str]]:
    failed: list[str] = []

    blocks = _norm_list(rules.block_if_text_contains_any)
    hay = _haystack(job)
    for phrase in blocks:
        if phrase.lower() in hay:
            failed.append(f"blocked_text:{phrase[:40]}")

    company_blocks = _norm_list(rules.company_name_block_substrings)
    co = (job.company_name or "").lower()
    for s in company_blocks:
        if s.lower() in co:
            failed.append(f"blocked_company:{s[:40]}")

    if failed:
        return False, failed

    must = _norm_list(rules.title_or_description_must_contain_any)
    if must:
        td = ((job.title or "") + "\n" + (job.description_clean or "")).lower()
        if not any(m.lower() in td for m in must):
            failed.append("must_contain_any_unsatisfied")

    if rules.min_ranking_score is not None:
        if ranking_score is None:
            failed.append("no_ranking_score")
        elif float(ranking_score) < float(rules.min_ranking_score):
            failed.append("below_min_ranking_score")

    allow_remote = _norm_list(rules.remote_types_allowed)
    if allow_remote:
        rt = (job.remote_type or "").strip().lower()
        allowed = {x.lower() for x in allow_remote}
        if not rt or rt not in allowed:
            failed.append("remote_type_not_allowed")

    return (len(failed) == 0), failed


def filter_jobs_by_qualification(
    db: Session,
    *,
    user_id: uuid.UUID,
    jobs: list[Job],
    profile_slug: Optional[str],
) -> tuple[list[Job], int]:
    """Drop jobs that fail saved tenant rules (same semantics as ``/qualification/evaluate``).

    Returns ``(kept, dropped_count)``. When no rules are configured, returns
    ``jobs`` unchanged and ``0`` drops.
    """
    raw = get_settings_dict(db, user_id=user_id)
    rules = rules_from_dict(raw)
    if not rules.model_dump(exclude_none=True):
        return jobs, 0
    profile = profiles_svc.get_effective(db, profile_slug, uid=user_id)
    kept: list[Job] = []
    dropped = 0
    for job in jobs:
        score = _effective_ranking(db, job, profile=profile)
        ok, _ = job_passes(job, ranking_score=score, rules=rules)
        if ok:
            kept.append(job)
        else:
            dropped += 1
    return kept, dropped


def qualification_pass_map(
    db: Session,
    *,
    user_id: uuid.UUID,
    jobs: Iterable[Job],
    profile_slug: Optional[str],
) -> dict[uuid.UUID, bool]:
    """Whether each job passes saved tenant rules (True when no rules are stored)."""
    jobs_list = list(jobs)
    if not jobs_list:
        return {}
    raw = get_settings_dict(db, user_id=user_id)
    rules = rules_from_dict(raw)
    if not rules.model_dump(exclude_none=True):
        return {j.id: True for j in jobs_list}
    profile = profiles_svc.get_effective(db, profile_slug, uid=user_id)
    out: dict[uuid.UUID, bool] = {}
    for job in jobs_list:
        score = _effective_ranking(db, job, profile=profile)
        ok, _ = job_passes(job, ranking_score=score, rules=rules)
        out[j.id] = ok
    return out


def evaluate_job_ids(
    db: Session,
    *,
    user_id: uuid.UUID,
    job_ids: list[uuid.UUID],
    rules: QualificationRules,
    profile_slug: Optional[str],
) -> list[QualificationEvalItem]:
    profile = profiles_svc.get_effective(db, profile_slug, uid=user_id)
    out: list[QualificationEvalItem] = []
    for jid in job_ids:
        job = db.get(Job, jid)
        if job is None:
            out.append(
                QualificationEvalItem(
                    job_id=jid, passed=False, reasons_failed=["job_not_found"]
                )
            )
            continue
        score = _effective_ranking(db, job, profile=profile)
        ok, reasons = job_passes(job, ranking_score=score, rules=rules)
        out.append(QualificationEvalItem(job_id=jid, passed=ok, reasons_failed=reasons))
    return out
