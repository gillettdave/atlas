"""Ranker v2 — description-side fit signals (Sprint v2).

Builds per-profile sparse text vectors from:
- **Positive** feedback jobs (saved / applied / interviewed / clicked):
  aggregate ``description_clean`` into a TF–IDF-style reference vector.
- **Dismissed / rejected** rows with **notes** (+ job title): mine tokens for
  ``suggested_keywords``. Operators promote selected tokens via
  ``POST /profiles/{slug}/promote-suggested-keywords`` (typically after rebuild).

No sklearn dependency — small corpora only; vectors are L2-normalized dicts.
"""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.job import Job
from ..models.job_feedback import JobFeedback
from ..models.user_profile import UserProfile

_POSITIVE = frozenset({"saved", "applied", "interviewed", "clicked"})
_NEGATIVE = frozenset({"dismissed", "rejected"})

_STOPWORDS: frozenset[str] = frozenset(
    """
    the a an and or to of in for on with at by from as is was are were been be
    this that these those it its we you our your they their not no yes all any
    some more most other so if than then into out up down over under just only
    also can will would could should may might must have has had do does did
    get got make made work working worked job jobs role team company about
    looking looking_for great good best strong experience years year
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,48}", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [
        m.group(0).lower()
        for m in _TOKEN_RE.finditer(text.lower())
        if m.group(0).lower() not in _STOPWORDS
    ]


def _l2_normalize(vec: dict[str, float]) -> dict[str, float]:
    n = math.sqrt(sum(v * v for v in vec.values()))
    if n <= 0:
        return {}
    return {t: v / n for t, v in vec.items()}


def aggregate_tfidf_reference(docs: list[str]) -> dict[str, float]:
    """One reference vector: sum TF×IDF over documents, then L2-normalize."""
    tokenized = [tokenize(d) for d in docs if d and d.strip()]
    n_docs = len(tokenized)
    if n_docs == 0:
        return {}

    doc_freq: dict[str, int] = {}
    for toks in tokenized:
        for t in set(toks):
            doc_freq[t] = doc_freq.get(t, 0) + 1

    agg: dict[str, float] = {}
    for toks in tokenized:
        tf = Counter(toks)
        for term, c in tf.items():
            df = max(1, doc_freq.get(term, 1))
            idf = math.log((n_docs + 1) / (df + 1)) + 1.0
            agg[term] = agg.get(term, 0.0) + float(c) * idf

    return _l2_normalize(agg)


def trim_vector(vec: dict[str, float], max_terms: int) -> dict[str, float]:
    if len(vec) <= max_terms:
        return vec
    top = sorted(vec.items(), key=lambda x: -x[1])[:max_terms]
    return _l2_normalize(dict(top))


def cosine_sparse(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # Assume both L2-normalized → dot product is cosine.
    return float(sum(a[t] * b[t] for t in a if t in b))


def job_description_vector(description_clean: str) -> dict[str, float]:
    toks = tokenize(description_clean or "")
    if not toks:
        return {}
    tf = Counter(toks)
    raw = {t: float(c) for t, c in tf.items()}
    return _l2_normalize(raw)


def mine_keywords_from_notes(
    db: Session,
    profile_id: uuid.UUID,
    *,
    max_rows: int = 400,
) -> list[str]:
    stmt = (
        select(JobFeedback.note, Job.title)
        .join(Job, Job.id == JobFeedback.job_id)
        .where(JobFeedback.profile_id == profile_id)
        .where(JobFeedback.action.in_(_NEGATIVE))
        .where(JobFeedback.note.isnot(None))
        .where(JobFeedback.note != "")
        .order_by(JobFeedback.created_at.desc())
        .limit(max_rows)
    )
    rows = db.execute(stmt).all()
    bag: Counter[str] = Counter()
    for note, title in rows:
        blob = f"{note or ''} {title or ''}"
        for t in tokenize(blob):
            if len(t) >= 4:
                bag[t] += 1
    return [w for w, _ in bag.most_common(25)]


def build_ranker_text_signals(
    db: Session,
    profile: UserProfile,
    *,
    max_positive_jobs: int = 400,
    max_note_rows: int = 400,
) -> dict[str, Any]:
    """Compute signals, assign ``profile.ranker_text_signals``, flush (caller commits)."""

    s = get_settings()
    max_terms = int(s.ranker_text_signals_max_vector_terms)

    pos_stmt = (
        select(JobFeedback.job_id)
        .where(JobFeedback.profile_id == profile.id)
        .where(JobFeedback.action.in_(_POSITIVE))
        .distinct()
        .limit(max_positive_jobs)
    )
    job_ids = [row[0] for row in db.execute(pos_stmt).all()]

    docs: list[str] = []
    if job_ids:
        jrows = db.execute(
            select(Job.description_clean).where(Job.id.in_(job_ids))
        ).all()
        for (dc,) in jrows:
            if dc and len(dc.strip()) > 30:
                docs.append(dc)

    ref = aggregate_tfidf_reference(docs)
    ref = trim_vector(ref, max_terms)
    suggested = mine_keywords_from_notes(
        db, profile.id, max_rows=max_note_rows
    )

    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "version": 1,
        "built_at": now.isoformat(timespec="seconds"),
        "positive_job_ids_scanned": len(job_ids),
        "positive_docs_used": len(docs),
        "ref_dim": len(ref),
        "ref_vector": ref,
        "suggested_keywords": suggested,
    }
    profile.ranker_text_signals = payload
    db.add(profile)
    db.flush()
    return payload
