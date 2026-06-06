"""Schemas for user_profiles (Sprint G)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Canonical weight keys recognised by the ranker. Unknown keys are
# accepted but ignored at scoring time; the UI uses this list to offer
# sliders.
WEIGHT_KEYS: tuple[str, ...] = (
    "web3_fit",
    "title_quality",
    "provider_trust",
    "freshness",
    "remote_fit",
    "duplicate_confidence",
    "description_fit",
    "hidden_gem_bonus",
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,62}[a-z0-9]$|^[a-z0-9]$")


def _validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError(
            "slug must be kebab-case, 1-64 chars, letters/digits/hyphen only"
        )
    return slug


def _validate_weights(weights: dict[str, Any]) -> dict[str, float]:
    """Coerce weights to floats in [0, 5]. Ignore unknown keys silently."""
    cleaned: dict[str, float] = {}
    for k, v in (weights or {}).items():
        if k not in WEIGHT_KEYS:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError) as e:
            raise ValueError(f"weights[{k!r}] must be numeric") from e
        if not (0.0 <= f <= 5.0):
            raise ValueError(f"weights[{k!r}] must be in [0, 5]")
        cleaned[k] = f
    return cleaned


def _validate_keywords(kws: list[str]) -> list[str]:
    if not kws:
        return []
    out: list[str] = []
    for kw in kws:
        if not isinstance(kw, str):
            raise ValueError("keyword must be a string")
        s = kw.strip().lower()
        if not s:
            continue
        if len(s) > 64:
            raise ValueError(f"keyword too long: {s[:24]!r}")
        if s not in out:
            out.append(s)
    return out


class UserProfileCreate(BaseModel):
    slug: str = Field(..., max_length=64)
    display_name: str = Field(..., max_length=128)
    description: Optional[str] = None
    weights: dict[str, float] = Field(default_factory=dict)
    strong_keywords: list[str] = Field(default_factory=list)
    weak_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    preferred_remote: Optional[str] = Field(default=None, max_length=16)
    min_score_threshold: Decimal = Decimal("0")
    is_default: bool = False
    is_active: bool = True

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return _validate_slug(v)

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: dict[str, Any]) -> dict[str, float]:
        return _validate_weights(v)

    @field_validator("strong_keywords", "weak_keywords", "negative_keywords")
    @classmethod
    def _keywords(cls, v: list[str]) -> list[str]:
        return _validate_keywords(v)

    @field_validator("preferred_remote")
    @classmethod
    def _remote(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        low = v.strip().lower()
        if low not in {"remote", "hybrid", "onsite"}:
            raise ValueError(
                "preferred_remote must be one of remote|hybrid|onsite"
            )
        return low


class UserProfileUpdate(BaseModel):
    """All fields optional; only provided fields are updated."""
    display_name: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = None
    weights: Optional[dict[str, float]] = None
    strong_keywords: Optional[list[str]] = None
    weak_keywords: Optional[list[str]] = None
    negative_keywords: Optional[list[str]] = None
    preferred_remote: Optional[str] = Field(default=None, max_length=16)
    min_score_threshold: Optional[Decimal] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: Optional[dict[str, Any]]) -> Optional[dict[str, float]]:
        if v is None:
            return None
        return _validate_weights(v)

    @field_validator("strong_keywords", "weak_keywords", "negative_keywords")
    @classmethod
    def _keywords(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        return _validate_keywords(v)

    @field_validator("preferred_remote")
    @classmethod
    def _remote(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        low = v.strip().lower()
        if low not in {"remote", "hybrid", "onsite"}:
            raise ValueError(
                "preferred_remote must be one of remote|hybrid|onsite"
            )
        return low


class UserProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    slug: str
    display_name: str
    description: Optional[str] = None
    weights: dict[str, float]
    strong_keywords: list[str]
    weak_keywords: list[str]
    negative_keywords: list[str]
    ranker_text_signals: dict[str, Any] = Field(default_factory=dict)
    preferred_remote: Optional[str] = None
    min_score_threshold: Decimal
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserProfileListResponse(BaseModel):
    total: int
    items: list[UserProfileOut]


class RankerTextSignalsRebuildOut(BaseModel):
    """Summary after POST …/rebuild-ranker-text-signals."""

    profile_slug: str
    built_at: str
    positive_job_ids_scanned: int
    positive_docs_used: int
    ref_dim: int
    suggested_keywords: list[str]


class PromoteSuggestedKeywordsRequest(BaseModel):
    """POST …/promote-suggested-keywords — dry-run by default."""

    dry_run: bool = True
    target: Literal["strong", "weak"] = "weak"
    terms: Optional[list[str]] = None
    auto: bool = False
    max_terms: int = Field(default=5, ge=1, le=50)
    remove_from_suggestions: bool = True


class PromoteSuggestedKeywordsOut(BaseModel):
    profile_slug: str
    dry_run: bool
    applied: bool
    target: str
    added: list[str]
    skipped_already_on_profile: list[str]
    rejected_not_in_suggestions: list[str]
    suggested_keywords_remaining: list[str]
    reason_skipped: Optional[str] = None


class ProfileScoreTestResponse(BaseModel):
    """Result of scoring a single job against a profile (dry run)."""
    profile_slug: str
    job_id: uuid.UUID
    score: float
    bucket: str
    rationale: str
    hidden_gem: bool
    details: dict[str, Any]
