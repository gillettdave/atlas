"""Human-in-the-loop resolver for `needs_review` raw_job_events.

When the cleaner sees a Tier-2/Tier-3 match it flags the event with
parse_status='needs_review' rather than silently merging or forking.
This service closes the loop:

    merge    -> treat as MATCHED_EXISTING against a specific job_id
    promote  -> treat as NEW_CANONICAL (operator disagrees with match)
    reject   -> mark rejected (spam, wrong company, closed, etc.)

Every resolution writes a pipeline_event so we can audit decisions.

We reuse importer's insert/upsert helpers to keep the "what a
matched/new event actually does to the DB" logic in one place.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from ..models.job import Job
from ..models.pipeline_event import PipelineEvent
from ..models.raw_job_event import RawJobEvent
from . import cleaner_v2
from .importer import _insert_new_canonical, _upsert_sighting
from . import ranker as ranker_mod
from ..models.job_score import JobScore


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ReviewAction(str, Enum):
    MERGE = "merge"
    PROMOTE = "promote"
    REJECT = "reject"


class ReviewError(Exception):
    """Raised when a resolution cannot be applied (bad state / bad input)."""


@dataclass
class ReviewResolveResult:
    raw_event_id: uuid.UUID
    action: str
    job_id: Optional[uuid.UUID] = None
    rescored: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(
    db: Session,
    raw_id: uuid.UUID,
    event_name: str,
    details: dict,
) -> None:
    db.add(
        PipelineEvent(
            entity_type="raw_job_event",
            entity_id=raw_id,
            event_name=event_name,
            details=details,
        )
    )


def _rescore_one(db: Session, job: Job) -> None:
    """Quick rescore so the newly merged/promoted job has up-to-date score."""
    sight_map = ranker_mod._gather_sighting_stats(db, [job.id])
    count, domains = sight_map.get(job.id, (1, []))
    try:
        result = ranker_mod.score_job(
            job, sighting_count=count, sighting_domains=domains
        )
    except Exception:  # noqa: BLE001
        return
    job.ranking_score = result.ranking_score
    job.quality_score = result.quality_score
    db.add(
        JobScore(
            job_id=job.id,
            score=result.ranking_score,
            bucket=result.bucket,
            rationale=result.rationale,
            hidden_gem=result.hidden_gem,
            freshness_score=result.freshness_score,
            fit_score=result.fit_score,
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve(
    db: Session,
    *,
    raw_event_id: uuid.UUID,
    action: ReviewAction,
    target_job_id: Optional[uuid.UUID] = None,
    note: Optional[str] = None,
    rescore: bool = True,
) -> ReviewResolveResult:
    """Resolve a single `needs_review` raw_job_event.

    Args:
        raw_event_id: the raw_job_event to resolve.
        action: merge | promote | reject.
        target_job_id: required when action == merge. The canonical job
            that the raw event should be attributed to.
        note: optional operator-supplied justification, stored on the
            pipeline_event.
        rescore: if True (default), rescore the resulting job after
            merge/promote.

    Returns:
        ReviewResolveResult with the outcome + job_id (if applicable).

    Raises:
        ReviewError if the raw event isn't in needs_review state, if the
        target job is missing (for merge), or if normalization fails
        (for merge/promote).
    """
    raw = db.get(RawJobEvent, raw_event_id)
    if raw is None:
        raise ReviewError("raw_job_event not found")
    if raw.parse_status != "needs_review":
        raise ReviewError(
            f"raw_job_event is in state '{raw.parse_status}', not 'needs_review'"
        )

    details_base: dict = {"action": action.value}
    if note:
        details_base["note"] = note

    # -------------------------------------------------------------- reject
    if action == ReviewAction.REJECT:
        raw.parse_status = "rejected"
        _log(db, raw.id, "review_rejected", details_base)
        db.commit()
        return ReviewResolveResult(
            raw_event_id=raw.id, action=action.value
        )

    # For merge + promote we need a fresh normalization of the raw event.
    candidate = cleaner_v2.normalize_raw_event(raw)
    if candidate is None:
        raise ReviewError(
            "cannot normalize raw_job_event (missing company/title/apply_url)"
        )

    # --------------------------------------------------------------- merge
    if action == ReviewAction.MERGE:
        if target_job_id is None:
            raise ReviewError("target_job_id is required for merge")
        job = db.get(Job, target_job_id)
        if job is None:
            raise ReviewError("target job not found")

        job.last_seen_at = datetime.now(timezone.utc)
        job.is_active = True
        _upsert_sighting(db, job.id, raw, candidate)

        raw.parse_status = "stored"
        _log(
            db,
            raw.id,
            "review_merged",
            {**details_base, "job_id": str(job.id)},
        )

        rescored = False
        if rescore:
            _rescore_one(db, job)
            rescored = True

        db.commit()
        return ReviewResolveResult(
            raw_event_id=raw.id,
            action=action.value,
            job_id=job.id,
            rescored=rescored,
        )

    # -------------------------------------------------------------- promote
    if action == ReviewAction.PROMOTE:
        job = _insert_new_canonical(db, raw, candidate)
        raw.parse_status = "stored"
        _log(
            db,
            raw.id,
            "review_promoted",
            {**details_base, "job_id": str(job.id)},
        )

        # Flush so job.id is available + sightings are seen by the ranker.
        db.flush()
        rescored = False
        if rescore:
            _rescore_one(db, job)
            rescored = True

        db.commit()
        return ReviewResolveResult(
            raw_event_id=raw.id,
            action=action.value,
            job_id=job.id,
            rescored=rescored,
        )

    raise ReviewError(f"unknown action: {action}")


def get_review_detail(
    db: Session, raw_event_id: uuid.UUID
) -> tuple[RawJobEvent, Optional[cleaner_v2.NormalizedCandidate], list[Job], dict]:
    """Fetch a raw event plus its candidate jobs + normalized view.

    Returns (raw, candidate, candidate_jobs, extra):
        raw: the RawJobEvent row
        candidate: normalized view (may be None if payload is unusable)
        candidate_jobs: list of Job rows the cleaner flagged as possible matches
        extra: {"reason": str, "tier": str | None}
    """
    raw = db.get(RawJobEvent, raw_event_id)
    if raw is None:
        raise ReviewError("raw_job_event not found")

    candidate = cleaner_v2.normalize_raw_event(raw)

    # Find the most recent `needs_review` pipeline_event for this raw event
    # so we can recover the candidate ids + reason the cleaner logged.
    from sqlalchemy import select

    ev = db.execute(
        select(PipelineEvent)
        .where(
            PipelineEvent.entity_type == "raw_job_event",
            PipelineEvent.entity_id == raw.id,
            PipelineEvent.event_name == "needs_review",
        )
        .order_by(PipelineEvent.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    candidate_ids: list[uuid.UUID] = []
    extra = {"reason": "", "tier": None}
    if ev and ev.details:
        extra["reason"] = ev.details.get("reason") or ""
        extra["tier"] = ev.details.get("tier")
        for s in ev.details.get("candidates", []) or []:
            try:
                candidate_ids.append(uuid.UUID(s))
            except (ValueError, TypeError):
                continue

    jobs: list[Job] = []
    if candidate_ids:
        jobs = list(
            db.execute(
                select(Job).where(Job.id.in_(candidate_ids))
            ).scalars().all()
        )

    return raw, candidate, jobs, extra
