"""Generate profile keyword lists from approved career facts using an LLM."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.career_memory import CareerFact
from ..models.profile import UserProfile

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a job search expert. Your task is to analyse a candidate's career facts \
and produce three keyword lists used to match and rank job postings.

Rules:
- strong_keywords: Role titles, skills, and terms that DIRECTLY match the candidate's \
experience and target roles. Include both single words and short phrases. \
These drive the highest score boost.
- weak_keywords: Adjacent terms — related domains, transferable skills, or roles the \
candidate could pivot into. These give a smaller score boost.
- negative_keywords: Role types and titles the candidate is clearly NOT a fit for. \
These penalise irrelevant jobs. Be specific enough to avoid false positives \
(e.g. "frontend engineer" not just "engineer", unless you're sure the candidate \
wants no engineering roles at all).

Output ONLY valid JSON in exactly this shape:
{
  "strong_keywords": ["...", ...],
  "weak_keywords": ["...", ...],
  "negative_keywords": ["...", ...]
}

Guidelines for keyword format:
- Use lowercase
- Mix single words ("community") and short phrases ("community manager", "head of community")
- 20–50 strong, 15–30 weak, 15–40 negative keywords
- Negative keywords should be role-specific phrases, not generic words
"""


def generate_keywords_from_facts(db: Session, profile: UserProfile) -> dict:
    """Call the LLM with the profile's approved facts and update its keywords."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    facts = db.execute(
        select(CareerFact.fact_text)
        .where(CareerFact.verification_state == "approved")
        .order_by(CareerFact.id)
    ).scalars().all()

    if not facts:
        raise ValueError("No approved career facts found — approve some facts first")

    facts_text = "\n".join(f"- {f}" for f in facts)
    user_message = (
        f"Here are the candidate's approved career facts:\n\n{facts_text}\n\n"
        f"Profile description: {profile.description or '(none)'}\n\n"
        "Generate the keyword lists."
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
        )
        raw = response.choices[0].message.content or "{}"
        keywords = json.loads(raw)
    except Exception as e:
        logger.exception("LLM keyword generation failed")
        raise ValueError(f"LLM call failed: {e}") from e

    strong = [k.strip().lower() for k in keywords.get("strong_keywords", []) if k.strip()]
    weak = [k.strip().lower() for k in keywords.get("weak_keywords", []) if k.strip()]
    negative = [k.strip().lower() for k in keywords.get("negative_keywords", []) if k.strip()]

    if not strong:
        raise ValueError("LLM returned empty strong_keywords — check your facts")

    profile.strong_keywords = strong
    profile.weak_keywords = weak
    profile.negative_keywords = negative
    db.commit()

    logger.info(
        "Generated keywords for profile %r: strong=%d weak=%d negative=%d",
        profile.slug, len(strong), len(weak), len(negative),
    )

    return {
        "ok": True,
        "profile_slug": profile.slug,
        "facts_used": len(facts),
        "strong_keywords": strong,
        "weak_keywords": weak,
        "negative_keywords": negative,
    }
