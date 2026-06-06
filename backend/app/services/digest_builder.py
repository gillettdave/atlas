"""Digest builder — freezes a ranked snapshot into durable digest rows.

A `Digest` is "the N best jobs as of now, deduped by company caps, grouped
into lanes".

Lanes:
- `fresh`       : jobs first seen within `fresh_hours`.
- `hidden_gems` : older jobs flagged by ranker as gems OR older-but-strong
                  jobs above `gem_min_score`.

Optional (Phase 3): when `apply_qualification` is True (default), candidates
are filtered through saved `/qualification` rules before per-company caps.

Design:
- Pull candidate jobs in generous excess of the target limit per lane.
- Order each lane by ranking_score desc (ties broken by recency).
- Apply a per-company cap across the whole digest (so one company can't
  monopolise the output).
- De-dupe: a job never appears in two lanes of the same digest.
- Persist atomically: Digest + DigestItem rows in one transaction.
- Log a PipelineEvent for observability.

This module keeps business logic; the API layer only translates HTTP.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..models.digest import Digest
from ..models.digest_item import DigestItem
from ..models.job import Job
from ..models.job_score import JobScore
from ..models.pipeline_event import PipelineEvent
from ..constants import SEEDED_LOCAL_USER_ID
from . import feedback as feedback_svc
from . import profiles as profiles_svc
from . import qualification as qualification_svc
from . import qualification_scorer as qual_scorer_svc


# ---------------------------------------------------------------------------
# Config & result types
# ---------------------------------------------------------------------------

@dataclass
class DigestConfig:
    """Knobs for a single digest-build pass."""

    digest_type: str = "daily"        # daily | weekly | hidden_gems | custom
    fresh_hours: int = 48
    fresh_limit: int = 15
    gem_limit: int = 10
    per_company_cap: int = 3
    min_ranking_score: Decimal = Decimal("35")  # skip "skip" bucket
    gem_min_score: Decimal = Decimal("60")      # padding threshold for gems lane
    notes: Optional[str] = None
    # Sprint I: when set, the builder excludes jobs the user has already
    # resolved (dismissed/applied/interviewed/rejected) under this
    # profile. The default profile is looked up when slug is omitted.
    profile_slug: Optional[str] = None
    # Phase 3: when True, exclude candidates that fail tenant qualification rules
    # (`user_qualification_settings`), using the same profile overlay as `/qualification/evaluate`.
    apply_qualification: bool = True
    # P1.5b: when True, score each candidate with LLM qualification scoring.
    # Jobs scoring < 3/10 are excluded. Cached per (job, profile) for 7 days.
    use_llm_qualification: bool = True


@dataclass
class DigestStats:
    fresh_selected: int = 0
    gem_selected: int = 0
    fresh_candidates: int = 0
    gem_candidates: int = 0
    dropped_by_cap: int = 0
    excluded_by_feedback: int = 0
    excluded_by_qualification: int = 0


@dataclass
class BuiltDigestItem:
    job: Job
    lane: str
    reason: str
    rank_position: int  # 1-indexed within lane


@dataclass
class BuiltDigest:
    digest: Digest
    items: list[BuiltDigestItem] = field(default_factory=list)
    stats: DigestStats = field(default_factory=DigestStats)

    @property
    def fresh_items(self) -> list[BuiltDigestItem]:
        return [i for i in self.items if i.lane == "fresh"]

    @property
    def gem_items(self) -> list[BuiltDigestItem]:
        return [i for i in self.items if i.lane == "hidden_gem"]


# ---------------------------------------------------------------------------
# Candidate queries
# ---------------------------------------------------------------------------

def _latest_profile_score_subquery(profile_id: uuid.UUID):
    """Subquery: latest job_scores row per job for a given profile.

    Returns a subquery with columns (job_id, score, hidden_gem).
    Joined LEFT OUTER against Job so jobs without a profile score fall back
    to Job.ranking_score via coalesce().
    """
    from sqlalchemy import func as _func
    return (
        select(
            JobScore.job_id,
            JobScore.score.label("profile_score"),
            JobScore.hidden_gem.label("profile_hidden_gem"),
        )
        .distinct(JobScore.job_id)
        .where(JobScore.profile_id == profile_id)
        .order_by(JobScore.job_id, JobScore.created_at.desc())
        .subquery()
    )


def _fresh_candidates(
    db: Session,
    *,
    now: datetime,
    cfg: DigestConfig,
    over_fetch: int,
    profile_id: Optional[uuid.UUID] = None,
    exclude_ids: Optional[set[uuid.UUID]] = None,
) -> list[Job]:
    cutoff = now - timedelta(hours=cfg.fresh_hours)

    if profile_id is not None:
        ps = _latest_profile_score_subquery(profile_id)
        effective_score = func.coalesce(ps.c.profile_score, Job.ranking_score)
        stmt = (
            select(Job)
            .outerjoin(ps, ps.c.job_id == Job.id)
            .where(
                Job.is_active.is_(True),
                Job.first_seen_at >= cutoff,
                effective_score >= cfg.min_ranking_score,
            )
            .order_by(effective_score.desc(), Job.first_seen_at.desc())
            .limit(over_fetch)
        )
    else:
        stmt = (
            select(Job)
            .where(
                Job.is_active.is_(True),
                Job.first_seen_at >= cutoff,
                Job.ranking_score >= cfg.min_ranking_score,
            )
            .order_by(Job.ranking_score.desc(), Job.first_seen_at.desc())
            .limit(over_fetch)
        )

    if exclude_ids:
        stmt = stmt.where(Job.id.notin_(exclude_ids))
    return list(db.execute(stmt).scalars().all())


def _gem_candidates(
    db: Session,
    *,
    now: datetime,
    cfg: DigestConfig,
    over_fetch: int,
    profile_id: Optional[uuid.UUID] = None,
    exclude_ids: Optional[set[uuid.UUID]] = None,
) -> tuple[list[Job], set[uuid.UUID]]:
    """Return (candidate_jobs, ids_flagged_as_gem_in_latest_score).

    Gems come from two sources, unioned and deduped:
    1) Jobs whose latest job_scores row has hidden_gem = True (for this profile).
    2) Active jobs older than fresh_hours with effective score >= gem_min_score.
    """
    cutoff = now - timedelta(hours=cfg.fresh_hours)

    # (1) latest-score-hidden-gem scoped to profile when available
    gem_score_filter = JobScore.hidden_gem.is_(True)
    if profile_id is not None:
        gem_score_filter = and_(JobScore.hidden_gem.is_(True), JobScore.profile_id == profile_id)

    latest_gem_stmt = (
        select(JobScore.job_id)
        .where(gem_score_filter)
        .order_by(JobScore.created_at.desc())
        .limit(over_fetch * 3)
    )
    gem_ids: set[uuid.UUID] = set()
    for jid in db.execute(latest_gem_stmt).scalars().all():
        gem_ids.add(jid)
        if len(gem_ids) >= over_fetch:
            break

    if profile_id is not None:
        ps = _latest_profile_score_subquery(profile_id)
        effective_score = func.coalesce(ps.c.profile_score, Job.ranking_score)
        older_strong = and_(
            Job.first_seen_at < cutoff,
            effective_score >= cfg.gem_min_score,
        )
        condition = or_(Job.id.in_(gem_ids), older_strong) if gem_ids else older_strong
        stmt = (
            select(Job)
            .outerjoin(ps, ps.c.job_id == Job.id)
            .where(Job.is_active.is_(True), condition)
            .order_by(effective_score.desc(), Job.last_seen_at.desc())
            .limit(over_fetch)
        )
    else:
        older_strong = and_(
            Job.first_seen_at < cutoff,
            Job.ranking_score >= cfg.gem_min_score,
        )
        condition = or_(Job.id.in_(gem_ids), older_strong) if gem_ids else older_strong
        stmt = (
            select(Job)
            .where(Job.is_active.is_(True), condition)
            .order_by(Job.ranking_score.desc(), Job.last_seen_at.desc())
            .limit(over_fetch)
        )

    if exclude_ids:
        stmt = stmt.where(Job.id.notin_(exclude_ids))
    jobs = list(db.execute(stmt).scalars().all())
    return jobs, gem_ids


# ---------------------------------------------------------------------------
# Per-company cap
# ---------------------------------------------------------------------------

def _select_with_caps(
    candidates: list[Job],
    *,
    limit: int,
    per_company_cap: int,
    seen_job_ids: set[uuid.UUID],
    company_counts: dict[str, int],
    stats: DigestStats,
) -> list[Job]:
    """Take at most `limit` jobs honoring per-company caps and job-dedupe.

    `seen_job_ids` and `company_counts` are mutated so repeated calls across
    lanes share state (no job in two lanes; cap counts across the digest).
    """
    out: list[Job] = []
    for job in candidates:
        if len(out) >= limit:
            break
        if job.id in seen_job_ids:
            continue
        key = (job.normalized_company_name or job.company_name or "").strip().lower()
        if company_counts.get(key, 0) >= per_company_cap:
            stats.dropped_by_cap += 1
            continue
        out.append(job)
        seen_job_ids.add(job.id)
        company_counts[key] = company_counts.get(key, 0) + 1
    return out


# ---------------------------------------------------------------------------
# Reason strings
# ---------------------------------------------------------------------------

def _reason_for_fresh(job: Job, now: datetime) -> str:
    hours = max((now - (job.first_seen_at or now)).total_seconds() / 3600.0, 0.0)
    if hours < 1:
        age = "just posted"
    elif hours < 24:
        age = f"{int(hours)}h old"
    else:
        age = f"{int(hours / 24)}d old"
    # ASCII-only separators so Windows PowerShell (cp1252) renders cleanly.
    return f"Fresh ({age}) - ranking {float(job.ranking_score):.1f}"


def _reason_for_gem(job: Job, *, is_gem_flagged: bool) -> str:
    if is_gem_flagged:
        return (
            f"Hidden gem - ranking {float(job.ranking_score):.1f} "
            f"(strong fit, ATS-direct, single-sourced)"
        )
    return f"Older strong match - ranking {float(job.ranking_score):.1f}"


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def build_digest(
    db: Session,
    cfg: Optional[DigestConfig] = None,
    *,
    now: Optional[datetime] = None,
) -> BuiltDigest:
    """Build and persist a Digest + its DigestItems.

    Commits the transaction on success. On any unexpected error the caller
    should roll back; we do not swallow exceptions here.
    """
    cfg = cfg or DigestConfig()
    now = now or datetime.now(timezone.utc)
    stats = DigestStats()

    # Resolve the feedback exclusion set for this profile (Sprint I).
    # Jobs the user has already dismissed/applied/interviewed/rejected
    # under this profile are filtered out of both lanes. The builder
    # stays v1-compatible when no profile is configured.
    resolved_profile = None
    exclude_ids: set[uuid.UUID] = set()
    if cfg.profile_slug:
        resolved_profile = profiles_svc.get_by_slug(db, cfg.profile_slug)
    if resolved_profile is None:
        resolved_profile = profiles_svc.get_default(db)
    if resolved_profile is not None:
        exclude_ids = feedback_svc.resolution_set(
            db, profile_id=resolved_profile.id
        )
    stats.excluded_by_feedback = len(exclude_ids)

    # Over-fetch enough candidates so per-company caps still leave us with
    # the requested limit in each lane.
    over = max(cfg.per_company_cap, 3) + 2
    fresh_pool_size = cfg.fresh_limit * over
    gem_pool_size = cfg.gem_limit * over

    digest_profile_id = resolved_profile.id if resolved_profile is not None else None

    fresh_pool = _fresh_candidates(
        db, now=now, cfg=cfg, over_fetch=fresh_pool_size,
        profile_id=digest_profile_id,
        exclude_ids=exclude_ids,
    )
    gem_pool, gem_flagged_ids = _gem_candidates(
        db, now=now, cfg=cfg, over_fetch=gem_pool_size,
        profile_id=digest_profile_id,
        exclude_ids=exclude_ids,
    )
    stats.fresh_candidates = len(fresh_pool)
    stats.gem_candidates = len(gem_pool)

    if cfg.apply_qualification:
        fq, dq_f = qualification_svc.filter_jobs_by_qualification(
            db,
            user_id=SEEDED_LOCAL_USER_ID,
            jobs=fresh_pool,
            profile_slug=cfg.profile_slug,
        )
        gq, dq_g = qualification_svc.filter_jobs_by_qualification(
            db,
            user_id=SEEDED_LOCAL_USER_ID,
            jobs=gem_pool,
            profile_slug=cfg.profile_slug,
        )
        fresh_pool, gem_pool = fq, gq
        stats.excluded_by_qualification = dq_f + dq_g

    seen_ids: set[uuid.UUID] = set()
    company_counts: dict[str, int] = {}

    fresh_selected = _select_with_caps(
        fresh_pool,
        limit=cfg.fresh_limit,
        per_company_cap=cfg.per_company_cap,
        seen_job_ids=seen_ids,
        company_counts=company_counts,
        stats=stats,
    )
    gem_selected = _select_with_caps(
        gem_pool,
        limit=cfg.gem_limit,
        per_company_cap=cfg.per_company_cap,
        seen_job_ids=seen_ids,
        company_counts=company_counts,
        stats=stats,
    )

    stats.fresh_selected = len(fresh_selected)
    stats.gem_selected = len(gem_selected)

    # ------- LLM qualification filter -----------------------------------
    # Score each selected candidate against the user's approved career facts.
    # Jobs scoring < 3/10 are removed from their lane before persisting.
    qual_scores: dict[uuid.UUID, tuple[float, str]] = {}
    if cfg.use_llm_qualification and (fresh_selected or gem_selected):
        all_candidates = fresh_selected + [j for j in gem_selected if j not in fresh_selected]
        try:
            qual_scores = qual_scorer_svc.score_candidates(
                db, all_candidates, profile_id=digest_profile_id
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "digest_builder: LLM qualification scoring failed, proceeding unfiltered: %s", exc
            )

        if qual_scores:
            min_score = qual_scorer_svc._MIN_QUALIFY_SCORE
            fresh_selected = [j for j in fresh_selected
                              if qual_scores.get(j.id, (5.0, ""))[0] >= min_score]
            gem_selected   = [j for j in gem_selected
                              if qual_scores.get(j.id, (5.0, ""))[0] >= min_score]
            stats.fresh_selected = len(fresh_selected)
            stats.gem_selected   = len(gem_selected)

    # ------- persist ----------------------------------------------------
    digest = Digest(
        generated_at=now,
        digest_type=cfg.digest_type,
        notes=cfg.notes,
    )
    db.add(digest)
    db.flush()  # need digest.id

    built_items: list[BuiltDigestItem] = []

    for i, job in enumerate(fresh_selected, start=1):
        reason = _reason_for_fresh(job, now=now)
        if job.id in qual_scores:
            q_score, q_reason = qual_scores[job.id]
            reason = f"{reason} | Qualification: {q_score:.0f}/10 — {q_reason}"
        db.add(
            DigestItem(
                digest_id=digest.id,
                job_id=job.id,
                rank_position=i,
                lane="fresh",
                reason=reason,
            )
        )
        built_items.append(
            BuiltDigestItem(job=job, lane="fresh", reason=reason, rank_position=i)
        )

    for i, job in enumerate(gem_selected, start=1):
        reason = _reason_for_gem(job, is_gem_flagged=job.id in gem_flagged_ids)
        if job.id in qual_scores:
            q_score, q_reason = qual_scores[job.id]
            reason = f"{reason} | Qualification: {q_score:.0f}/10 — {q_reason}"
        db.add(
            DigestItem(
                digest_id=digest.id,
                job_id=job.id,
                rank_position=i,
                lane="hidden_gem",
                reason=reason,
            )
        )
        built_items.append(
            BuiltDigestItem(job=job, lane="hidden_gem", reason=reason, rank_position=i)
        )

    db.add(
        PipelineEvent(
            entity_type="digest",
            entity_id=digest.id,
            event_name="digest_built",
            details={
                "digest_type": cfg.digest_type,
                "fresh_selected": stats.fresh_selected,
                "gem_selected": stats.gem_selected,
                "dropped_by_cap": stats.dropped_by_cap,
                "fresh_candidates": stats.fresh_candidates,
                "gem_candidates": stats.gem_candidates,
                "excluded_by_feedback": stats.excluded_by_feedback,
                "per_company_cap": cfg.per_company_cap,
                "min_ranking_score": float(cfg.min_ranking_score),
                "profile_slug": (
                    resolved_profile.slug if resolved_profile else None
                ),
                "apply_qualification": cfg.apply_qualification,
                "excluded_by_qualification": stats.excluded_by_qualification,
            },
        )
    )

    db.commit()

    return BuiltDigest(digest=digest, items=built_items, stats=stats)


# ---------------------------------------------------------------------------
# Read helpers (used by GET endpoints)
# ---------------------------------------------------------------------------

def list_digests(
    db: Session, *, limit: int = 20, offset: int = 0
) -> tuple[list[tuple[Digest, int]], int]:
    """Return (rows, total_count) where each row is (Digest, item_count)."""
    total = db.execute(select(func.count(Digest.id))).scalar_one()

    item_count_subq = (
        select(DigestItem.digest_id, func.count(DigestItem.id).label("n"))
        .group_by(DigestItem.digest_id)
        .subquery()
    )

    stmt = (
        select(Digest, func.coalesce(item_count_subq.c.n, 0))
        .outerjoin(item_count_subq, item_count_subq.c.digest_id == Digest.id)
        .order_by(Digest.generated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = [(d, int(n)) for d, n in db.execute(stmt).all()]
    return rows, int(total)


def get_digest_with_items(
    db: Session, digest_id: uuid.UUID
) -> Optional[tuple[Digest, list[tuple[DigestItem, Job]]]]:
    digest = db.get(Digest, digest_id)
    if digest is None:
        return None
    stmt = (
        select(DigestItem, Job)
        .join(Job, Job.id == DigestItem.job_id)
        .where(DigestItem.digest_id == digest_id)
        .order_by(DigestItem.lane.asc(), DigestItem.rank_position.asc())
    )
    rows = [(di, j) for di, j in db.execute(stmt).all()]
    return digest, rows
