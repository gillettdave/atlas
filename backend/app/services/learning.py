"""learning - Sprint I.1.

Reads the job_feedback log for a given profile and proposes weight
nudges using a simple, explainable mean-difference heuristic:

For each ranker component C (web3_fit, title_quality, ...):
  - Split feedback events into positive (saved/applied/interviewed/clicked)
    and negative (dismissed/rejected) buckets.
  - For each event, score the underlying job against the profile in
    dry-run mode to recover the per-component raw value.
  - signal(C) = weighted_mean(positive[C])/MAX[C] - weighted_mean(negative[C])/MAX[C]
    (weights default to uniform; optional half-life decay by feedback age)
  - nudge(C)  = clamp(signal * learning_rate, +/- max_step)
  - new_weight(C) = clamp(current_weight * (1 + nudge), weight_min, weight_max)

The algorithm is intentionally simple:
  - No ML dependencies.
  - Explainable: every nudge is attributable to concrete pos/neg means.
  - Safe: a min_samples threshold per class suppresses changes until
    real evidence accumulates.

Default mode is **dry-run** so the operator can preview the report
before persisting. Applying writes the new weights to the profile and
a `pipeline_events.profile_learned` audit row.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.job_feedback import JobFeedback
from ..models.pipeline_event import PipelineEvent
from ..models.user_profile import UserProfile
from . import ranker


logger = logging.getLogger("atlas.learning")


POSITIVE_ACTIONS: frozenset[str] = frozenset(
    {"saved", "applied", "interviewed", "clicked"}
)
NEGATIVE_ACTIONS: frozenset[str] = frozenset({"dismissed", "rejected"})

# Components we actually learn over. Keeping this tuple decoupled from
# ranker._BASE_COMPONENTS lets us include hidden_gem_bonus in learning
# while the ranker's normalization logic keeps the base separate.
LEARNABLE_COMPONENTS: tuple[str, ...] = (
    "web3_fit",
    "title_quality",
    "provider_trust",
    "freshness",
    "remote_fit",
    "duplicate_confidence",
    "description_fit",
    "hidden_gem_bonus",
)


# ---------------------------------------------------------------------------
# Config + report types
# ---------------------------------------------------------------------------

@dataclass
class LearningConfig:
    """Knobs for one learning pass. All optional in API payloads."""

    min_samples: int = 3
    learning_rate: float = 0.5
    max_step: float = 0.2
    weight_min: float = 0.1
    weight_max: float = 3.0
    max_events: int = 2000
    dry_run: bool = True
    # None → ATLAS_LEARNING_FEEDBACK_DECAY_HALF_LIFE_DAYS
    feedback_decay_half_life_days: Optional[float] = None


@dataclass
class ComponentStat:
    component: str
    positive_count: int = 0
    negative_count: int = 0
    positive_mean: float = 0.0
    negative_mean: float = 0.0
    signal: float = 0.0
    current_weight: float = 1.0
    nudge: float = 0.0
    new_weight: float = 1.0
    applied: bool = False
    reason_skipped: Optional[str] = None


@dataclass
class LearningReport:
    profile_slug: str
    events_considered: int = 0
    jobs_unique: int = 0
    positive_events: int = 0
    negative_events: int = 0
    feedback_decay_half_life_days_used: float = 0.0
    components: list[ComponentStat] = field(default_factory=list)
    applied: bool = False
    reason_skipped: Optional[str] = None
    config: LearningConfig = field(default_factory=LearningConfig)


# ---------------------------------------------------------------------------
# Time decay + weighted means
# ---------------------------------------------------------------------------

def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def decay_weight_for_feedback_age(
    anchor_at: datetime,
    *,
    now: datetime,
    half_life_days: float,
) -> float:
    """Contribution weight ``0.5 ** (age_days / half_life)`` (1.0 if half-life 0)."""
    if half_life_days <= 0:
        return 1.0
    age_days = (_utc(now) - _utc(anchor_at)).total_seconds() / 86400.0
    return float(0.5 ** (age_days / float(half_life_days)))


def _effective_decay_half_life_days(cfg: LearningConfig) -> float:
    """Per-request override, else ATLAS_LEARNING_FEEDBACK_DECAY_HALF_LIFE_DAYS."""
    if cfg.feedback_decay_half_life_days is not None:
        return max(0.0, float(cfg.feedback_decay_half_life_days))
    return max(0.0, float(get_settings().learning_feedback_decay_half_life_days))


def _weighted_mean(samples: list[tuple[float, float]]) -> tuple[float, float]:
    """(mean, weight_sum). Weight sum is informational when decay is enabled."""
    if not samples:
        return 0.0, 0.0
    wsum = sum(w for _, w in samples)
    if wsum <= 0:
        return 0.0, 0.0
    return sum(v * w for v, w in samples) / wsum, wsum


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

def _load_labeled_jobs(
    db: Session, profile_id: uuid.UUID, *, max_events: int
) -> tuple[dict[uuid.UUID, tuple[int, datetime]], int, int]:
    """Return {job_id -> (label, anchor_created_at)}, plus raw event totals.

    Label rule matches the historical implementation: traverse feedback
    ``created_at DESC``; negative writes overwrite positive; ``setdefault``
    keeps negatives. ``anchor_created_at`` is the timestamp carried on each
    final assignment (last writer per rule path). This timestamp drives
    decay weights for that job row in the aggregates.
    """
    stmt = (
        select(JobFeedback.job_id, JobFeedback.action, JobFeedback.created_at)
        .where(JobFeedback.profile_id == profile_id)
        .order_by(JobFeedback.created_at.desc())
        .limit(max_events)
    )
    rows = db.execute(stmt).all()

    labels: dict[uuid.UUID, tuple[int, datetime]] = {}
    positive_total = 0
    negative_total = 0
    for job_id, action, created_at in rows:
        if action in NEGATIVE_ACTIONS:
            labels[job_id] = (-1, created_at)
            negative_total += 1
        elif action in POSITIVE_ACTIONS:
            positive_total += 1
            if job_id not in labels:
                labels[job_id] = (+1, created_at)

    return labels, positive_total, negative_total


# ---------------------------------------------------------------------------
# Core pass
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def learn_from_feedback(
    db: Session,
    profile: UserProfile,
    *,
    config: Optional[LearningConfig] = None,
) -> LearningReport:
    """Produce a LearningReport. When `config.dry_run=False`, also
    persists the new weights to the profile and writes an audit event.

    Never mutates feedback rows or job scores.
    """
    cfg = config or LearningConfig()
    now = datetime.now(timezone.utc)
    half_life = _effective_decay_half_life_days(cfg)

    labels, positive_total, negative_total = _load_labeled_jobs(
        db, profile.id, max_events=cfg.max_events
    )

    report = LearningReport(
        profile_slug=profile.slug,
        events_considered=positive_total + negative_total,
        jobs_unique=len(labels),
        positive_events=positive_total,
        negative_events=negative_total,
        feedback_decay_half_life_days_used=half_life,
        config=cfg,
    )

    if not labels:
        report.reason_skipped = "no feedback events for this profile yet"
        return report

    # Score each labeled job against the current profile to get the
    # per-component raw values.
    pos_values: dict[str, list[tuple[float, float]]] = {
        c: [] for c in LEARNABLE_COMPONENTS
    }
    neg_values: dict[str, list[tuple[float, float]]] = {
        c: [] for c in LEARNABLE_COMPONENTS
    }

    for job_id, (label, anchor_at) in labels.items():
        result = ranker.score_job_dry(db, job_id, profile=profile, now=now)
        if result is None:
            continue
        contrib_w = decay_weight_for_feedback_age(
            anchor_at, now=now, half_life_days=half_life
        )
        bucket = pos_values if label > 0 else neg_values
        for c in LEARNABLE_COMPONENTS:
            raw = result.details.get(c)
            if raw is None:
                continue
            try:
                bucket[c].append((float(raw), contrib_w))
            except (TypeError, ValueError):
                continue

    current_weights = dict(ranker.DEFAULT_COMPONENT_WEIGHTS)
    current_weights.update(profile.weights or {})

    any_applied = False
    new_weights = dict(current_weights)

    for comp in LEARNABLE_COMPONENTS:
        max_c = ranker.COMPONENT_MAX[comp]
        pos_vals = pos_values[comp]
        neg_vals = neg_values[comp]
        cw = float(current_weights.get(comp, 1.0))

        stat = ComponentStat(
            component=comp,
            positive_count=len(pos_vals),
            negative_count=len(neg_vals),
            current_weight=round(cw, 4),
            new_weight=round(cw, 4),
        )
        if pos_vals:
            pm, _ = _weighted_mean(pos_vals)
            stat.positive_mean = round(pm, 3)
        if neg_vals:
            nm, _ = _weighted_mean(neg_vals)
            stat.negative_mean = round(nm, 3)

        if stat.positive_count < cfg.min_samples or stat.negative_count < cfg.min_samples:
            stat.reason_skipped = (
                f"insufficient samples "
                f"(need {cfg.min_samples} per class; "
                f"have pos={stat.positive_count}, neg={stat.negative_count})"
            )
            report.components.append(stat)
            continue

        # Normalize means to [0, 1] against the component's max before
        # differencing so signal is comparable across components.
        pos_norm = stat.positive_mean / max_c if max_c else 0.0
        neg_norm = stat.negative_mean / max_c if max_c else 0.0
        signal = pos_norm - neg_norm
        nudge = _clamp(signal * cfg.learning_rate, -cfg.max_step, cfg.max_step)
        new_w = _clamp(cw * (1.0 + nudge), cfg.weight_min, cfg.weight_max)

        stat.signal = round(signal, 4)
        stat.nudge = round(nudge, 4)
        stat.new_weight = round(new_w, 4)
        stat.applied = not cfg.dry_run and abs(new_w - cw) > 1e-6

        if stat.applied:
            new_weights[comp] = new_w
            any_applied = True

        report.components.append(stat)

    # Persist if requested and something actually changed.
    if not cfg.dry_run and any_applied:
        profile.weights = new_weights
        profile.updated_at = now
        db.add(
            PipelineEvent(
                entity_type="user_profile",
                entity_id=profile.id,
                event_name="profile_learned",
                details={
                    "profile_slug": profile.slug,
                    "events_considered": report.events_considered,
                    "jobs_unique": report.jobs_unique,
                    "feedback_decay_half_life_days": half_life,
                    "learning_rate": cfg.learning_rate,
                    "max_step": cfg.max_step,
                    "min_samples": cfg.min_samples,
                    "deltas": {
                        s.component: {
                            "from": s.current_weight,
                            "to": s.new_weight,
                            "nudge": s.nudge,
                            "signal": s.signal,
                        }
                        for s in report.components
                        if s.applied
                    },
                },
            )
        )
        db.commit()
        db.refresh(profile)
        report.applied = True
    else:
        if cfg.dry_run:
            report.reason_skipped = "dry_run=True; no changes persisted"
        elif not any_applied:
            report.reason_skipped = "no component met sample threshold or produced a non-zero nudge"

    return report
