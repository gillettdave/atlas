"""feedback - Sprint I.

Business logic for recording user reactions to jobs and deriving useful
views on top of the log:

- `record` writes one `job_feedback` row + a `pipeline_events.feedback_recorded`
  row for observability. Always commits.

- `resolution_set` returns the set of job_ids that have ANY resolution
  action (`dismissed | applied | interviewed | rejected`) under a given
  profile. The digest builder uses this to avoid re-showing jobs the
  user has already acted on.

- `summary_for_job` returns a compact view used on the job detail page
  (latest action + per-action counts).

We intentionally store feedback as an append-only event log; "undo" is
expressed by recording an opposite/neutralizing action rather than
editing history. This keeps audit clean and lets future learning loops
see the full trajectory.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.job import Job
from ..models.job_feedback import (
    FEEDBACK_ACTIONS,
    JobFeedback,
    RESOLUTION_ACTIONS,
)
from ..models.pipeline_event import PipelineEvent
from ..models.user_profile import UserProfile
from . import profiles as profiles_svc


logger = logging.getLogger("atlas.feedback")


class FeedbackError(RuntimeError):
    """Raised for business-rule violations (bad action, missing job, ...)."""


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------

@dataclass
class FeedbackResolveResult:
    feedback: JobFeedback
    profile: Optional[UserProfile]
    is_resolution: bool


def record(
    db: Session,
    *,
    job_id: uuid.UUID,
    action: str,
    profile_slug: Optional[str] = None,
    source: str = "ui",
    note: Optional[str] = None,
) -> FeedbackResolveResult:
    """Append one feedback event.

    Resolves `profile_slug` to a concrete UserProfile (falls back to the
    default profile). Raises FeedbackError if the job does not exist or
    the action is invalid.
    """
    if action not in FEEDBACK_ACTIONS:
        raise FeedbackError(
            f"invalid action {action!r}; expected one of {FEEDBACK_ACTIONS}"
        )

    job = db.get(Job, job_id)
    if job is None:
        raise FeedbackError(f"job not found: {job_id}")

    profile: Optional[UserProfile]
    if profile_slug:
        profile = profiles_svc.get_by_slug(db, profile_slug)
        if profile is None:
            raise FeedbackError(f"profile not found: slug={profile_slug!r}")
    else:
        # Default profile. Bootstrapped on app startup; we tolerate its
        # absence by storing profile_id=NULL rather than crashing.
        profile = profiles_svc.get_default(db)

    fb = JobFeedback(
        job_id=job_id,
        profile_id=profile.id if profile is not None else None,
        action=action,
        source=source,
        note=(note or None),
    )
    db.add(fb)

    db.add(
        PipelineEvent(
            entity_type="job",
            entity_id=job_id,
            event_name="feedback_recorded",
            details={
                "action": action,
                "source": source,
                "profile_id": str(profile.id) if profile else None,
                "profile_slug": profile.slug if profile else None,
                "has_note": bool(note),
                "is_resolution": action in RESOLUTION_ACTIONS,
            },
        )
    )
    db.commit()
    db.refresh(fb)

    return FeedbackResolveResult(
        feedback=fb,
        profile=profile,
        is_resolution=action in RESOLUTION_ACTIONS,
    )


# ---------------------------------------------------------------------------
# Reads used by digest_builder + job detail
# ---------------------------------------------------------------------------

def resolution_set(
    db: Session,
    *,
    profile_id: Optional[uuid.UUID],
) -> set[uuid.UUID]:
    """Return {job_id} that should be hidden from future digests.

    A job is "resolved" if it has at least one RESOLUTION_ACTIONS event
    under `profile_id` (or NULL-profile events when profile_id is None).
    Positive actions (saved / clicked) never cause exclusion.
    """
    stmt = (
        select(JobFeedback.job_id)
        .where(JobFeedback.action.in_(RESOLUTION_ACTIONS))
        .distinct()
    )
    if profile_id is None:
        stmt = stmt.where(JobFeedback.profile_id.is_(None))
    else:
        stmt = stmt.where(JobFeedback.profile_id == profile_id)

    return set(db.execute(stmt).scalars().all())


def list_feedback(
    db: Session,
    *,
    job_id: Optional[uuid.UUID] = None,
    profile_id: Optional[uuid.UUID] = None,
    action: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[JobFeedback]]:
    """Paginated log lookup. Returns (total_matching, items_desc_by_created_at)."""
    base = select(JobFeedback)
    count = select(func.count(JobFeedback.id))

    if job_id is not None:
        base = base.where(JobFeedback.job_id == job_id)
        count = count.where(JobFeedback.job_id == job_id)
    if profile_id is not None:
        base = base.where(JobFeedback.profile_id == profile_id)
        count = count.where(JobFeedback.profile_id == profile_id)
    if action:
        base = base.where(JobFeedback.action == action)
        count = count.where(JobFeedback.action == action)

    total = int(db.execute(count).scalar_one() or 0)

    items = list(
        db.execute(
            base.order_by(JobFeedback.created_at.desc())
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        )
        .scalars()
        .all()
    )
    return total, items


def summary_for_job(
    db: Session,
    *,
    job_id: uuid.UUID,
    profile_id: Optional[uuid.UUID] = None,
) -> dict:
    """Compact per-job stats for the UI detail panel.

    Shape matches `schemas.feedback.FeedbackJobSummary`. When
    `profile_id` is given, only that profile's events are considered;
    otherwise all profiles are aggregated.
    """
    base = select(JobFeedback).where(JobFeedback.job_id == job_id)
    if profile_id is not None:
        base = base.where(JobFeedback.profile_id == profile_id)
    rows = list(
        db.execute(base.order_by(JobFeedback.created_at.desc())).scalars().all()
    )

    counts: dict[str, int] = {a: 0 for a in FEEDBACK_ACTIONS}
    for r in rows:
        counts[r.action] = counts.get(r.action, 0) + 1

    latest = rows[0] if rows else None
    is_resolved = any(r.action in RESOLUTION_ACTIONS for r in rows)

    return {
        "job_id": job_id,
        "profile_id": profile_id,
        "latest_action": latest.action if latest else None,
        "latest_source": latest.source if latest else None,
        "latest_at": latest.created_at if latest else None,
        "counts": counts,
        "is_resolved": is_resolved,
    }


def bulk_resolution_maps(
    db: Session,
    job_ids: Iterable[uuid.UUID],
    *,
    profile_id: Optional[uuid.UUID] = None,
) -> dict[uuid.UUID, str]:
    """Return {job_id -> latest resolution action} for a batch.

    Efficient batch helper for list views. Only considers resolution
    actions; saves/clicks are ignored here so the UI can still show
    those jobs in a normal state.
    """
    ids = list(job_ids)
    if not ids:
        return {}

    # Use DISTINCT ON to grab latest resolution action per job in one
    # round trip.
    stmt = (
        select(
            JobFeedback.job_id,
            JobFeedback.action,
        )
        .where(JobFeedback.job_id.in_(ids))
        .where(JobFeedback.action.in_(RESOLUTION_ACTIONS))
        .order_by(JobFeedback.job_id, JobFeedback.created_at.desc())
        .distinct(JobFeedback.job_id)
    )
    if profile_id is not None:
        stmt = stmt.where(JobFeedback.profile_id == profile_id)

    out: dict[uuid.UUID, str] = {}
    for job_id, action in db.execute(stmt).all():
        out[job_id] = action
    return out
