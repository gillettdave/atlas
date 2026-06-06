"""Normalization backfill for existing Jobs.

When cleaner_v2 / normalization logic improves (e.g. broader remote_type
sniffing in Sprint B.1), existing `jobs` rows keep their stale normalized
fields — the cleaner only writes those during initial insert.

This service re-runs `cleaner_v2.normalize_raw_event` against a job's most
recent RawJobEvent and fills in the fields that were missing / stale:
- remote_type
- location
- employment_type
- salary_text
- description_clean / description_hash

Canonical-identity fields (provider, external_job_id, company_name,
normalized_company_name, title, normalized_title, apply_url,
canonical_apply_url) are NEVER overwritten here — those define the
dedupe identity and are stable by contract.

Default semantics are "fill null only". Pass force=True to overwrite
existing non-null values (useful when a normalization rule changed, not
just when a field was originally missing).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.job import Job
from ..models.job_score import JobScore
from ..models.job_source_sighting import JobSourceSighting
from ..models.pipeline_event import PipelineEvent
from ..models.raw_job_event import RawJobEvent
from . import cleaner_v2
from . import ranker as ranker_mod


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class BackfillStats:
    scanned: int = 0
    updated: int = 0
    unchanged: int = 0
    no_raw_event: int = 0
    failed: int = 0
    rescored: int = 0
    fields_filled: dict[str, int] = field(default_factory=dict)

    def bump_field(self, field_name: str) -> None:
        self.fields_filled[field_name] = self.fields_filled.get(field_name, 0) + 1


# ---------------------------------------------------------------------------
# Latest raw event lookup
# ---------------------------------------------------------------------------

def _latest_raw_event_for_job(
    db: Session, job: Job
) -> Optional[RawJobEvent]:
    """Find the most recent raw_job_event that produced a sighting for this job.

    Matches by (provider, source_url) which is how the importer creates
    sightings from raw events. Falls back to any raw event with the same
    provider + canonical_apply_url (rare).
    """
    urls_stmt = (
        select(JobSourceSighting.source_url)
        .where(JobSourceSighting.job_id == job.id)
    )
    sighting_urls = [u for u in db.execute(urls_stmt).scalars().all() if u]
    if not sighting_urls:
        return None

    stmt = (
        select(RawJobEvent)
        .where(
            RawJobEvent.provider == job.provider,
            RawJobEvent.source_url.in_(sighting_urls),
        )
        .order_by(RawJobEvent.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Per-job update
# ---------------------------------------------------------------------------

_UPDATABLE_FIELDS: tuple[str, ...] = (
    "remote_type",
    "location",
    "employment_type",
    "salary_text",
    "description_clean",
    "description_hash",
)


def _apply_fill(
    job: Job,
    candidate: cleaner_v2.NormalizedCandidate,
    *,
    force: bool,
    stats: BackfillStats,
) -> bool:
    """Copy updatable normalized fields from `candidate` onto `job`.

    Returns True if any field was changed.
    """
    changed = False
    for name in _UPDATABLE_FIELDS:
        new_val = getattr(candidate, name, None)
        if not new_val:
            continue
        cur_val = getattr(job, name, None)
        if cur_val and not force:
            continue
        if cur_val == new_val:
            continue
        setattr(job, name, new_val)
        stats.bump_field(name)
        changed = True
    return changed


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def backfill_jobs(
    db: Session,
    *,
    only_missing_remote_type: bool = True,
    only_active: bool = True,
    limit: Optional[int] = None,
    force: bool = False,
    then_rescore: bool = True,
) -> BackfillStats:
    """Re-normalize a batch of jobs from their latest raw_job_event.

    Args:
        only_missing_remote_type: if True (default), restrict to jobs with
            remote_type IS NULL — this is the common case that Sprint B.1
            unlocked.
        only_active: restrict to jobs.is_active = True.
        limit: cap rows processed.
        force: overwrite even non-null fields.
        then_rescore: after filling, rescore touched jobs (recommended).
    """
    stats = BackfillStats()

    stmt = select(Job)
    if only_active:
        stmt = stmt.where(Job.is_active.is_(True))
    if only_missing_remote_type:
        stmt = stmt.where(Job.remote_type.is_(None))
    stmt = stmt.order_by(Job.last_seen_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)

    jobs: list[Job] = list(db.execute(stmt).scalars().all())
    touched_ids: list[uuid.UUID] = []

    for job in jobs:
        stats.scanned += 1
        try:
            raw = _latest_raw_event_for_job(db, job)
            if raw is None:
                stats.no_raw_event += 1
                continue

            candidate = cleaner_v2.normalize_raw_event(raw)
            if candidate is None:
                stats.failed += 1
                db.add(
                    PipelineEvent(
                        entity_type="job",
                        entity_id=job.id,
                        event_name="backfill_normalize_failed",
                        details={"raw_event_id": str(raw.id)},
                    )
                )
                continue

            changed = _apply_fill(job, candidate, force=force, stats=stats)
            if changed:
                stats.updated += 1
                touched_ids.append(job.id)
                db.add(
                    PipelineEvent(
                        entity_type="job",
                        entity_id=job.id,
                        event_name="backfill_normalized",
                        details={
                            "raw_event_id": str(raw.id),
                            "fields_touched": [
                                f for f in _UPDATABLE_FIELDS
                                if getattr(candidate, f, None)
                            ],
                        },
                    )
                )
            else:
                stats.unchanged += 1

        except Exception as e:  # noqa: BLE001
            stats.failed += 1
            db.add(
                PipelineEvent(
                    entity_type="job",
                    entity_id=job.id,
                    event_name="backfill_failed",
                    details={
                        "error_type": type(e).__name__,
                        "message": str(e)[:500],
                    },
                )
            )

    db.commit()

    # Rescore the touched jobs so ranking_score reflects the freshly filled
    # remote_type / description etc.
    if then_rescore and touched_ids:
        sight_map = ranker_mod._gather_sighting_stats(db, touched_ids)
        for jid in touched_ids:
            job = db.get(Job, jid)
            if job is None:
                continue
            count, domains = sight_map.get(jid, (1, []))
            try:
                result = ranker_mod.score_job(
                    job, sighting_count=count, sighting_domains=domains
                )
            except Exception:  # noqa: BLE001
                continue
            job.ranking_score = result.ranking_score
            job.quality_score = result.quality_score
            db.add(
                JobScore(
                    job_id=jid,
                    score=result.ranking_score,
                    bucket=result.bucket,
                    rationale=result.rationale,
                    hidden_gem=result.hidden_gem,
                    freshness_score=result.freshness_score,
                    fit_score=result.fit_score,
                )
            )
            stats.rescored += 1

        db.commit()

    return stats
