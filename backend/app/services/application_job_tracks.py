"""Service layer — application_job_tracks (Phase E1)."""
from __future__ import annotations

import uuid
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models.application_job_track import ApplicationJobTrack
from ..models.base import utcnow
from ..models.job import Job


def _clamp_stage(stage: str | None) -> str:
    s = (stage or "").strip().lower()
    return (s[:64] if len(s) > 64 else s) or "interested"


_VALID_OUTCOME = frozenset(
    {"rejected", "interviewing", "offered", "hired", "withdrawn"}
)


def normalize_outcome_value(value: str | None) -> str | None:
    """Map PATCH `application_outcome` (None clears; empty string clears; else enum)."""
    if value is None or value == "":
        return None
    v = value.strip().lower()
    return v if v in _VALID_OUTCOME else None


class DuplicateTrackError(Exception):
    """A track already exists for (user_id, canonical_job_id)."""

    def __init__(self, existing: ApplicationJobTrack) -> None:
        self.existing = existing


def get_track(
    db: Session,
    track_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
) -> ApplicationJobTrack | None:
    return db.scalar(
        select(ApplicationJobTrack)
        .options(joinedload(ApplicationJobTrack.job))
        .where(
            ApplicationJobTrack.id == track_id,
            ApplicationJobTrack.user_id == user_id,
        )
    )


def list_tracks(db: Session, *, user_id: uuid.UUID, stage: str | None = None) -> list[ApplicationJobTrack]:
    stmt = (
        select(ApplicationJobTrack)
        .options(joinedload(ApplicationJobTrack.job))
        .where(ApplicationJobTrack.user_id == user_id)
        .order_by(ApplicationJobTrack.updated_at.desc())
    )
    if stage and stage.strip():
        stmt = stmt.where(ApplicationJobTrack.current_stage == _clamp_stage(stage))
    rows = db.scalars(stmt).unique().all()
    return list(rows)


def track_to_payload(track: ApplicationJobTrack) -> dict[str, Any]:
    """Serialize track + canonical job excerpt for HTTP."""
    j: Job | None = track.job
    return {
        "id": track.id,
        "user_id": track.user_id,
        "canonical_job_id": track.canonical_job_id,
        "current_stage": track.current_stage,
        "application_outcome": track.application_outcome,
        "notes": track.notes,
        "stage_changed_at": track.stage_changed_at,
        "created_at": track.created_at,
        "updated_at": track.updated_at,
        "job_title": (j.title if j else None),
        "job_company_name": (j.company_name if j else None),
        "job_apply_url": (j.apply_url if j else None),
    }


def create_track(
    db: Session,
    *,
    user_id: uuid.UUID,
    canonical_job_id: uuid.UUID,
    current_stage: str | None,
    notes: str | None,
    application_outcome: str | None = None,
) -> ApplicationJobTrack:
    """Raises ``LookupError('job_not_found')`` or ``DuplicateTrackError``."""
    _ = db.get(Job, canonical_job_id)
    if _ is None:
        raise LookupError("job_not_found")

    existing = db.scalar(
        select(ApplicationJobTrack).where(
            ApplicationJobTrack.user_id == user_id,
            ApplicationJobTrack.canonical_job_id == canonical_job_id,
        )
    )
    if existing is not None:
        raise DuplicateTrackError(existing)

    now = utcnow()
    oo = normalize_outcome_value(application_outcome)
    row = ApplicationJobTrack(
        user_id=user_id,
        canonical_job_id=canonical_job_id,
        current_stage=_clamp_stage(current_stage),
        application_outcome=oo,
        notes=(notes.strip()[:20000] if notes and notes.strip() else None),
        stage_changed_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    hydrated = db.scalar(
        select(ApplicationJobTrack)
        .options(joinedload(ApplicationJobTrack.job))
        .where(ApplicationJobTrack.id == row.id)
    )
    assert hydrated is not None
    return hydrated


def update_track(
    db: Session,
    track_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    patch: Mapping[str, Any],
) -> ApplicationJobTrack | None:
    """PATCH semantics: only keys present in ``patch`` are applied."""
    row = db.scalar(
        select(ApplicationJobTrack).where(
            ApplicationJobTrack.id == track_id,
            ApplicationJobTrack.user_id == user_id,
        )
    )
    if row is None:
        return None

    touched = False
    if "current_stage" in patch:
        nv = patch["current_stage"]
        if nv is not None:
            new_s = _clamp_stage(nv)
            if new_s != row.current_stage:
                row.current_stage = new_s
                row.stage_changed_at = utcnow()
                touched = True

    if "notes" in patch:
        nv = patch["notes"]
        if nv is None:
            row.notes = None
        else:
            t = str(nv).strip()
            row.notes = t[:20000] if t else None
        touched = True

    if "application_outcome" in patch:
        oo = normalize_outcome_value(patch["application_outcome"])
        if oo != row.application_outcome:
            row.application_outcome = oo
            touched = True

    if not touched:
        return db.scalar(
            select(ApplicationJobTrack)
            .options(joinedload(ApplicationJobTrack.job))
            .where(ApplicationJobTrack.id == track_id)
        )

    db.commit()
    db.refresh(row)
    return db.scalar(
        select(ApplicationJobTrack)
        .options(joinedload(ApplicationJobTrack.job))
        .where(ApplicationJobTrack.id == track_id)
    )


def delete_track(db: Session, track_id: uuid.UUID, *, user_id: uuid.UUID) -> bool:
    row = db.scalar(
        select(ApplicationJobTrack).where(
            ApplicationJobTrack.id == track_id,
            ApplicationJobTrack.user_id == user_id,
        )
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
