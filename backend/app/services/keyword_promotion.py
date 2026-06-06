"""Automatic promotion of note-mined keywords into profile lists (Ranker v2+).

``ranker_text.build_ranker_text_signals`` stores ``suggested_keywords`` mined from
dismissed/rejected feedback notes. This module moves a guarded subset into
``strong_keywords`` or ``weak_keywords``, optionally removing them from the
suggestions list. Mirrors ``learning.learn_from_feedback``: dry-run by default.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from sqlalchemy.orm import Session

from ..models.pipeline_event import PipelineEvent
from ..models.user_profile import UserProfile
from ..schemas.user_profile import _validate_keywords


TargetLane = Literal["strong", "weak"]


@dataclass
class PromotionReport:
    profile_slug: str
    dry_run: bool
    applied: bool
    target: str
    added: list[str]
    skipped_already_on_profile: list[str]
    rejected_not_in_suggestions: list[str]
    suggested_keywords_remaining: list[str]
    reason_skipped: Optional[str] = None


def _normalized_profile_kw(profile: UserProfile) -> set[str]:
    out: set[str] = set()
    for lst in (
        profile.strong_keywords or [],
        profile.weak_keywords or [],
        profile.negative_keywords or [],
    ):
        for kw in lst:
            if isinstance(kw, str) and kw.strip():
                out.add(kw.strip().lower())
    return out


def _suggestion_canonical_map(signals: dict) -> dict[str, str]:
    """Lowercase token -> canonical display string (first wins)."""
    mp: dict[str, str] = {}
    for raw in signals.get("suggested_keywords") or []:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
        if low not in mp:
            mp[low] = s
    return mp


def promote_suggested_keywords(
    db: Session,
    profile: UserProfile,
    *,
    dry_run: bool = True,
    target: TargetLane = "weak",
    terms: Optional[list[str]] = None,
    auto: bool = False,
    max_terms: int = 5,
    remove_from_suggestions: bool = True,
) -> PromotionReport:
    """Promote mined suggestions into ``strong_keywords`` or ``weak_keywords``.

    When ``terms`` is non-empty, ``auto`` is ignored. Only tokens that appear in the
    current ``ranker_text_signals.suggested_keywords`` list are eligible; others are
    listed under ``rejected_not_in_suggestions``.
    """
    if target not in ("strong", "weak"):
        raise ValueError("target must be 'strong' or 'weak'")

    sig = dict(profile.ranker_text_signals or {})
    canon = _suggestion_canonical_map(sig)
    sug_raw = list(sig.get("suggested_keywords") or [])

    if not canon:
        rejected_list: list[str] = []
        for raw in explicit:
            cl = _validate_keywords([raw])
            if cl:
                rejected_list.append(cl[0])
        return PromotionReport(
            profile_slug=profile.slug,
            dry_run=dry_run,
            applied=False,
            target=target,
            added=[],
            skipped_already_on_profile=[],
            rejected_not_in_suggestions=rejected_list,
            suggested_keywords_remaining=sug_raw,
            reason_skipped="no suggested_keywords — run POST …/rebuild-ranker-text-signals first",
        )

    have = _normalized_profile_kw(profile)
    explicit = [t for t in (terms or []) if isinstance(t, str) and t.strip()]
    if explicit:
        auto = False

    added: list[str] = []
    skipped_have: list[str] = []
    rejected: list[str] = []

    if explicit:
        for raw in explicit:
            cleaned = _validate_keywords([raw])
            if not cleaned:
                rejected.append(raw.strip())
                continue
            low = cleaned[0].lower()
            if low not in canon:
                rejected.append(cleaned[0])
                continue
            if low in have:
                skipped_have.append(canon[low])
                continue
            token = canon[low]
            if token.lower() not in {x.lower() for x in added}:
                added.append(token)
                have.add(low)
    elif auto:
        cap = max(1, min(int(max_terms), 50))
        ordered_low: list[str] = []
        seen_low: set[str] = set()
        for raw in sug_raw:
            if not isinstance(raw, str):
                continue
            low = raw.strip().lower()
            if not low or low not in canon:
                continue
            if low in seen_low:
                continue
            seen_low.add(low)
            ordered_low.append(low)

        for low in ordered_low:
            if len(added) >= cap:
                break
            if low in have:
                skipped_have.append(canon[low])
                continue
            display = canon[low]
            added.append(display)
            have.add(low)
    else:
        return PromotionReport(
            profile_slug=profile.slug,
            dry_run=dry_run,
            applied=False,
            target=target,
            added=[],
            skipped_already_on_profile=[],
            rejected_not_in_suggestions=[],
            suggested_keywords_remaining=sug_raw,
            reason_skipped="provide ``terms`` or set auto=true",
        )

    if not added:
        return PromotionReport(
            profile_slug=profile.slug,
            dry_run=dry_run,
            applied=False,
            target=target,
            added=[],
            skipped_already_on_profile=skipped_have,
            rejected_not_in_suggestions=rejected,
            suggested_keywords_remaining=sug_raw,
            reason_skipped="nothing eligible to promote (already on profile or empty selection)",
        )

    sug_preview = list(sug_raw)
    if remove_from_suggestions:
        rem = {a.lower() for a in added}
        sug_preview = [
            x
            for x in sug_preview
            if isinstance(x, str) and x.strip().lower() not in rem
        ]

    if dry_run:
        return PromotionReport(
            profile_slug=profile.slug,
            dry_run=True,
            applied=False,
            target=target,
            added=added,
            skipped_already_on_profile=skipped_have,
            rejected_not_in_suggestions=rejected,
            suggested_keywords_remaining=sug_preview,
            reason_skipped="dry_run=True; no changes persisted",
        )

    lane_list = list(profile.weak_keywords if target == "weak" else profile.strong_keywords or [])
    seen_lane = {x.lower() for x in lane_list}
    for a in added:
        low = a.lower()
        if low not in seen_lane:
            lane_list.append(a)
            seen_lane.add(low)

    validated_lane = _validate_keywords(lane_list)
    if target == "weak":
        profile.weak_keywords = validated_lane
    else:
        profile.strong_keywords = validated_lane

    if remove_from_suggestions:
        rem = {a.lower() for a in added}
        sig["suggested_keywords"] = [
            x
            for x in (sig.get("suggested_keywords") or [])
            if isinstance(x, str) and x.strip().lower() not in rem
        ]
    profile.ranker_text_signals = sig

    db.add(profile)
    db.add(
        PipelineEvent(
            entity_type="user_profile",
            entity_id=profile.id,
            event_name="profile_keywords_promoted",
            details={
                "profile_slug": profile.slug,
                "target": target,
                "added": added,
                "skipped_already_on_profile": skipped_have,
                "rejected_not_in_suggestions": rejected,
                "remove_from_suggestions": remove_from_suggestions,
            },
        )
    )
    db.commit()
    db.refresh(profile)

    final_sig = dict(profile.ranker_text_signals or {})
    return PromotionReport(
        profile_slug=profile.slug,
        dry_run=False,
        applied=True,
        target=target,
        added=added,
        skipped_already_on_profile=skipped_have,
        rejected_not_in_suggestions=rejected,
        suggested_keywords_remaining=list(final_sig.get("suggested_keywords") or []),
        reason_skipped=None,
    )
