"""User profile endpoints (Sprint G / Ranker v2).

CRUD over `user_profiles` plus a dry-run test endpoint that scores a
single job against a profile without persisting anything.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path

from ..schemas.learning import (
    ComponentDelta,
    LearnRequest,
    LearningReportOut,
)
from ..schemas.user_profile import (
    ProfileFromTemplateRequest,
    ProfileScoreTestResponse,
    PromoteSuggestedKeywordsOut,
    PromoteSuggestedKeywordsRequest,
    RankerTextSignalsRebuildOut,
    TemplateInfo,
    TemplateListResponse,
    UserProfileCreate,
    UserProfileListResponse,
    UserProfileOut,
    UserProfileUpdate,
)
from ..services import keyword_promotion as keyword_promotion_svc
from ..services import keyword_generation as keyword_generation_svc
from ..services import learning as learning_svc
from ..services import profiles as profiles_svc
from ..services import ranker
from .deps import DbSession, require_admin_token


router = APIRouter()


@router.get(
    "",
    response_model=UserProfileListResponse,
    summary="List user profiles (default first).",
)
def list_profiles(
    db: DbSession,
    only_active: bool = False,
) -> UserProfileListResponse:
    total, items = profiles_svc.list_profiles(db, only_active=only_active)
    return UserProfileListResponse(
        total=total,
        items=[UserProfileOut.model_validate(p) for p in items],
    )


@router.post(
    "",
    response_model=UserProfileOut,
    dependencies=[Depends(require_admin_token)],
    status_code=201,
    summary="Create a new user profile.",
)
def create_profile(payload: UserProfileCreate, db: DbSession) -> UserProfileOut:
    try:
        profile = profiles_svc.create_profile(
            db,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            weights=payload.weights,
            strong_keywords=payload.strong_keywords,
            weak_keywords=payload.weak_keywords,
            negative_keywords=payload.negative_keywords,
            preferred_remote=payload.preferred_remote,
            min_score_threshold=payload.min_score_threshold,
            is_default=payload.is_default,
            is_active=payload.is_active,
        )
    except profiles_svc.ProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return UserProfileOut.model_validate(profile)


@router.get(
    "/templates",
    response_model=TemplateListResponse,
    summary="List available onboarding templates.",
)
def list_templates() -> TemplateListResponse:
    return TemplateListResponse(
        templates=[
            TemplateInfo(slug=slug, display_name=tmpl["display_name"], description=tmpl["description"])
            for slug, tmpl in profiles_svc._TEMPLATES.items()
        ]
    )


@router.post(
    "/from-template",
    response_model=UserProfileOut,
    status_code=201,
    summary="Create (or activate) a scoring profile from a built-in onboarding template.",
)
def create_profile_from_template(
    payload: ProfileFromTemplateRequest, db: DbSession
) -> UserProfileOut:
    try:
        profile = profiles_svc.create_profile_from_template(
            db,
            template_slug=payload.template_slug,
            preferred_remote=payload.preferred_remote,
        )
    except profiles_svc.ProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return UserProfileOut.model_validate(profile)


@router.get(
    "/{slug}",
    response_model=UserProfileOut,
    summary="Get a profile by slug.",
)
def get_profile(slug: str, db: DbSession) -> UserProfileOut:
    profile = profiles_svc.get_by_slug(db, slug)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {slug!r}")
    return UserProfileOut.model_validate(profile)


@router.patch(
    "/{slug}",
    response_model=UserProfileOut,
    dependencies=[Depends(require_admin_token)],
    summary="Update a profile (partial).",
)
def update_profile(
    slug: str, payload: UserProfileUpdate, db: DbSession
) -> UserProfileOut:
    existing = profiles_svc.get_by_slug(db, slug)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {slug!r}")
    try:
        profile = profiles_svc.update_profile(
            db,
            existing.id,
            display_name=payload.display_name,
            description=payload.description,
            weights=payload.weights,
            strong_keywords=payload.strong_keywords,
            weak_keywords=payload.weak_keywords,
            negative_keywords=payload.negative_keywords,
            preferred_remote=payload.preferred_remote,
            min_score_threshold=payload.min_score_threshold,
            is_default=payload.is_default,
            is_active=payload.is_active,
        )
    except profiles_svc.ProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return UserProfileOut.model_validate(profile)


@router.delete(
    "/{slug}",
    dependencies=[Depends(require_admin_token)],
    status_code=204,
    summary="Delete a profile (default profile is protected).",
)
def delete_profile(slug: str, db: DbSession) -> None:
    existing = profiles_svc.get_by_slug(db, slug)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {slug!r}")
    try:
        profiles_svc.delete_profile(db, existing.id)
    except profiles_svc.ProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/{slug}/rebuild-ranker-text-signals",
    response_model=RankerTextSignalsRebuildOut,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Rebuild Ranker v2 text signals: TF–IDF vector from positive-feedback "
        "job descriptions + suggested keywords from dismissed/rejected notes."
    ),
)
def rebuild_ranker_text_signals_route(
    slug: str, db: DbSession
) -> RankerTextSignalsRebuildOut:
    from ..services import ranker_text as ranker_text_mod

    profile = profiles_svc.get_by_slug(db, slug)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {slug!r}")
    payload = ranker_text_mod.build_ranker_text_signals(db, profile)
    db.commit()
    db.refresh(profile)
    return RankerTextSignalsRebuildOut(
        profile_slug=profile.slug,
        built_at=str(payload.get("built_at", "")),
        positive_job_ids_scanned=int(payload.get("positive_job_ids_scanned", 0)),
        positive_docs_used=int(payload.get("positive_docs_used", 0)),
        ref_dim=int(payload.get("ref_dim", 0)),
        suggested_keywords=list(payload.get("suggested_keywords") or []),
    )


@router.post(
    "/{slug}/promote-suggested-keywords",
    response_model=PromoteSuggestedKeywordsOut,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Promote note-mined suggested_keywords into strong_keywords or weak_keywords "
        "(dry-run by default)."
    ),
)
def promote_suggested_keywords_route(
    slug: str,
    payload: PromoteSuggestedKeywordsRequest,
    db: DbSession,
) -> PromoteSuggestedKeywordsOut:
    profile = profiles_svc.get_by_slug(db, slug)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {slug!r}")

    r = keyword_promotion_svc.promote_suggested_keywords(
        db,
        profile,
        dry_run=payload.dry_run,
        target=payload.target,
        terms=payload.terms,
        auto=payload.auto,
        max_terms=payload.max_terms,
        remove_from_suggestions=payload.remove_from_suggestions,
    )
    return PromoteSuggestedKeywordsOut(
        profile_slug=r.profile_slug,
        dry_run=r.dry_run,
        applied=r.applied,
        target=r.target,
        added=r.added,
        skipped_already_on_profile=r.skipped_already_on_profile,
        rejected_not_in_suggestions=r.rejected_not_in_suggestions,
        suggested_keywords_remaining=r.suggested_keywords_remaining,
        reason_skipped=r.reason_skipped,
    )


@router.post(
    "/{slug}/score/{job_id}",
    response_model=ProfileScoreTestResponse,
    dependencies=[Depends(require_admin_token)],
    summary="Score a single job against this profile WITHOUT persisting.",
)
def test_score(
    slug: str,
    job_id: uuid.UUID = Path(..., description="Canonical job id to score."),
    db: DbSession = None,  # type: ignore[assignment]
) -> ProfileScoreTestResponse:
    profile = profiles_svc.get_by_slug(db, slug)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {slug!r}")

    result = ranker.score_job_dry(db, job_id, profile=profile)
    if result is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")

    return ProfileScoreTestResponse(
        profile_slug=profile.slug,
        job_id=job_id,
        score=float(result.ranking_score),
        bucket=result.bucket,
        rationale=result.rationale,
        hidden_gem=result.hidden_gem,
        details=result.details,
    )


@router.post(
    "/{slug}/generate-keywords",
    dependencies=[Depends(require_admin_token)],
    summary="Use LLM to generate keyword lists for a profile from approved career facts.",
)
def generate_keywords(slug: str, db: DbSession) -> dict:
    profile = profiles_svc.get_by_slug(db, slug)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {slug!r}")
    result = keyword_generation_svc.generate_keywords_from_facts(db, profile)
    return result


@router.post(
    "/{slug}/learn",
    response_model=LearningReportOut,
    dependencies=[Depends(require_admin_token)],
    summary=(
        "Propose (or apply) weight nudges for a profile based on its "
        "feedback log. Dry-run by default."
    ),
)
def learn_profile(
    slug: str,
    payload: LearnRequest,
    db: DbSession,
) -> LearningReportOut:
    profile = profiles_svc.get_by_slug(db, slug)
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"profile not found: {slug!r}"
        )

    cfg = learning_svc.LearningConfig(
        dry_run=payload.dry_run,
        min_samples=payload.min_samples,
        learning_rate=payload.learning_rate,
        max_step=payload.max_step,
        weight_min=payload.weight_min,
        weight_max=payload.weight_max,
        max_events=payload.max_events,
        feedback_decay_half_life_days=payload.feedback_decay_half_life_days,
    )
    if cfg.weight_max < cfg.weight_min:
        raise HTTPException(
            status_code=400,
            detail="weight_max must be >= weight_min",
        )

    report = learning_svc.learn_from_feedback(db, profile, config=cfg)
    return LearningReportOut(
        profile_slug=report.profile_slug,
        events_considered=report.events_considered,
        jobs_unique=report.jobs_unique,
        positive_events=report.positive_events,
        negative_events=report.negative_events,
        feedback_decay_half_life_days_used=report.feedback_decay_half_life_days_used,
        applied=report.applied,
        reason_skipped=report.reason_skipped,
        components=[ComponentDelta(**s.__dict__) for s in report.components],
    )
