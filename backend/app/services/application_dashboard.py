"""CRM dashboard — buckets over `application_job_tracks` + ranker overlay (Jobr-style merge)."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.application_job_track import ApplicationJobTrack
from ..models.job import Job
from ..models.job_score import JobScore
from ..schemas.application_dashboard import (
    ApplicationDashboardResponse,
    DashboardTrackRow,
    UntrackedJobRow,
)
from . import application_job_tracks as tracks_svc
from . import profiles as profiles_svc


_DASH_OUTCOME_ALLOWED = frozenset(
    {"unset", "rejected", "interviewing", "offered", "hired", "withdrawn"}
)


def parse_dashboard_outcome_filter(raw: Optional[str]) -> frozenset[str]:
    """Comma-separated tokens for ``application_outcomes`` query. Empty ⇒ no filter."""
    if raw is None or not str(raw).strip():
        return frozenset()
    parts = {p.strip().lower() for p in str(raw).split(",") if p.strip()}
    unknown = parts - _DASH_OUTCOME_ALLOWED
    if unknown:
        raise ValueError(
            "unknown application_outcomes tokens: " + ", ".join(sorted(unknown))
        )
    return frozenset(parts)


def _matches_outcome(track: ApplicationJobTrack, wanted: frozenset[str]) -> bool:
    if not wanted:
        return True
    cur = track.application_outcome
    if cur is None:
        return "unset" in wanted
    return cur.lower() in wanted


def _norm_stage(stage: str) -> str:
    return re.sub(r"\s+", " ", (stage or "").strip().lower())


def pipeline_lane(stage: str) -> str:
    """Map free-text CRM stage → swim-lane bucket for dashboard UI."""
    n = _norm_stage(stage)
    if any(x in n for x in ("rejected", "declined")) or n in frozenset(
        {"withdrawn", "archived", "closed", "hired", "accepted"}
    ):
        return "closed"
    if "interview" in n or n.startswith("applied") or "offer" in n or n == "applied":
        return "post_apply"
    if n in {"interested", "shortlisted"} or "shortlist" in n:
        return "active"
    if "draft" in n or "prepar" in n:
        return "active"
    return "needs_attention"


def outcome_derived_lane(application_outcome: str | None) -> str | None:
    """When ``application_outcome`` is set, it dominates free-text staging for buckets."""
    if application_outcome is None or not str(application_outcome).strip():
        return None
    o = str(application_outcome).strip().lower()
    if o in ("rejected", "withdrawn", "hired"):
        return "closed"
    if o in ("interviewing", "offered"):
        return "post_apply"
    return None


def effective_pipeline_lane(stage: str, application_outcome: str | None) -> str:
    lane_keys = ("active", "post_apply", "closed", "needs_attention")
    dom = outcome_derived_lane(application_outcome)
    if dom is not None and dom in lane_keys:
        return dom  # type: ignore[return-value]
    lane_pm = pipeline_lane(stage)
    return lane_pm if lane_pm in lane_keys else "needs_attention"


def _best_score_rows(
    db: Session, job_ids: list[uuid.UUID], *, profile_id: Optional[uuid.UUID]
) -> dict[uuid.UUID, JobScore]:
    """Latest JobScore rows per job (tie-break newest `created_at`).

    If ``profile_id`` is set, only rows for that profile; otherwise scan all scores.
    """
    if not job_ids:
        return {}
    filt = JobScore.job_id.in_(job_ids)
    stmt = (
        select(JobScore).where(filt).where(JobScore.profile_id == profile_id)
        if profile_id is not None
        else select(JobScore).where(filt)
    )
    rows = list(db.scalars(stmt).all())
    best: dict[uuid.UUID, JobScore] = {}
    for row in rows:
        jid = row.job_id
        cur = best.get(jid)
        if cur is None or row.created_at > cur.created_at:
            best[jid] = row
    return best


def _row_for_track(
    tr,
    *,
    profile,
    prof_scores: dict[uuid.UUID, JobScore],
    default_scores: dict[uuid.UUID, JobScore],
) -> DashboardTrackRow:
    jid = tr.canonical_job_id
    j = tr.job
    lane_pm = effective_pipeline_lane(tr.current_stage, tr.application_outcome)
    lane_keys = ("active", "post_apply", "closed", "needs_attention")
    lane_key = lane_pm if lane_pm in lane_keys else "needs_attention"

    eff_rank = j.ranking_score if j else Decimal("0")
    bucket = None
    rationale = None

    if profile is not None and not profile.is_default:
        js = prof_scores.get(jid)
        if js is not None:
            eff_rank = js.score
            bucket = js.bucket
            rationale = js.rationale
    else:
        ds = default_scores.get(jid)
        if ds is not None:
            eff_rank = ds.score
            bucket = ds.bucket
            rationale = ds.rationale

    return DashboardTrackRow(
        id=tr.id,
        canonical_job_id=jid,
        current_stage=tr.current_stage,
        application_outcome=tr.application_outcome,
        notes=tr.notes,
        stage_changed_at=tr.stage_changed_at,
        job_title=tr.job_title,
        job_company_name=tr.job_company_name,
        job_apply_url=tr.job_apply_url,
        created_at=tr.created_at,
        updated_at=tr.updated_at,
        pipeline_lane=lane_key,  # type: ignore[arg-type]
        effective_ranking_score=eff_rank,
        effective_bucket=bucket,
        rationale=rationale,
    )


def build_dashboard(
    db: Session,
    *,
    user_id: uuid.UUID,
    profile_slug: Optional[str],
    q: Optional[str],
    include_untracked: bool,
    untracked_limit: int,
    untracked_min_score: Decimal,
    application_outcomes_filter: frozenset[str],
) -> ApplicationDashboardResponse:
    """Grouped CRM rows + optional pipeline watchlist (no Jobr SQLite schema).

    Mirrors Jobr's ``GET /jobs/dashboard`` as an operator view over canonical jobs
    and ``application_job_tracks`` rather than SQLite ``jobs.processing_state``.
    """
    tracks = tracks_svc.list_tracks(db, user_id=user_id, stage=None)
    profile = profiles_svc.get_effective(db, profile_slug, uid=user_id)

    query_terms = [t.strip().lower() for t in (q or "").split() if t.strip()]

    def _matches_text(track: ApplicationJobTrack) -> bool:
        if not query_terms:
            return True
        blobs = [
            (track.job_title or ""),
            (track.job_company_name or ""),
            (track.current_stage or ""),
            (track.application_outcome or ""),
            (track.notes or ""),
        ]
        hay = "\n".join(blobs).lower()
        return all(term in hay for term in query_terms)

    filtered = [
        t
        for t in tracks
        if _matches_text(t) and _matches_outcome(t, application_outcomes_filter)
    ]
    job_ids = [tr.canonical_job_id for tr in filtered]

    prof_scores: dict[uuid.UUID, JobScore] = {}
    default_scores = _best_score_rows(db, job_ids, profile_id=None)
    if profile is not None and not profile.is_default:
        prof_scores = _best_score_rows(db, job_ids, profile_id=profile.id)

    lanes = {
        "active": [],
        "post_apply": [],
        "closed": [],
        "needs_attention": [],
    }

    for tr in filtered:
        row = _row_for_track(
            tr,
            profile=profile,
            prof_scores=prof_scores,
            default_scores=default_scores,
        )
        lanes[row.pipeline_lane].append(row)

    lane_counts = {k: len(v) for k, v in lanes.items()}
    slug_out = profile.slug if profile else None

    untracked: list[UntrackedJobRow] = []
    if include_untracked and untracked_limit > 0:
        sub_existing = select(ApplicationJobTrack.canonical_job_id).where(
            ApplicationJobTrack.user_id == user_id
        )
        stmt = (
            select(Job)
            .where(
                Job.is_active.is_(True),
                Job.ranking_score >= untracked_min_score,
                Job.id.notin_(sub_existing),
            )
            .order_by(Job.ranking_score.desc())
            .limit(untracked_limit)
        )
        for jj in db.scalars(stmt).all():
            untracked.append(
                UntrackedJobRow(
                    job_id=jj.id,
                    title=jj.title,
                    company_name=jj.company_name,
                    apply_url=jj.apply_url,
                    ranking_score=jj.ranking_score,
                    last_seen_at=jj.last_seen_at,
                )
            )

    return ApplicationDashboardResponse(
        total_tracked=len(filtered),
        profile_slug=slug_out,
        lanes=lanes,
        lane_counts=lane_counts,
        untracked_candidates=untracked,
    )
