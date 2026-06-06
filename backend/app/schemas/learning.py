"""Schemas for Sprint I.1 — learned weight nudges."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LearnRequest(BaseModel):
    """POST /profiles/{slug}/learn body. All fields optional."""

    dry_run: bool = Field(
        default=True,
        description=(
            "When true (default) the response shows the proposed nudges "
            "but does not persist. Set false to apply."
        ),
    )
    min_samples: int = Field(default=3, ge=1, le=50)
    learning_rate: float = Field(default=0.5, ge=0.0, le=2.0)
    max_step: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_min: float = Field(default=0.1, ge=0.0, le=5.0)
    weight_max: float = Field(default=3.0, ge=0.0, le=5.0)
    max_events: int = Field(default=2000, ge=1, le=50000)
    feedback_decay_half_life_days: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=730.0,
        description=(
            "Half-life in days for exponentially down-weighting older labeled jobs "
            "(omit to use ATLAS_LEARNING_FEEDBACK_DECAY_HALF_LIFE_DAYS). 0 disables."
        ),
    )


class ComponentDelta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component: str
    positive_count: int
    negative_count: int
    positive_mean: float
    negative_mean: float
    signal: float
    current_weight: float
    nudge: float
    new_weight: float
    applied: bool
    reason_skipped: Optional[str] = None


class LearningReportOut(BaseModel):
    profile_slug: str
    events_considered: int
    jobs_unique: int
    positive_events: int
    negative_events: int
    feedback_decay_half_life_days_used: float = 0.0
    applied: bool
    reason_skipped: Optional[str] = None
    components: list[ComponentDelta]
