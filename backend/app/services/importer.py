"""Importer service — applies cleaner_v2 decisions to the database.

Flow per raw_job_event:
    pending -> parsed -> normalized -> deduped -> stored
    (optionally) -> needs_review | rejected | failed

Responsibilities:
- Pull a batch of raw_job_events where parse_status == 'pending'.
- For each event call cleaner_v2.decide(db, event).
- Apply the decision:
    NEW_CANONICAL              -> insert Job, insert primary Sighting, mark stored
    MATCHED_EXISTING           -> update last_seen_at, insert/upsert Sighting
    POSSIBLE_DUPLICATE_REVIEW  -> mark needs_review, log pipeline_event
    REJECTED_LOW_QUALITY       -> mark rejected, log pipeline_event
- Emit PipelineEvent rows for every state change.

The importer is synchronous (one DB session per batch). Concurrency is
handled at the collector-runner level, not here.
"""
from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.ingestion_run import IngestionRun
from ..models.job import Job
from ..models.job_source_sighting import JobSourceSighting
from ..models.pipeline_event import PipelineEvent
from ..models.raw_job_event import RawJobEvent
from . import cleaner_v2
from .cleaner_v2 import CleanerDecision, CleanerDecisionType, NormalizedCandidate
from .url_canonicalize import source_domain


@dataclass
class ImporterStats:
    processed: int = 0
    new_canonical: int = 0
    matched_existing: int = 0
    possible_duplicate_review: int = 0
    rejected_low_quality: int = 0
    failed: int = 0


def _log_event(
    db: Session,
    entity_type: str,
    entity_id: Optional[uuid.UUID],
    event_name: str,
    details: Optional[dict] = None,
) -> None:
    db.add(
        PipelineEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            event_name=event_name,
            details=details,
        )
    )


def _source_kind_for(provider: str, domain: str) -> str:
    """Classify a sighting by provider/domain for future sponsor routing."""
    p = (provider or "").lower()
    d = (domain or "").lower()
    if p in {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "teamtailor", "kula", "recruitee"}:
        return f"ats_{p}"
    if "jobstash" in d:
        return "aggregator_jobstash"
    if "cryptojobslist" in d:
        return "aggregator_cryptojobslist"
    if p in {"native_jobs_page", "jobs_page"}:
        return "native_jobs_page"
    return "other"


def _insert_new_canonical(
    db: Session, raw: RawJobEvent, c: NormalizedCandidate
) -> Job:
    now = datetime.now(timezone.utc)
    def _trunc(value: str | None, limit: int) -> str | None:
        return value[:limit] if value and len(value) > limit else value

    job = Job(
        provider=c.provider,
        external_job_id=_trunc(c.external_job_id, 256),
        company_name=_trunc(c.company_name, 256),
        normalized_company_name=_trunc(c.normalized_company_name, 256),
        title=_trunc(c.title, 256),
        normalized_title=_trunc(c.normalized_title, 256),
        location=_trunc(c.location, 256),
        remote_type=_trunc(c.remote_type, 64),
        apply_url=_trunc(c.apply_url, 2048),
        canonical_apply_url=_trunc(c.canonical_apply_url, 2048),
        description_clean=c.description_clean,
        description_hash=c.description_hash,
        salary_text=_trunc(c.salary_text, 256),
        employment_type=_trunc(c.employment_type, 64),
        first_seen_at=now,
        last_seen_at=now,
        is_active=True,
    )
    db.add(job)
    db.flush()  # need job.id

    kind = _source_kind_for(c.provider, c.source_domain)
    db.add(
        JobSourceSighting(
            job_id=job.id,
            source_domain=c.source_domain,
            source_kind=kind,
            source_url=raw.source_url,
            provider=c.provider,
            apply_url=c.apply_url,
            is_primary=True,
            source_priority=100,
        )
    )
    return job


def _upsert_sighting(
    db: Session, job_id: uuid.UUID, raw: RawJobEvent, c: NormalizedCandidate
) -> None:
    """Insert a sighting if we don't already have one from the same source+url."""
    stmt = (
        select(JobSourceSighting.id)
        .where(
            JobSourceSighting.job_id == job_id,
            JobSourceSighting.source_url == raw.source_url,
            JobSourceSighting.provider == c.provider,
        )
        .limit(1)
    )
    if db.execute(stmt).scalar_one_or_none():
        return

    kind = _source_kind_for(c.provider, c.source_domain)
    db.add(
        JobSourceSighting(
            job_id=job_id,
            source_domain=c.source_domain,
            source_kind=kind,
            source_url=raw.source_url,
            provider=c.provider,
            apply_url=c.apply_url,
            is_primary=False,
            source_priority=50,
        )
    )


def _apply_decision(
    db: Session, raw: RawJobEvent, decision: CleanerDecision, stats: ImporterStats
) -> None:
    if decision.decision == CleanerDecisionType.REJECTED_LOW_QUALITY:
        raw.parse_status = "rejected"
        stats.rejected_low_quality += 1
        _log_event(
            db, "raw_job_event", raw.id, "rejected",
            {"reason": decision.reason},
        )
        return

    if decision.decision == CleanerDecisionType.POSSIBLE_DUPLICATE_REVIEW:
        raw.parse_status = "needs_review"
        stats.possible_duplicate_review += 1
        _log_event(
            db, "raw_job_event", raw.id, "needs_review",
            {
                "tier": decision.match_tier,
                "reason": decision.reason,
                "candidates": [str(i) for i in decision.candidate_job_ids],
            },
        )
        return

    c = decision.candidate
    assert c is not None, "candidate must be set for match/new decisions"

    if decision.decision == CleanerDecisionType.MATCHED_EXISTING:
        job = db.get(Job, decision.matched_job_id)
        if job is None:
            # The matched job disappeared mid-flight; treat as new to be safe.
            _insert_new_canonical(db, raw, c)
            raw.parse_status = "stored"
            stats.new_canonical += 1
            _log_event(
                db, "raw_job_event", raw.id, "stored_after_missing_match",
                {"tier": decision.match_tier},
            )
            return

        job.last_seen_at = datetime.now(timezone.utc)
        job.is_active = True
        _upsert_sighting(db, job.id, raw, c)

        raw.parse_status = "stored"
        stats.matched_existing += 1
        _log_event(
            db, "raw_job_event", raw.id, "matched_existing",
            {"job_id": str(job.id), "tier": decision.match_tier},
        )
        return

    # NEW_CANONICAL
    job = _insert_new_canonical(db, raw, c)
    raw.parse_status = "stored"
    stats.new_canonical += 1
    _log_event(
        db, "raw_job_event", raw.id, "new_canonical",
        {"job_id": str(job.id)},
    )


def process_pending(
    db: Session,
    limit: int = 500,
    ingestion_run_id: Optional[uuid.UUID] = None,
    intake_max_listing_age_days: Optional[int] = None,
) -> ImporterStats:
    """Process up to `limit` raw_job_events with parse_status='pending'.

    ``intake_max_listing_age_days`` (optional, import batch only):
    - ``None`` — use :attr:`Settings.intake_max_listing_age_days` (env default).
    - ``0`` — disable the listing-age gate for this batch.
    - ``>= 1`` — max age in days for this batch only.
    """
    stats = ImporterStats()

    stmt = select(RawJobEvent).where(RawJobEvent.parse_status == "pending")
    if ingestion_run_id is not None:
        stmt = stmt.where(RawJobEvent.ingestion_run_id == ingestion_run_id)
    stmt = stmt.order_by(RawJobEvent.created_at.asc()).limit(limit)

    events = list(db.execute(stmt).scalars().all())

    ctx = (
        cleaner_v2.intake_max_listing_age_run_override(
            None if intake_max_listing_age_days == 0 else int(intake_max_listing_age_days)
        )
        if intake_max_listing_age_days is not None
        else contextlib.nullcontext()
    )
    with ctx:
        for raw in events:
            stats.processed += 1
            try:
                decision = cleaner_v2.decide(db, raw)
                _apply_decision(db, raw, decision, stats)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                raw.parse_status = "failed_parse"
                stats.failed += 1
                try:
                    _log_event(
                        db, "raw_job_event", raw.id, "failed",
                        {"error_type": type(e).__name__, "message": str(e)[:500]},
                    )
                except Exception:
                    pass

    # Roll up run stats if the batch was scoped to one run.
    if ingestion_run_id is not None and events:
        run = db.get(IngestionRun, ingestion_run_id)
        if run is not None:
            run.rows_inserted = (run.rows_inserted or 0) + stats.new_canonical + stats.matched_existing
            run.rows_failed = (run.rows_failed or 0) + stats.failed + stats.rejected_low_quality

    db.commit()
    return stats
