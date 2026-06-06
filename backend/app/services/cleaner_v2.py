"""Cleaner v2 — canonical-job decision engine.

Input:  a RawJobEvent row (raw_payload dict + provider + source_url)
Output: a CleanerDecision describing what to do with it.

Contract:
- Collectors do not dedupe. Cleaner decides.
- A duplicate must NOT create a second visible job. It updates last_seen_at
  on the canonical and adds a JobSourceSighting.
- Matching runs in three tiers (strong / medium / weak). The first tier
  that returns a match wins.

This module intentionally owns *decision* logic only. The importer is
responsible for applying the decision (inserting rows, updating fields).
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.job import Job
from ..models.raw_job_event import RawJobEvent
from .normalization import (
    description_hash,
    normalize_company,
    normalize_location,
    normalize_remote_type,
    normalize_title,
)
from .url_canonicalize import canonicalize_url, source_domain


_INTAKE_MAX_AGE_SENTINEL = object()
_intake_max_listing_age_ctx: ContextVar[Any] = ContextVar(
    "intake_max_listing_age_ctx", default=_INTAKE_MAX_AGE_SENTINEL
)


def _effective_intake_max_listing_age_days() -> int | None:
    v = _intake_max_listing_age_ctx.get()
    if v is _INTAKE_MAX_AGE_SENTINEL:
        return get_settings().intake_max_listing_age_days
    return v


@contextmanager
def intake_max_listing_age_run_override(max_days: int | None):
    """Override listing-age gate for :func:`decide` inside this block only.

    - ``None`` — disable the gate (no rejection by listing age).
    - ``int`` >= 1 — reject **new** canonical rows when the parsed listing date
      is older than this many days.
    """
    token = _intake_max_listing_age_ctx.set(max_days)
    try:
        yield
    finally:
        _intake_max_listing_age_ctx.reset(token)


class CleanerDecisionType(str, Enum):
    NEW_CANONICAL = "new_canonical"
    MATCHED_EXISTING = "matched_existing"
    POSSIBLE_DUPLICATE_REVIEW = "possible_duplicate_review"
    REJECTED_LOW_QUALITY = "rejected_low_quality"


@dataclass
class NormalizedCandidate:
    """Flat, normalized view of a raw_job_event ready for matching/insert."""
    provider: str
    external_job_id: Optional[str]

    company_name: str
    normalized_company_name: str

    title: str
    normalized_title: str

    location: Optional[str]
    normalized_location: str
    remote_type: Optional[str]

    apply_url: str
    canonical_apply_url: str
    source_domain: str

    description_clean: Optional[str]
    description_hash: Optional[str]

    salary_text: Optional[str]
    employment_type: Optional[str]


@dataclass
class CleanerDecision:
    decision: CleanerDecisionType
    candidate: Optional[NormalizedCandidate] = None
    matched_job_id: Optional[uuid.UUID] = None
    match_tier: Optional[str] = None  # "tier1" | "tier2" | "tier3"
    # For review: list of possible existing job_ids this might collide with
    candidate_job_ids: list[uuid.UUID] = field(default_factory=list)
    reason: Optional[str] = None


# ----------------------------------------------------------------------------
# Normalization
# ----------------------------------------------------------------------------

def _first_nonempty(*vals: Any) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def normalize_raw_event(raw: RawJobEvent) -> Optional[NormalizedCandidate]:
    """Turn a RawJobEvent into a NormalizedCandidate.

    Returns None if the payload is missing required fields after extraction.
    Keys sniffed from raw_payload are tolerant of multiple collector shapes
    (e.g. JobRow from jobs_collector_v4 and native ATS JSON).
    """
    payload: dict[str, Any] = raw.raw_payload or {}

    company = _first_nonempty(
        payload.get("company_name"),
        payload.get("company"),
    )
    title = _first_nonempty(
        payload.get("job_title"),
        payload.get("title"),
        payload.get("text"),
    )
    apply_url = _first_nonempty(
        payload.get("job_url"),
        payload.get("apply_url"),
        payload.get("hostedUrl"),
        payload.get("absolute_url"),
        raw.source_url,
    )

    if not (company and title and apply_url):
        return None

    location = _first_nonempty(
        payload.get("location"),
        (payload.get("categories") or {}).get("location") if isinstance(payload.get("categories"), dict) else None,
        (payload.get("location_obj") or {}).get("name") if isinstance(payload.get("location_obj"), dict) else None,
    )

    # Gather every field that plausibly carries a remote/hybrid/onsite signal
    # and let `normalize_remote_type` look for keywords across the joined text.
    # Many ATS providers stash the signal in unexpected places (e.g. Lever
    # puts it in `commitment`/`employment_type` like "Full-Time - Remote",
    # Greenhouse sometimes only hints it in the title).
    remote_signal_parts = [
        payload.get("remote_type"),
        payload.get("workplace_type"),
        payload.get("work_location_type"),
        location,
        payload.get("employment_type"),
        payload.get("commitment"),
        title,
    ]
    remote_raw = " | ".join(str(p) for p in remote_signal_parts if p)

    external_job_id = _first_nonempty(
        payload.get("external_job_id"),
        payload.get("id"),
        payload.get("requisition_id"),
    )

    description = _first_nonempty(
        payload.get("description_clean"),
        payload.get("description"),
        payload.get("content"),
    )

    canonical = canonicalize_url(apply_url)
    if not canonical:
        return None

    return NormalizedCandidate(
        provider=raw.provider,
        external_job_id=external_job_id,
        company_name=company,
        normalized_company_name=normalize_company(company),
        title=title,
        normalized_title=normalize_title(title),
        location=location,
        normalized_location=normalize_location(location),
        remote_type=normalize_remote_type(remote_raw),
        apply_url=apply_url,
        canonical_apply_url=canonical,
        source_domain=source_domain(apply_url) or source_domain(raw.source_url),
        description_clean=description,
        description_hash=description_hash(description),
        salary_text=_first_nonempty(payload.get("salary_text"), payload.get("salary")),
        employment_type=_first_nonempty(
            payload.get("employment_type"),
            payload.get("commitment"),
        ),
    )


# ----------------------------------------------------------------------------
# Listing age (optional global gate for NEW_CANONICAL only)
# ----------------------------------------------------------------------------

_DATE_KEYS_ORDERED: tuple[str, ...] = (
    "jobstash_date_posted_utc",
    "released_date",
    "releasedDate",
    "updated_at",
    "datePosted",
    "date_posted",
    "posted_at",
    "firstPublishedDate",
    "created_at",
)


def _coerce_payload_datetime(val: Any) -> Optional[datetime]:
    """Parse common collector date shapes to UTC-aware datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        ts = float(val)
        if ts > 1e12:  # ms
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    s = str(val).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            d = datetime.strptime(s[:10], "%Y-%m-%d").date()
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def listing_reference_datetime(payload: dict[str, Any]) -> Optional[datetime]:
    """Best-effort listing/posting time from raw_payload (not collected_at)."""
    for k in _DATE_KEYS_ORDERED:
        dt = _coerce_payload_datetime(payload.get(k))
        if dt is not None:
            return dt
    nai = payload.get("native_api_item")
    if isinstance(nai, dict):
        for k in _DATE_KEYS_ORDERED:
            dt = _coerce_payload_datetime(nai.get(k))
            if dt is not None:
                return dt
    return None


# ----------------------------------------------------------------------------
# Quality gates
# ----------------------------------------------------------------------------

_MIN_TITLE_LEN = 3
_MAX_TITLE_LEN = 256


def _is_low_quality(c: NormalizedCandidate) -> Optional[str]:
    """Return a reason string if this candidate should be rejected, else None."""
    if not c.normalized_title or len(c.normalized_title) < _MIN_TITLE_LEN:
        return "title_too_short"
    if len(c.title) > _MAX_TITLE_LEN:
        return "title_too_long"
    if not c.normalized_company_name:
        return "missing_company"
    if not c.canonical_apply_url:
        return "missing_apply_url"
    return None


# ----------------------------------------------------------------------------
# Matching tiers
# ----------------------------------------------------------------------------

_WEAK_MATCH_WINDOW = timedelta(days=45)


def _tier1_strong_match(db: Session, c: NormalizedCandidate) -> Optional[uuid.UUID]:
    """Same provider+external_job_id OR same canonical_apply_url."""
    if c.external_job_id:
        stmt = select(Job.id).where(
            Job.provider == c.provider,
            Job.external_job_id == c.external_job_id,
        )
        hit = db.execute(stmt).scalar_one_or_none()
        if hit:
            return hit

    stmt = select(Job.id).where(Job.canonical_apply_url == c.canonical_apply_url)
    return db.execute(stmt).scalar_one_or_none()


def _tier2_medium_match(db: Session, c: NormalizedCandidate) -> list[uuid.UUID]:
    """Same normalized company + normalized title + (loose) location/remote.

    Returns all candidate ids — the caller decides exact vs review.
    """
    if not c.normalized_company_name or not c.normalized_title:
        return []
    stmt = select(Job.id).where(
        Job.normalized_company_name == c.normalized_company_name,
        Job.normalized_title == c.normalized_title,
        Job.is_active.is_(True),
    )
    ids = list(db.execute(stmt).scalars().all())
    if not ids:
        return []

    if c.remote_type or c.normalized_location:
        refined_stmt = select(Job.id).where(
            Job.id.in_(ids),
        )
        if c.remote_type:
            refined_stmt = refined_stmt.where(
                (Job.remote_type == c.remote_type) | (Job.remote_type.is_(None))
            )
        refined = list(db.execute(refined_stmt).scalars().all())
        if refined:
            return refined
    return ids


def _tier3_weak_match(db: Session, c: NormalizedCandidate) -> list[uuid.UUID]:
    """Description hash equality + recent posting window + same company."""
    if not c.description_hash or not c.normalized_company_name:
        return []
    cutoff = datetime.now(timezone.utc) - _WEAK_MATCH_WINDOW
    stmt = select(Job.id).where(
        Job.normalized_company_name == c.normalized_company_name,
        Job.description_hash == c.description_hash,
        Job.last_seen_at >= cutoff,
    )
    return list(db.execute(stmt).scalars().all())


# ----------------------------------------------------------------------------
# Public entrypoint
# ----------------------------------------------------------------------------

def decide(db: Session, raw: RawJobEvent) -> CleanerDecision:
    """Decide what to do with a single raw_job_event."""
    candidate = normalize_raw_event(raw)
    if candidate is None:
        return CleanerDecision(
            decision=CleanerDecisionType.REJECTED_LOW_QUALITY,
            reason="missing_required_fields",
        )

    low_q = _is_low_quality(candidate)
    if low_q:
        return CleanerDecision(
            decision=CleanerDecisionType.REJECTED_LOW_QUALITY,
            candidate=candidate,
            reason=low_q,
        )

    # Tier 1 — strong match
    t1 = _tier1_strong_match(db, candidate)
    if t1:
        return CleanerDecision(
            decision=CleanerDecisionType.MATCHED_EXISTING,
            candidate=candidate,
            matched_job_id=t1,
            match_tier="tier1",
        )

    # Tier 2 — medium match
    t2 = _tier2_medium_match(db, candidate)
    if len(t2) == 1:
        return CleanerDecision(
            decision=CleanerDecisionType.MATCHED_EXISTING,
            candidate=candidate,
            matched_job_id=t2[0],
            match_tier="tier2",
        )
    if len(t2) > 1:
        return CleanerDecision(
            decision=CleanerDecisionType.POSSIBLE_DUPLICATE_REVIEW,
            candidate=candidate,
            candidate_job_ids=t2,
            match_tier="tier2",
            reason="multiple_tier2_matches",
        )

    # Tier 3 — weak match
    t3 = _tier3_weak_match(db, candidate)
    if len(t3) == 1:
        return CleanerDecision(
            decision=CleanerDecisionType.POSSIBLE_DUPLICATE_REVIEW,
            candidate=candidate,
            candidate_job_ids=t3,
            match_tier="tier3",
            reason="tier3_desc_hash_match",
        )
    if len(t3) > 1:
        return CleanerDecision(
            decision=CleanerDecisionType.POSSIBLE_DUPLICATE_REVIEW,
            candidate=candidate,
            candidate_job_ids=t3,
            match_tier="tier3",
            reason="multiple_tier3_matches",
        )

    max_days = _effective_intake_max_listing_age_days()
    if max_days is not None and max_days > 0:
        posted = listing_reference_datetime(raw.raw_payload or {})
        if posted is not None:
            if datetime.now(timezone.utc) - posted > timedelta(days=max_days):
                return CleanerDecision(
                    decision=CleanerDecisionType.REJECTED_LOW_QUALITY,
                    candidate=candidate,
                    reason="listing_exceeds_max_age_days",
                )

    return CleanerDecision(
        decision=CleanerDecisionType.NEW_CANONICAL,
        candidate=candidate,
    )
