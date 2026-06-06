"""One-time seed script: create David Gillett's scoring profile.

Run from the backend directory:
    .venv/Scripts/python.exe scripts/seed_david_profile.py

Safe to re-run — skips if a profile with slug 'david' already exists.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import session_scope
from app.services.profiles import create_profile, list_profiles, ProfileError

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
    "software engineer", "backend developer", "frontend developer",
    "full stack developer", "data scientist", "machine learning engineer",
    "ml engineer", "quantitative analyst", "senior engineer",
    "staff engineer", "principal engineer", "devops", "sysadmin",
    "network engineer", "security engineer", "embedded", "firmware",
    "systems engineer", "data engineer", "analytics engineer",
    "database administrator",
]

WEIGHTS = {
    "web3_fit": 1.2,       # David has strong web3 community background
    "title_quality": 1.0,
    "provider_trust": 1.0,
    "freshness": 1.2,      # Prefer fresh listings
    "remote_fit": 2.0,     # Remote-only — heavily weighted
    "duplicate_confidence": 1.0,
    "description_fit": 1.0,
    "hidden_gem_bonus": 1.0,
}


def main() -> None:
    with session_scope() as db:
        # Check if already exists
        _, existing = list_profiles(db, only_active=False)
        for p in existing:
            if p.slug == "david":
                print(f"Profile 'david' already exists (id={p.id}). Skipping.")
                return

        try:
            profile = create_profile(
                db,
                slug="david",
                display_name="David Gillett",
                description=(
                    "Community, growth, marketing, and ecosystem roles. "
                    "Remote-only. Web3 + traditional marketing background. "
                    "Target: Community Lead, Head of Community, Growth Lead, "
                    "Marketing Director, Developer Relations, Ecosystem Growth."
                ),
                weights=WEIGHTS,
                strong_keywords=STRONG_KEYWORDS,
                weak_keywords=WEAK_KEYWORDS,
                negative_keywords=NEGATIVE_KEYWORDS,
                preferred_remote="remote",
                min_score_threshold=0,
                is_default=True,
                is_active=True,
            )
            print(f"Created profile 'david' (id={profile.id})")
            print(f"  Strong keywords: {len(STRONG_KEYWORDS)}")
            print(f"  Weak keywords:   {len(WEAK_KEYWORDS)}")
            print(f"  Negative:        {len(NEGATIVE_KEYWORDS)}")
            print(f"  remote_fit weight: {WEIGHTS['remote_fit']}x")
            print()
            print("Next: run a rescore to apply the new profile to all existing jobs.")
            print("  POST /imports/rescore  with profile_slug=david")
        except ProfileError as e:
            print(f"Error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
