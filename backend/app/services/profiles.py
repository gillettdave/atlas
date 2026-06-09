"""profiles — CRUD + bootstrap for UserProfile (Sprint G).

The default profile is created automatically (also seeded by migration
`0002_user_profiles`; ownership via `0009_users_and_profile_scope`).
Consumers should prefer `get_effective(db, slug)` which falls back to the
default when `slug` is None or missing.

Invariants enforced here (plus DB constraints):
- Per tenant user (`user_id`), exactly one profile has ``is_default = true``.
- A profile marked default is also active.
- Deleting the default profile is rejected.

Until multi-tenant routing exists, lookups are scoped to the seeded local
tenant ID (``constants.SEEDED_LOCAL_USER_ID``).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constants import SEEDED_LOCAL_USER_ID
from ..models.user_profile import UserProfile


class ProfileError(Exception):
    """Raised on invalid profile operations (business-rule violations)."""


# ---------------------------------------------------------------------------
# Onboarding templates
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, dict] = {
    "community_manager": {
        "display_name": "Community Manager",
        "description": "Community management, engagement, and ecosystem growth roles.",
        "strong_keywords": [
            "community", "discord", "telegram", "ecosystem", "ambassador",
            "events", "engagement", "forum", "moderation", "community manager",
            "community lead", "community growth", "online community",
        ],
        "weak_keywords": [
            "social media", "content", "partnerships", "brand", "advocacy",
            "user research", "feedback", "onboarding", "retention",
        ],
        "negative_keywords": ["rust", "solidity", "smart contract", "kernel", "firmware"],
        "preferred_remote": "remote",
        "weights": {"web3_fit": 1.2, "description_fit": 1.3, "freshness": 1.1},
    },
    "devrel": {
        "display_name": "Developer Relations",
        "description": "Developer advocacy, technical writing, and SDK/docs roles.",
        "strong_keywords": [
            "developer relations", "devrel", "developer advocate", "advocacy",
            "technical writing", "sdk", "api docs", "documentation", "hackathon",
            "developer experience", "dx", "developer community", "open source",
        ],
        "weak_keywords": [
            "community", "content", "tutorials", "blog", "webinar",
            "demos", "integrations", "technical marketing",
        ],
        "negative_keywords": ["firmware", "kernel", "embedded", "FPGA"],
        "preferred_remote": "remote",
        "weights": {"web3_fit": 1.3, "description_fit": 1.4, "freshness": 1.1},
    },
    "growth": {
        "display_name": "Growth",
        "description": "Growth marketing, acquisition, and retention roles.",
        "strong_keywords": [
            "growth", "acquisition", "funnel", "seo", "paid", "conversion",
            "retention", "a/b testing", "growth hacking", "user acquisition",
            "performance marketing", "growth marketing", "gtm",
        ],
        "weak_keywords": [
            "analytics", "data", "marketing", "product", "partnerships",
            "lifecycle", "email marketing", "referral",
        ],
        "negative_keywords": ["rust", "solidity", "firmware", "kernel"],
        "preferred_remote": "remote",
        "weights": {"description_fit": 1.3, "freshness": 1.2},
    },
    "marketing_manager": {
        "display_name": "Marketing Manager",
        "description": "Brand, campaigns, content, and communications roles.",
        "strong_keywords": [
            "marketing", "brand", "campaigns", "content", "social media",
            "communications", "pr", "public relations", "marketing manager",
            "content marketing", "brand manager", "storytelling",
        ],
        "weak_keywords": [
            "seo", "email", "events", "partnerships", "copywriting",
            "creative", "design", "social", "digital marketing",
        ],
        "negative_keywords": ["rust", "solidity", "firmware", "kernel"],
        "preferred_remote": "remote",
        "weights": {"description_fit": 1.2, "freshness": 1.1},
    },
    "customer_success": {
        "display_name": "Customer Success",
        "description": "CSM, onboarding, retention, and account management roles.",
        "strong_keywords": [
            "customer success", "csm", "onboarding", "retention", "churn",
            "nps", "account management", "customer success manager",
            "client success", "renewals", "expansion", "upsell",
        ],
        "weak_keywords": [
            "support", "saas", "b2b", "enterprise", "product", "training",
            "relationship", "partnership", "satisfaction",
        ],
        "negative_keywords": ["rust", "solidity", "firmware", "kernel"],
        "preferred_remote": "remote",
        "weights": {"description_fit": 1.3, "freshness": 1.1},
    },
    "operations": {
        "display_name": "Operations",
        "description": "Ops, process improvement, tooling, and project coordination roles.",
        "strong_keywords": [
            "operations", "ops", "process", "tooling", "systems",
            "project management", "coordination", "biz ops", "business operations",
            "strategy and ops", "chief of staff",
        ],
        "weak_keywords": [
            "analytics", "reporting", "planning", "cross-functional",
            "efficiency", "automation", "workflows", "vendor management",
        ],
        "negative_keywords": ["rust", "solidity", "firmware", "kernel"],
        "preferred_remote": "remote",
        "weights": {"description_fit": 1.2, "freshness": 1.0},
    },
    "product_manager": {
        "display_name": "Product Manager",
        "description": "Product management, roadmap, and discovery roles.",
        "strong_keywords": [
            "product", "product manager", "roadmap", "prd", "discovery",
            "user research", "stakeholder", "okr", "pm", "product lead",
            "product owner", "product strategy", "feature prioritization",
        ],
        "weak_keywords": [
            "agile", "scrum", "cross-functional", "analytics", "data",
            "design", "ux", "go-to-market", "launch",
        ],
        "negative_keywords": ["rust", "solidity", "firmware", "kernel"],
        "preferred_remote": "remote",
        "weights": {"description_fit": 1.3, "freshness": 1.1},
    },
    "sales": {
        "display_name": "Sales",
        "description": "Sales, BD, and revenue roles.",
        "strong_keywords": [
            "sales", "business development", "bd", "pipeline", "ae",
            "account executive", "sdr", "quota", "revenue", "closing",
            "enterprise sales", "b2b sales", "saas sales",
        ],
        "weak_keywords": [
            "crm", "salesforce", "partnerships", "outbound", "inbound",
            "prospecting", "negotiation", "demo",
        ],
        "negative_keywords": ["rust", "solidity", "firmware", "kernel"],
        "preferred_remote": "remote",
        "weights": {"description_fit": 1.2, "freshness": 1.2},
    },
}

TEMPLATE_SLUGS = list(_TEMPLATES.keys())


def create_profile_from_template(
    db: Session,
    *,
    template_slug: str,
    preferred_remote: str | None = None,
    user_id: uuid.UUID | None = None,
) -> UserProfile:
    """Create (or return existing) a UserProfile from a named template.

    Sets the new profile as the default. If a profile with the template
    slug already exists for this user, updates preferred_remote and
    promotes it to default instead of creating a duplicate.
    """
    tmpl = _TEMPLATES.get(template_slug)
    if tmpl is None:
        raise ProfileError(f"unknown template slug: {template_slug!r}")

    remote = preferred_remote or tmpl["preferred_remote"]

    owner = user_id or _tenant_user_id()
    existing = get_by_slug(db, template_slug, uid=owner)
    if existing is not None:
        # Already exists — update remote pref and promote to default
        return update_profile(
            db,
            existing.id,
            preferred_remote=remote,
            is_default=True,
            is_active=True,
        )

    return create_profile(
        db,
        slug=template_slug,
        display_name=tmpl["display_name"],
        description=tmpl["description"],
        weights=tmpl.get("weights", {}),
        strong_keywords=tmpl["strong_keywords"],
        weak_keywords=tmpl["weak_keywords"],
        negative_keywords=tmpl["negative_keywords"],
        preferred_remote=remote,
        min_score_threshold=Decimal("0"),
        is_default=True,
        is_active=True,
        user_id=owner,
    )


def _tenant_user_id() -> uuid.UUID:
    """Single seeded user until auth attaches a real tenant to requests."""
    return SEEDED_LOCAL_USER_ID


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_by_id(db: Session, profile_id: uuid.UUID) -> Optional[UserProfile]:
    row = db.get(UserProfile, profile_id)
    if row is None:
        return None
    return row


def get_by_slug(db: Session, slug: str, *, uid: uuid.UUID | None = None) -> Optional[UserProfile]:
    uid = uid or _tenant_user_id()
    if not slug:
        return None
    return db.execute(
        select(UserProfile).where(
            UserProfile.user_id == uid,
            UserProfile.slug == slug.strip().lower(),
        )
    ).scalar_one_or_none()


def get_default(db: Session, *, uid: uuid.UUID | None = None) -> Optional[UserProfile]:
    uid = uid or _tenant_user_id()
    return db.execute(
        select(UserProfile).where(
            UserProfile.user_id == uid,
            UserProfile.is_default.is_(True),
        )
    ).scalar_one_or_none()


def get_effective(
    db: Session, slug: Optional[str], *, uid: uuid.UUID | None = None
) -> Optional[UserProfile]:
    """Return the named profile, else the default. Returns None only
    if no profiles exist at all (pre-bootstrap)."""
    if slug:
        p = get_by_slug(db, slug, uid=uid)
        if p is not None:
            return p
    return get_default(db, uid=uid)


def list_profiles(
    db: Session, *, only_active: bool = False, uid: uuid.UUID | None = None
) -> tuple[int, list[UserProfile]]:
    uid = uid or _tenant_user_id()
    stmt = select(UserProfile).where(UserProfile.user_id == uid)
    if only_active:
        stmt = stmt.where(UserProfile.is_active.is_(True))
    stmt = stmt.order_by(
        UserProfile.is_default.desc(),
        UserProfile.display_name.asc(),
    )
    items = list(db.execute(stmt).scalars().all())
    total = int(
        db.execute(
            select(func.count(UserProfile.id)).where(UserProfile.user_id == uid)
        ).scalar_one()
        or 0
    )
    return total, items


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def create_profile(
    db: Session,
    *,
    slug: str,
    display_name: str,
    description: Optional[str],
    weights: dict[str, float],
    strong_keywords: list[str],
    weak_keywords: list[str],
    negative_keywords: list[str],
    preferred_remote: Optional[str],
    min_score_threshold,  # Decimal
    is_default: bool,
    is_active: bool,
    user_id: uuid.UUID | None = None,
) -> UserProfile:
    owner = user_id or _tenant_user_id()
    slug = slug.strip().lower()
    if get_by_slug(db, slug, uid=owner) is not None:
        raise ProfileError(f"profile slug already exists: {slug!r}")

    if is_default:
        _clear_default(db, owner_user_id=owner)
        is_active = True  # default must be active

    profile = UserProfile(
        user_id=owner,
        slug=slug,
        display_name=display_name,
        description=description,
        weights=weights or {},
        strong_keywords=strong_keywords or [],
        weak_keywords=weak_keywords or [],
        negative_keywords=negative_keywords or [],
        ranker_text_signals={},
        preferred_remote=preferred_remote,
        min_score_threshold=min_score_threshold,
        is_default=is_default,
        is_active=is_active,
    )
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ProfileError(f"failed to create profile: {e.orig}") from e
    db.refresh(profile)
    return profile


def update_profile(
    db: Session,
    profile_id: uuid.UUID,
    *,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    weights: Optional[dict[str, float]] = None,
    strong_keywords: Optional[list[str]] = None,
    weak_keywords: Optional[list[str]] = None,
    negative_keywords: Optional[list[str]] = None,
    preferred_remote: Optional[str] = None,
    min_score_threshold=None,
    is_default: Optional[bool] = None,
    is_active: Optional[bool] = None,
) -> UserProfile:
    profile = get_by_id(db, profile_id)
    if profile is None:
        raise ProfileError(f"profile not found: {profile_id}")

    if display_name is not None:
        profile.display_name = display_name
    if description is not None:
        profile.description = description
    if weights is not None:
        profile.weights = weights
    if strong_keywords is not None:
        profile.strong_keywords = strong_keywords
    if weak_keywords is not None:
        profile.weak_keywords = weak_keywords
    if negative_keywords is not None:
        profile.negative_keywords = negative_keywords
    if preferred_remote is not None:
        profile.preferred_remote = preferred_remote or None
    if min_score_threshold is not None:
        profile.min_score_threshold = min_score_threshold
    if is_active is not None:
        profile.is_active = is_active

    if is_default is True:
        _clear_default(db, owner_user_id=profile.user_id, except_id=profile.id)
        profile.is_default = True
        profile.is_active = True
    elif is_default is False:
        if profile.is_default:
            raise ProfileError(
                "cannot unset is_default directly; promote another "
                "profile to default instead."
            )

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ProfileError(f"failed to update profile: {e.orig}") from e
    db.refresh(profile)
    return profile


def delete_profile(db: Session, profile_id: uuid.UUID) -> bool:
    profile = get_by_id(db, profile_id)
    if profile is None:
        return False
    if profile.is_default:
        raise ProfileError("cannot delete the default profile")
    db.delete(profile)
    db.commit()
    return True


def _clear_default(
    db: Session,
    *,
    owner_user_id: uuid.UUID,
    except_id: Optional[uuid.UUID] = None,
) -> None:
    stmt = select(UserProfile).where(
        UserProfile.user_id == owner_user_id,
        UserProfile.is_default.is_(True),
    )
    if except_id is not None:
        stmt = stmt.where(UserProfile.id != except_id)
    for p in db.execute(stmt).scalars().all():
        p.is_default = False
    db.flush()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def ensure_default(db: Session) -> UserProfile:
    """Create the default profile if missing (safety net — migration seeds
    it when possible)."""
    uid = _tenant_user_id()
    existing = get_default(db, uid=uid)
    if existing is not None:
        return existing

    by_slug = get_by_slug(db, "default", uid=uid)
    if by_slug is not None:
        by_slug.is_default = True
        by_slug.is_active = True
        db.commit()
        db.refresh(by_slug)
        return by_slug

    return create_profile(
        db,
        slug="default",
        display_name="Default",
        description="Ranker v1 equivalent: all weights 1.0, no keyword overrides.",
        weights={},
        strong_keywords=[],
        weak_keywords=[],
        negative_keywords=[],
        preferred_remote=None,
        min_score_threshold=Decimal("0"),
        is_default=True,
        is_active=True,
        user_id=uid,
    )
