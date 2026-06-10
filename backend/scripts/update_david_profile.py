"""Update David's scoring profile weights and negative keywords.

Run from the backend directory:
    .venv/Scripts/python.exe scripts/update_david_profile.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import session_scope
from app.models.user_profile import UserProfile
from sqlalchemy import select

STRONG_KEYWORDS = [
    # Core role identity words
    "community", "discord", "telegram", "ambassador", "ecosystem",
    "engagement", "retention", "moderation", "devrel", "advocacy",
    "lifecycle", "gamification", "onboarding",
    # Multi-word role titles
    "community manager", "community lead", "head of community",
    "community operations", "community builder", "developer relations",
    "developer community", "community growth", "community marketing",
    "community and growth", "community and partnerships",
    "lifecycle marketing", "user engagement", "player engagement",
    "growth lead", "community engagement", "ecosystem growth",
    "brand community", "community programs", "community strategy",
    "community development", "community director", "community advocate",
    "community evangelist", "growth manager", "growth marketing",
    "growth operations", "social community", "online community",
    "community platform", "community and marketing", "head of growth",
    "director of community", "vp community", "vp of community",
    "community experience", "member experience",
    # DevRel / community-adjacent engineering titles (should score high)
    "developer advocate", "developer evangelist", "developer experience",
    "devrel engineer", "community engineer", "developer relations engineer",
]

WEAK_KEYWORDS = [
    "marketing", "social media", "content", "partnerships", "brand",
    "events", "operations", "crm", "ecommerce", "influencer", "activation",
    "campaigns", "customer success", "digital marketing", "email marketing",
    "newsletter", "partnership", "go-to-market", "product marketing",
    "creator", "social strategy", "social engagement", "comms",
    "communications", "customer engagement", "user acquisition",
    "user retention", "organic growth", "gtm",
]

NEGATIVE_KEYWORDS = [
    # Pure engineering roles — specific phrases to avoid false positives
    "software engineer", "frontend engineer", "backend engineer",
    "full stack engineer", "fullstack engineer",
    "frontend developer", "backend developer", "full stack developer",
    "blockchain engineer", "smart contract engineer",
    "android engineer", "ios engineer", "mobile engineer",
    "kotlin engineer", "swift engineer", "rust engineer",
    "platform engineer", "infrastructure engineer",
    "data engineer", "analytics engineer", "data scientist",
    "machine learning engineer", "ml engineer", "ai engineer",
    "systems engineer", "network engineer", "security engineer",
    "devops engineer", "site reliability engineer", "sre",
    "embedded engineer", "firmware engineer",
    "lead engineer", "staff engineer", "principal engineer",
    "senior engineer", "vp engineering", "head of engineering",
    # Non-engineering but wrong roles
    "quantitative analyst", "database administrator",
    "solana developer", "smart contract developer",
    "protocol engineer",
    # Finance / quant
    "quantitative researcher", "quant developer",
]

WEIGHTS = {
    "web3_fit": 0.3,          # web3 company is a bonus, not the dominant signal
    "title_quality": 1.0,
    "provider_trust": 1.0,
    "freshness": 1.2,
    "remote_fit": 2.0,        # Remote-only — heavily weighted
    "duplicate_confidence": 1.0,
    "description_fit": 1.5,   # Keyword matching is the primary signal
    "hidden_gem_bonus": 1.0,
}


def main() -> None:
    with session_scope() as db:
        profile = db.execute(
            select(UserProfile).where(UserProfile.slug == "david")
        ).scalar_one_or_none()

        if profile is None:
            print("Profile 'david' not found. Run seed_david_profile.py first.")
            sys.exit(1)

        profile.strong_keywords = STRONG_KEYWORDS
        profile.weak_keywords = WEAK_KEYWORDS
        profile.negative_keywords = NEGATIVE_KEYWORDS
        profile.weights = WEIGHTS
        db.commit()

        print(f"Updated profile 'david' (id={profile.id})")
        print(f"  web3_fit weight:      {WEIGHTS['web3_fit']}  (was 1.2)")
        print(f"  description_fit weight: {WEIGHTS['description_fit']}  (was 1.0)")
        print(f"  Strong keywords: {len(STRONG_KEYWORDS)}")
        print(f"  Weak keywords:   {len(WEAK_KEYWORDS)}")
        print(f"  Negative:        {len(NEGATIVE_KEYWORDS)}")
        print()
        print("Next: run a rescore to apply changes.")
        print("  POST /imports/rescore  with only_unscored=false")


if __name__ == "__main__":
    main()
