"""LLM-based job qualification scorer.

Lazy, cached per (job, profile) pair. Called at digest-time, not import-time.

Architecture:
- score_qualification(db, job, profile_id, facts) → float 0-10
- Checks job_scores for a cached result (< 7 days old, same description hash)
- On cache miss: calls OpenAI, stores result on job_scores row
- Jobs without descriptions return 5.0 (neutral — benefit of the doubt)
- Jobs where LLM scores < 3 are filtered from digests

Score interpretation:
  0-2  Clearly unqualified (missing core required skills)
  3-4  Partially qualified (some gaps)
  5-6  Likely qualified (soft match, light on specifics)
  7-8  Strong fit (background maps well)
  9-10 Exceptional fit (directly relevant experience)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..config import get_settings, Settings
from ..models.job import Job
from ..models.job_score import JobScore
from ..models.career_memory import CareerFact
from ..services.ai import AIProviderMisconfigured, get_chat_completer

logger = logging.getLogger(__name__)

_CACHE_TTL_DAYS = 7
_MIN_QUALIFY_SCORE = 3.0   # below this → excluded from digest
_NO_DESCRIPTION_SCORE = 5.0  # neutral when no description available
_FACTS_MAX_CHARS = 3_000
_DESC_MAX_CHARS = 4_000


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a job qualification screener. Given a job description and a candidate's career facts, \
score how well-qualified the candidate is on a scale of 0-10.

Scoring guide:
0-2: Candidate clearly lacks core required skills (e.g. job requires Rust expertise, candidate has none)
3-4: Candidate meets some requirements but is missing key ones
5-6: Candidate meets most soft requirements, light on technical specifics — plausible stretch
7-8: Candidate is a solid fit — background maps well to what the job needs
9-10: Exceptional fit — candidate's experience directly and specifically matches the role

Be decisive. If the job's primary requirement is a specific hard skill the candidate has no evidence of, score 0-2.
If the candidate's profile clearly matches the role's domain, responsibilities, and seniority, score 7+.

Return ONLY valid JSON with this exact shape:
{"score": <integer 0-10>, "reasoning": "<one sentence explaining the score>", "missing": ["<key gap if any>", ...]}

No other text. No markdown. Just the JSON object.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _description_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _summarise_facts(facts: list[CareerFact]) -> str:
    """Render approved facts as a compact bullet list, truncated to fit context."""
    lines = []
    for f in facts:
        lines.append(f"- {f.fact_text}")
    text = "\n".join(lines)
    return text[:_FACTS_MAX_CHARS]


def _parse_llm_response(raw: str) -> tuple[float, str, list[str]]:
    """Parse LLM JSON response → (score, reasoning, missing).

    Falls back gracefully on malformed output.
    """
    try:
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(cleaned)
        score = max(0.0, min(10.0, float(data.get("score", 5))))
        reasoning = str(data.get("reasoning", "")).strip()[:500]
        missing = [str(m) for m in (data.get("missing") or [])[:5]]
        return score, reasoning, missing
    except Exception:
        logger.warning("qualification_scorer: failed to parse LLM response: %r", raw[:200])
        return 5.0, "Could not parse qualification response.", []


# ---------------------------------------------------------------------------
# Cache check
# ---------------------------------------------------------------------------

def _find_cached_score(
    db: Session,
    job: Job,
    profile_id: Optional[uuid.UUID],
    desc_hash: Optional[str],
) -> Optional[tuple[float, str]]:
    """Return (score, reasoning) if a fresh cached result exists, else None."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_CACHE_TTL_DAYS)

    row = (
        db.query(JobScore)
        .filter(
            JobScore.job_id == job.id,
            JobScore.profile_id == profile_id,
            JobScore.qualification_score.is_not(None),
            JobScore.qualification_scored_at >= cutoff,
        )
        .order_by(JobScore.qualification_scored_at.desc())
        .first()
    )
    if row is None:
        return None

    # Invalidate if description has changed since scoring
    if desc_hash and row.description_hash_at_scoring and row.description_hash_at_scoring != desc_hash:
        return None

    return float(row.qualification_score), (row.qualification_reasoning or "")


def _write_cached_score(
    db: Session,
    job: Job,
    profile_id: Optional[uuid.UUID],
    score: float,
    reasoning: str,
    desc_hash: Optional[str],
) -> None:
    """Persist qualification result on the most recent job_scores row, or create one."""
    row = (
        db.query(JobScore)
        .filter(JobScore.job_id == job.id, JobScore.profile_id == profile_id)
        .order_by(JobScore.created_at.desc())
        .first()
    )
    if row is None:
        # No score row yet — we can't create a full one here (no ranker result)
        # so just skip caching; it'll be scored again next digest.
        return

    row.qualification_score = score
    row.qualification_reasoning = reasoning
    row.qualification_scored_at = datetime.now(timezone.utc)
    row.description_hash_at_scoring = desc_hash
    db.flush()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def score_qualification(
    db: Session,
    job: Job,
    profile_id: Optional[uuid.UUID],
    facts: list[CareerFact],
    *,
    settings: Optional[Settings] = None,
) -> tuple[float, str]:
    """Return (qualification_score 0-10, reasoning) for a job/profile pair.

    Uses cached result if fresh. Calls LLM on cache miss.
    Jobs without descriptions return (5.0, 'No description available').
    """
    desc = (job.description_clean or "").strip()
    desc_hash = _description_hash(desc) if desc else None

    # No description → neutral score, no LLM call
    if not desc:
        return _NO_DESCRIPTION_SCORE, "No job description available — scored neutral."

    # Check cache
    cached = _find_cached_score(db, job, profile_id, desc_hash)
    if cached is not None:
        logger.debug(
            "qualification_scorer: cache hit job=%s profile=%s score=%.1f",
            job.id, profile_id, cached[0],
        )
        return cached

    # LLM call
    cfg = settings or get_settings()
    try:
        completer = get_chat_completer(cfg)
    except AIProviderMisconfigured:
        logger.warning("qualification_scorer: OpenAI not configured — returning neutral score")
        return _NO_DESCRIPTION_SCORE, "AI qualification scoring not configured."

    facts_text = _summarise_facts(facts) if facts else "(No career facts available)"
    desc_truncated = desc[:_DESC_MAX_CHARS]

    user_content = (
        f"## Job: {job.title} at {job.company_name}\n\n"
        f"### Job Description\n{desc_truncated}\n\n"
        f"### Candidate Career Facts\n{facts_text}"
    )

    try:
        raw = completer.complete(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
        )
        score, reasoning, missing = _parse_llm_response(raw)
        if missing:
            reasoning = f"{reasoning} Missing: {', '.join(missing[:3])}."
    except Exception as exc:
        logger.error("qualification_scorer: LLM call failed: %s", exc)
        return _NO_DESCRIPTION_SCORE, "Qualification scoring failed — scored neutral."

    logger.info(
        "qualification_scorer: scored job=%s (%s @ %s) score=%.1f — %s",
        job.id, job.title, job.company_name, score, reasoning,
    )

    # Cache result
    _write_cached_score(db, job, profile_id, score, reasoning, desc_hash)

    return score, reasoning


# ---------------------------------------------------------------------------
# Bulk scorer for digest candidates
# ---------------------------------------------------------------------------

def score_candidates(
    db: Session,
    jobs: list[Job],
    profile_id: Optional[uuid.UUID],
    *,
    settings: Optional[Settings] = None,
) -> dict[uuid.UUID, tuple[float, str]]:
    """Score a list of digest candidate jobs.

    Returns {job_id: (score, reasoning)} for all jobs.
    Loads the user's approved facts once, then scores each job.
    """
    from ..constants import SEEDED_LOCAL_USER_ID
    from ..models.career_memory import CareerFact

    cfg = settings or get_settings()

    # Load approved facts for this profile's user
    # For now: profile_id maps 1:1 to the seeded user (pre-auth)
    # Post P2.3: resolve user_id from profile_id via profile.user_id
    facts = (
        db.query(CareerFact)
        .filter(
            CareerFact.user_id == SEEDED_LOCAL_USER_ID,
            CareerFact.verification_state == "approved",
        )
        .all()
    )

    results: dict[uuid.UUID, tuple[float, str]] = {}
    for job in jobs:
        score, reasoning = score_qualification(
            db, job, profile_id, facts, settings=cfg
        )
        results[job.id] = (score, reasoning)

    return results
