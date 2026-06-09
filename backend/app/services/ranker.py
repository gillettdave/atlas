"""Ranker — canonical-job scoring engine (v1 + v2 profiles).

Responsibilities:
- Produce a single `ScoreResult` for a canonical `Job` from:
    * intrinsic listing signals (title quality, spam flags, provider trust)
    * freshness signals (first_seen_at + recency of last sighting)
    * Web3-fit signals (keyword match in title/company/description)
    * remote-fit signals (remote_type)
    * duplicate-confidence signals (sighting count + source diversity)
    * hidden-gem signal (single-source + fresh + strong Web3 fit + ATS-direct)
- Write outputs:
    jobs.ranking_score  -> "is this a job Atlas should surface first?"
    jobs.quality_score  -> "is the listing itself well-formed and trustworthy?"
    job_scores          -> history row (latest per (job, profile) is authoritative)

Score is 0-100. Buckets:
    top     >= 75
    strong  55-74
    maybe   35-54
    skip    < 35

Sprint G — Ranker v2:
- `score_job(..., profile=None)` optionally accepts a `UserProfile` whose
  per-component weight multipliers and custom keyword lists flex the score.
- **Description fit** (v2 text): optional TF–IDF cosine vs a profile reference
  built from positive-feedback job descriptions, plus note-mined terms; see
  `ranker_text.build_ranker_text_signals` and `POST …/rebuild-ranker-text-signals`.
- `rescore_jobs(..., profile_slug=None)` writes per-profile `job_scores`
  rows (profile_id populated). When scoring against the DEFAULT profile
  (or no profile), `jobs.ranking_score` / `jobs.quality_score` are also
  updated to preserve v1 behavior.

`score_job` remains pure and side-effect free.
"""
from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import SEEDED_LOCAL_USER_ID
from ..models.candidate_profile import CandidateProfile
from ..models.job import Job
from ..models.job_score import JobScore
from ..models.job_source_sighting import JobSourceSighting
from ..models.pipeline_event import PipelineEvent
from ..models.user_job_score import UserJobScore
from ..models.user_profile import UserProfile

from . import ranker_text as ranker_text_svc


# ---------------------------------------------------------------------------
# Static vocabularies
# ---------------------------------------------------------------------------

# Strong Web3 signals — single-word tokens (word-boundary matched) and
# multi-word phrases (substring matched, already disambiguated by spaces).
# "rust" is intentionally omitted: too many false positives ("trust",
# "robust", "intrusion") and a generic systems-language signal is better
# handled by title-quality than Web3-fit.
_WEB3_STRONG_WORDS: set[str] = {
    "blockchain", "crypto", "cryptocurrency", "web3",
    "defi", "dao", "daos",
    "ethereum", "solana", "bitcoin", "polygon", "avalanche", "cosmos",
    "arbitrum", "optimism", "starknet", "zksync",
    "solidity", "vyper",
    "rollup", "rollups", "appchain", "subnet",
    "zk", "zkevm",
    "evm", "consensus", "validator",
    "nft", "nfts", "dex", "amm",
    "mev", "tokenomics", "stablecoin", "stablecoins",
    "onchain",
}
_WEB3_STRONG_PHRASES: set[str] = {
    "smart contract", "smart contracts",
    "web 3", "base chain",
    "layer 2", "l2 chain",
    "zero knowledge", "zero-knowledge",
    "zk-rollup", "zk rollup", "liquid staking",
    "governance token", "de-fi",
    "on-chain", "on chain",
    "move lang",
    "protocol research", "protocol researcher",
}

# Weaker signals — adjacent domains, lower weight.
_WEB3_WEAK_WORDS: set[str] = {
    "fintech", "trading", "quant", "derivatives",
    "options", "futures", "exchange",
    "custody", "custodian", "payments", "clearing", "settlement",
    "staking",  # sometimes used generically (e.g. "equity staking") → weak
    "wallet", "wallets", "bridge", "oracle", "oracles",  # overloaded words
}
_WEB3_WEAK_PHRASES: set[str] = {
    "hedge fund", "market maker", "market making", "market-making",
    "algorithmic trading", "algo trading",
    "protocol engineer",  # ambiguous — only weak signal without other web3 context
}


def _compile_word_re(words: set[str]) -> Optional[re.Pattern[str]]:
    """Build a single alternation regex with word boundaries, or None
    if the set is empty (some profiles may configure no strong words)."""
    if not words:
        return None
    # Sort by length desc so longer words win over prefixes on greedy regex.
    escaped = [re.escape(w) for w in sorted(words, key=len, reverse=True)]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


_WEB3_STRONG_WORD_RE = _compile_word_re(_WEB3_STRONG_WORDS)
_WEB3_WEAK_WORD_RE = _compile_word_re(_WEB3_WEAK_WORDS)


# ---------------------------------------------------------------------------
# Profile runtime (Sprint G)
# ---------------------------------------------------------------------------
#
# A ProfileRuntime bundles everything the scorer needs from a UserProfile:
# compiled regex for the profile's extra keyword lists, the weight map,
# and the preferred_remote bias. It's built once at the start of a
# rescore run so per-job scoring stays cheap.

DEFAULT_COMPONENT_WEIGHTS: dict[str, float] = {
    "web3_fit": 1.0,
    "title_quality": 1.0,
    "provider_trust": 1.0,
    "freshness": 1.0,
    "remote_fit": 1.0,
    "duplicate_confidence": 1.0,
    "description_fit": 1.0,
    "hidden_gem_bonus": 1.0,
    "location_fit": 1.5,
}

# Max raw points per component BEFORE weighting. Must stay in sync with
# the per-component scorer functions below.
COMPONENT_MAX: dict[str, float] = {
    "web3_fit": 25.0,
    "title_quality": 15.0,
    "provider_trust": 10.0,
    "freshness": 20.0,
    "remote_fit": 10.0,
    "duplicate_confidence": 10.0,
    "description_fit": 12.0,
    "hidden_gem_bonus": 10.0,
    "location_fit": 15.0,
}

# Base (non-gem) max used for normalization. Gem bonus is additive on top
# and clamped, matching v1's behavior.
_BASE_COMPONENTS: tuple[str, ...] = (
    "web3_fit",
    "title_quality",
    "provider_trust",
    "freshness",
    "remote_fit",
    "duplicate_confidence",
    "description_fit",
    "location_fit",
)


@dataclass
class ProfileRuntime:
    """Precomputed per-profile state used by score_job."""
    slug: str
    profile_id: Optional[uuid.UUID]
    weights: dict[str, float]
    preferred_remote: Optional[str]
    extra_strong_words: set[str]
    extra_strong_phrases: set[str]
    extra_weak_words: set[str]
    extra_weak_phrases: set[str]
    negative_words: set[str]
    negative_phrases: set[str]

    # Compiled regex combining global vocab + profile extras.
    strong_word_re: Optional[re.Pattern[str]]
    weak_word_re: Optional[re.Pattern[str]]
    negative_word_re: Optional[re.Pattern[str]]

    is_default: bool = True

    # Ranker v2 — sparse L2-normalized TF–IDF reference + note-mined terms.
    description_ref_vector: dict[str, float] = field(default_factory=dict)
    note_suggested_terms: frozenset[str] = field(default_factory=frozenset)

    # Location fit (Phase 1) — loaded from candidate_profiles at rescore time.
    location_search_mode: str = "remote"   # "remote"|"local"|"both"|"target"|"all"
    location_home_city: str = ""
    location_target_cities: list[str] = field(default_factory=list)


def _split_keywords(kws: list[str]) -> tuple[set[str], set[str]]:
    """Partition a flat keyword list into (single-word, multi-word) sets."""
    words: set[str] = set()
    phrases: set[str] = set()
    for kw in kws or []:
        if not kw:
            continue
        low = kw.strip().lower()
        if not low:
            continue
        if re.search(r"\s", low) or "-" in low:
            # Anything with whitespace or a hyphen is treated as a phrase
            # (substring match); single alphanumeric tokens use word-boundary.
            phrases.add(low)
        else:
            words.add(low)
    return words, phrases


def build_runtime(
    profile: Optional[UserProfile],
    *,
    location_ctx: Optional[dict] = None,
) -> ProfileRuntime:
    """Compile a profile into a ProfileRuntime.

    When `profile` is None, returns a runtime that matches v1 semantics
    exactly (all weights 1.0, no extras, no negatives).

    `location_ctx` is an optional dict with keys `search_mode`, `home_city`,
    `target_cities` — loaded from candidate_profiles by callers that have a
    DB session. When absent, defaults to remote-mode (safe, backward-compat).
    """
    loc = location_ctx or {}
    loc_mode = str(loc.get("search_mode") or "remote")
    loc_city = str(loc.get("home_city") or "")
    loc_targets = list(loc.get("target_cities") or [])

    if profile is None:
        return ProfileRuntime(
            slug="default",
            profile_id=None,
            weights=dict(DEFAULT_COMPONENT_WEIGHTS),
            preferred_remote=None,
            extra_strong_words=set(),
            extra_strong_phrases=set(),
            extra_weak_words=set(),
            extra_weak_phrases=set(),
            negative_words=set(),
            negative_phrases=set(),
            strong_word_re=_WEB3_STRONG_WORD_RE,
            weak_word_re=_WEB3_WEAK_WORD_RE,
            negative_word_re=None,
            is_default=True,
            description_ref_vector={},
            note_suggested_terms=frozenset(),
            location_search_mode=loc_mode,
            location_home_city=loc_city,
            location_target_cities=loc_targets,
        )

    weights = dict(DEFAULT_COMPONENT_WEIGHTS)
    for k, v in (profile.weights or {}).items():
        if k in weights:
            try:
                weights[k] = float(v)
            except (TypeError, ValueError):
                continue

    es_words, es_phrases = _split_keywords(list(profile.strong_keywords or []))
    ew_words, ew_phrases = _split_keywords(list(profile.weak_keywords or []))
    neg_words, neg_phrases = _split_keywords(
        list(profile.negative_keywords or [])
    )

    strong_re = _compile_word_re(_WEB3_STRONG_WORDS | es_words)
    weak_re = _compile_word_re(_WEB3_WEAK_WORDS | ew_words)
    neg_re = _compile_word_re(neg_words) if neg_words else None

    ref_vec: dict[str, float] = {}
    note_sug: frozenset[str] = frozenset()
    sig = getattr(profile, "ranker_text_signals", None) or {}
    if isinstance(sig, dict):
        rv = sig.get("ref_vector")
        if isinstance(rv, dict):
            for k, v in rv.items():
                try:
                    ref_vec[str(k)] = float(v)
                except (TypeError, ValueError):
                    continue
        sk = sig.get("suggested_keywords")
        if isinstance(sk, list):
            note_sug = frozenset(
                str(x).strip().lower()
                for x in sk
                if x and str(x).strip()
            )

    return ProfileRuntime(
        slug=profile.slug,
        profile_id=profile.id,
        weights=weights,
        preferred_remote=(profile.preferred_remote or None),
        extra_strong_words=es_words,
        extra_strong_phrases=es_phrases,
        extra_weak_words=ew_words,
        extra_weak_phrases=ew_phrases,
        negative_words=neg_words,
        negative_phrases=neg_phrases,
        strong_word_re=strong_re,
        weak_word_re=weak_re,
        negative_word_re=neg_re,
        is_default=bool(profile.is_default),
        description_ref_vector=ref_vec,
        note_suggested_terms=note_sug,
        location_search_mode=loc_mode,
        location_home_city=loc_city,
        location_target_cities=loc_targets,
    )

# Title-quality positives.
_SENIORITY: set[str] = {
    "senior", "sr.", "sr ", "staff", "principal", "lead", "head of",
    "director", "vp", "vice president", "chief", "architect",
}
_ROLE_WORDS: set[str] = {
    "engineer", "developer", "scientist", "designer", "manager",
    "analyst", "researcher", "specialist", "architect", "strategist",
    "lead", "director", "pm", "product manager", "marketer",
    "recruiter", "operator",
}

# Title-quality negatives (spam-ish).
_SPAM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\$\$\$"),
    re.compile(r"\bcommission[- ]only\b", re.IGNORECASE),
    re.compile(r"\bunlimited earning\b", re.IGNORECASE),
    re.compile(r"\bbe your own boss\b", re.IGNORECASE),
    re.compile(r"\bno experience (needed|required)\b", re.IGNORECASE),
    re.compile(r"\bmake \$\d+", re.IGNORECASE),
    re.compile(r"!!+"),
]

# Provider trust: higher = more likely a real, direct, well-formed listing.
_PROVIDER_TRUST: dict[str, int] = {
    "greenhouse": 10,
    "lever": 10,
    "ashby": 10,
    "workable": 9,
    "smartrecruiters": 9,
    "teamtailor": 9,
    "recruitee": 8,
    "kula": 8,
    "native_jobs_page": 6,
    "jobs_page": 5,
    "binance_native": 6,
    "oracle_native": 4,
}

# Aggregator domains penalise slightly — a listing found only there is lower
# confidence than one sourced from an ATS.
_AGGREGATOR_DOMAINS: set[str] = {
    "jobstash.xyz", "cryptojobslist.com", "web3.career",
    "cryptocurrencyjobs.co", "remotecrypto.io",
}

# Freshness decay: half-life in hours. 5 days ~ 120h.
_FRESHNESS_HALF_LIFE_H: float = 120.0


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ScoreResult:
    """Output of score_job. All scores are in 0..100 range unless noted."""

    ranking_score: Decimal       # goes to jobs.ranking_score
    quality_score: Decimal       # goes to jobs.quality_score
    bucket: str                  # top | strong | maybe | skip
    rationale: str               # human-readable one-liner
    hidden_gem: bool

    freshness_score: Decimal     # 0..20, the freshness component
    fit_score: Decimal           # 0..40, the web3+remote fit component

    details: dict = field(default_factory=dict)  # component breakdown


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------

def _find_strong_hits(text: str, rt: ProfileRuntime) -> list[str]:
    """Return deduped strong Web3 matches found in `text` (word-bounded
    single words + substring-bounded multi-word phrases)."""
    if not text:
        return []
    low = text.lower()
    hits: set[str] = set()
    if rt.strong_word_re is not None:
        for m in rt.strong_word_re.finditer(low):
            hits.add(m.group(1).lower())
    for phrase in _WEB3_STRONG_PHRASES:
        if phrase in low:
            hits.add(phrase)
    for phrase in rt.extra_strong_phrases:
        if phrase in low:
            hits.add(phrase)
    return sorted(hits)


def _find_weak_hits(text: str, rt: ProfileRuntime) -> list[str]:
    if not text:
        return []
    low = text.lower()
    hits: set[str] = set()
    if rt.weak_word_re is not None:
        for m in rt.weak_word_re.finditer(low):
            hits.add(m.group(1).lower())
    for phrase in _WEB3_WEAK_PHRASES:
        if phrase in low:
            hits.add(phrase)
    for phrase in rt.extra_weak_phrases:
        if phrase in low:
            hits.add(phrase)
    return sorted(hits)


def _find_negative_hits(text: str, rt: ProfileRuntime) -> list[str]:
    """Profile-only. Empty list when the profile declares no negatives."""
    if not text or (rt.negative_word_re is None and not rt.negative_phrases):
        return []
    low = text.lower()
    hits: set[str] = set()
    if rt.negative_word_re is not None:
        for m in rt.negative_word_re.finditer(low):
            hits.add(m.group(1).lower())
    for phrase in rt.negative_phrases:
        if phrase in low:
            hits.add(phrase)
    return sorted(hits)


def _score_web3_fit(
    job: Job, rt: ProfileRuntime
) -> tuple[float, list[str]]:
    """0..25. Strong hits in title/company score heaviest."""
    hay_title = " ".join(filter(None, [job.title or "", job.normalized_title or ""]))
    hay_company = " ".join(
        filter(None, [job.company_name or "", job.normalized_company_name or ""])
    )
    hay_desc = job.description_clean or ""

    title_strong = _find_strong_hits(hay_title, rt)
    company_strong = _find_strong_hits(hay_company, rt)
    desc_strong = _find_strong_hits(hay_desc, rt)

    title_weak = _find_weak_hits(hay_title, rt)
    desc_weak = _find_weak_hits(hay_desc, rt)

    score = 0.0
    notes: list[str] = []
    if title_strong:
        score += 12.0
        notes.append(f"web3 in title ({', '.join(title_strong[:2])})")
    if company_strong:
        score += 8.0
        notes.append(f"web3 in company ({', '.join(company_strong[:1])})")
    if desc_strong and not title_strong:
        score += 5.0
        notes.append(f"web3 in description ({', '.join(desc_strong[:1])})")
    if title_weak and not title_strong:
        score += 3.0
        notes.append(f"adjacent signal in title ({title_weak[0]})")
    elif desc_weak and not (title_strong or desc_strong):
        score += 1.5

    return min(score, 25.0), notes


def _score_title_quality(job: Job) -> tuple[float, list[str]]:
    """0..15. Seniority + role word = good. Spam patterns = penalty."""
    title = (job.title or "").strip()
    if not title:
        return 0.0, ["no title"]

    score = 5.0  # baseline for having a title at all
    notes: list[str] = []

    low = title.lower()
    if any(s in low for s in _SENIORITY):
        score += 5.0
        notes.append("seniority")
    if any(r in low for r in _ROLE_WORDS):
        score += 3.0
        notes.append("role word")

    words = [w for w in re.split(r"\s+", title) if w]
    if len(words) < 2:
        score -= 3.0
        notes.append("very short title")
    if title.isupper() and len(title) > 6:
        score -= 2.0
        notes.append("ALL CAPS")

    for pat in _SPAM_PATTERNS:
        if pat.search(title):
            score -= 4.0
            notes.append("spam pattern")
            break

    return max(min(score, 15.0), 0.0), notes


def _score_provider_trust(job: Job, domains: list[str]) -> tuple[float, list[str]]:
    """0..10. ATS providers trusted most; aggregator-only listings discounted."""
    trust = _PROVIDER_TRUST.get((job.provider or "").lower(), 3)
    notes = [f"provider:{job.provider or 'unknown'}={trust}"]

    # Penalise if ONLY seen on aggregator domains.
    if domains and all(d in _AGGREGATOR_DOMAINS for d in domains):
        trust = max(trust - 3, 1)
        notes.append("aggregator-only")

    return float(min(trust, 10)), notes


def _score_freshness(job: Job, now: Optional[datetime] = None) -> tuple[float, list[str]]:
    """0..20. Exponential decay with 5-day half-life, floor at 1."""
    now = now or datetime.now(timezone.utc)
    first = job.first_seen_at or now
    # Be tolerant of naive datetimes from edge cases.
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)

    hours = max((now - first).total_seconds() / 3600.0, 0.0)
    score = 20.0 * math.pow(0.5, hours / _FRESHNESS_HALF_LIFE_H)
    score = max(score, 1.0)

    if hours < 24:
        note = "<24h old"
    elif hours < 24 * 7:
        note = f"{int(hours/24)}d old"
    elif hours < 24 * 30:
        note = f"{int(hours/24)}d old"
    else:
        note = f"{int(hours/24)}d old (stale)"

    return score, [note]


def _score_remote_fit(
    job: Job, rt: ProfileRuntime
) -> tuple[float, list[str]]:
    """0..10. If the profile has a `preferred_remote`, that choice
    gets full credit and the others are penalised. Otherwise the v1
    remote-first default applies."""
    kind = (job.remote_type or "").lower()

    if rt.preferred_remote:
        pref = rt.preferred_remote
        if kind == pref:
            return 10.0, [f"matches preferred:{pref}"]
        if kind in {"remote", "hybrid", "onsite"}:
            return 2.0, [f"{kind} != preferred:{pref}"]
        return 5.0, [f"remote unknown (prefers {pref})"]

    if kind == "remote":
        return 10.0, ["remote"]
    if kind == "hybrid":
        return 6.0, ["hybrid"]
    if kind == "onsite":
        return 2.0, ["onsite"]
    return 5.0, ["remote unknown"]


def _score_duplicate_confidence(sighting_count: int) -> tuple[float, list[str]]:
    """0..10. More independent sightings => higher confidence it's real."""
    if sighting_count <= 0:
        return 2.0, ["no sightings?"]
    if sighting_count == 1:
        return 5.0, ["1 sighting"]
    if sighting_count == 2:
        return 8.0, ["2 sightings"]
    return 10.0, [f"{sighting_count}+ sightings"]


def _score_description_fit(job: Job, rt: ProfileRuntime) -> tuple[float, list[str]]:
    """0..12. Cosine match of job description to profile TF–IDF reference;
    small bonus for overlap with note-mined ``suggested_keywords``."""
    ref = rt.description_ref_vector
    sug = rt.note_suggested_terms
    if not ref and not sug:
        return 0.0, []

    desc = job.description_clean or ""
    vec = ranker_text_svc.job_description_vector(desc)
    cos = ranker_text_svc.cosine_sparse(vec, ref) if ref else 0.0
    raw = cos * 10.5
    hits: list[str] = []
    bonus = 0.0
    if sug:
        toks = set(ranker_text_svc.tokenize(desc))
        low = desc.lower()
        hits = [k for k in sorted(sug) if k in toks or k in low]
        bonus = min(3.5, 0.7 * len(hits))

    total = max(0.0, min(12.0, raw + bonus))
    notes: list[str] = []
    if ref and cos >= 0.25:
        notes.append(f"description fit cos≈{cos:.2f}")
    if hits:
        notes.append(f"note-keyword overlap ({', '.join(hits[:4])})")
    return total, notes


def _score_location_fit(job: Job, rt: ProfileRuntime) -> tuple[float, list[str]]:
    """0..15. Geographic relevance of the job to the user's location preferences.

    For the default search_mode of "remote", remote-tagged jobs score maximum
    and all others score near-neutral — this preserves existing ranking behaviour
    while slightly rewarding explicitly-remote listings.

    City matching is simple substring: "Halifax" matches "Halifax, NS, Canada".
    Geocoding / distance math is deferred to Phase 1 stretch / Phase 3.
    """
    search_mode = rt.location_search_mode
    home_city = rt.location_home_city.strip().lower() if rt.location_home_city else ""
    target_cities = [c.strip().lower() for c in rt.location_target_cities if c.strip()]

    job_loc = (job.location or "").strip().lower()
    remote_type = (job.remote_type or "").strip().lower()
    is_remote = remote_type == "remote" or (not remote_type and "remote" in job_loc)

    def _city_match(city: str) -> bool:
        if not city or not job_loc:
            return False
        return any(seg.strip() in job_loc for seg in city.split(",") if seg.strip())

    if search_mode == "remote":
        if is_remote:
            return 15.0, ["remote job (remote mode)"]
        if not job_loc:
            return 8.0, ["location unknown"]
        return 5.0, ["non-remote in remote mode"]

    if search_mode == "local":
        if not home_city:
            return 8.0, ["no home city set"]
        if is_remote:
            return 3.0, ["remote job (local mode)"]
        if _city_match(home_city):
            return 15.0, [f"near {rt.location_home_city}"]
        if any(_city_match(t) for t in target_cities):
            return 12.0, ["target city match"]
        if not job_loc:
            return 8.0, ["location unknown"]
        return 2.0, ["outside search area"]

    if search_mode == "both":
        if is_remote:
            return 15.0, ["remote job (both mode)"]
        if home_city and _city_match(home_city):
            return 15.0, [f"near {rt.location_home_city}"]
        if any(_city_match(t) for t in target_cities):
            return 12.0, ["target city match"]
        if not job_loc:
            return 8.0, ["location unknown"]
        return 4.0, ["neither remote nor local"]

    if search_mode == "target":
        if not target_cities:
            return 8.0, ["no target cities set"]
        if any(_city_match(t) for t in target_cities):
            return 15.0, ["target city match"]
        if not job_loc:
            return 8.0, ["location unknown"]
        return 2.0, ["not in target cities"]

    # "all" mode — neutral, no boost or penalty
    return 8.0, ["all locations"]


def _detect_hidden_gem(
    *,
    job: Job,
    web3_score: float,
    freshness: float,
    sighting_count: int,
    domains: list[str],
) -> tuple[bool, list[str]]:
    """Hidden gem = strong fit + fresh + single credible source, not aggregator."""
    notes: list[str] = []
    provider = (job.provider or "").lower()
    ats_direct = provider in {
        "greenhouse", "lever", "ashby", "workable",
        "smartrecruiters", "teamtailor", "recruitee", "kula",
    }
    not_aggregator = not any(d in _AGGREGATOR_DOMAINS for d in domains)

    is_gem = (
        web3_score >= 18.0
        and freshness >= 12.0
        and sighting_count <= 1
        and ats_direct
        and not_aggregator
    )
    if is_gem:
        notes.append("hidden gem: strong-fit + fresh + ATS-direct + single-sourced")
    return is_gem, notes


def _bucket_for(score: float) -> str:
    if score >= 75:
        return "top"
    if score >= 55:
        return "strong"
    if score >= 35:
        return "maybe"
    return "skip"


# ---------------------------------------------------------------------------
# Public scoring entrypoint
# ---------------------------------------------------------------------------

def score_job(
    job: Job,
    *,
    sighting_count: int = 1,
    sighting_domains: Optional[list[str]] = None,
    now: Optional[datetime] = None,
    profile: Optional[UserProfile] = None,
    runtime: Optional[ProfileRuntime] = None,
) -> ScoreResult:
    """Pure scorer. Does no DB I/O.

    Args:
        job: the canonical job (already persisted).
        sighting_count: number of rows in job_source_sightings for this job.
        sighting_domains: distinct source_domain values for the sightings.
        now: injectable "current time" for deterministic tests.
        profile: optional UserProfile for per-profile weights/keywords.
            Ignored when `runtime` is provided.
        runtime: optional pre-built ProfileRuntime (use to avoid
            recompiling regex across a batch rescore).

    When neither `profile` nor `runtime` is supplied the scorer uses
    v1-equivalent defaults (all weights 1.0, no keyword extras).
    """
    rt = runtime if runtime is not None else build_runtime(profile)
    domains = sighting_domains or []

    web3, web3_notes = _score_web3_fit(job, rt)
    title_q, title_notes = _score_title_quality(job)
    prov_q, prov_notes = _score_provider_trust(job, domains)
    fresh, fresh_notes = _score_freshness(job, now=now)
    remote_q, remote_notes = _score_remote_fit(job, rt)
    dup_q, dup_notes = _score_duplicate_confidence(sighting_count)
    desc_fit, desc_notes = _score_description_fit(job, rt)
    loc_fit, loc_notes = _score_location_fit(job, rt)

    # quality_score is profile-independent: "is this listing well-formed
    # and trustworthy?" Composed of title_quality (15) + provider_trust
    # (10) + duplicate_confidence (10), normalised to 0..100.
    quality_raw = title_q + prov_q + dup_q
    quality_score = quality_raw * (100.0 / 35.0)

    hidden_gem, gem_notes = _detect_hidden_gem(
        job=job,
        web3_score=web3,
        freshness=fresh,
        sighting_count=sighting_count,
        domains=domains,
    )
    gem_bonus = 10.0 if hidden_gem else 0.0

    # Weighted ranking. Each component's raw score is multiplied by its
    # profile weight; the base maximum (sum of COMPONENT_MAX * weight for
    # the base components) is used to normalise to 0..100.
    actuals: dict[str, float] = {
        "web3_fit": web3,
        "title_quality": title_q,
        "provider_trust": prov_q,
        "freshness": fresh,
        "remote_fit": remote_q,
        "duplicate_confidence": dup_q,
        "description_fit": desc_fit,
        "location_fit": loc_fit,
        "hidden_gem_bonus": gem_bonus,
    }
    weights = rt.weights

    has_text_fit = bool(rt.description_ref_vector or rt.note_suggested_terms)
    active_base = tuple(
        c
        for c in _BASE_COMPONENTS
        if c != "description_fit" or has_text_fit
    )
    weighted_base = sum(
        COMPONENT_MAX[c] * weights.get(c, 1.0) for c in active_base
    )
    weighted_raw = sum(
        actuals[c] * weights.get(c, 1.0) for c in active_base
    )
    weighted_gem = gem_bonus * weights.get("hidden_gem_bonus", 1.0)

    if weighted_base > 0:
        ranking_score = (weighted_raw + weighted_gem) * (100.0 / weighted_base)
    else:
        ranking_score = 0.0
    ranking_score = max(min(ranking_score, 100.0), 0.0)

    # Negative-keyword penalty (post-normalization). Title/company hits
    # are heavy, description hits lighter. Capped to preserve a valid
    # 0..100 range.
    negative_notes: list[str] = []
    negative_details: dict[str, list[str]] = {}
    if rt.negative_word_re is not None or rt.negative_phrases:
        hay_title = " ".join(
            filter(None, [job.title or "", job.normalized_title or ""])
        )
        hay_company = job.company_name or ""
        hay_desc = job.description_clean or ""

        title_neg = _find_negative_hits(hay_title + " " + hay_company, rt)
        desc_neg = _find_negative_hits(hay_desc, rt)
        penalty = 0.0
        if title_neg:
            penalty += 15.0
            negative_notes.append(
                f"neg in title/company ({', '.join(title_neg[:2])})"
            )
            negative_details["title"] = title_neg
        if desc_neg and not title_neg:
            penalty += 5.0
            negative_notes.append(
                f"neg in description ({', '.join(desc_neg[:1])})"
            )
            negative_details["description"] = desc_neg

        if penalty > 0:
            ranking_score = max(ranking_score - penalty, 0.0)

    synergy_notes: list[str] = []
    synergy = float(get_settings().ranker_synergy_profile_fit_boost)
    if synergy > 0 and has_text_fit:
        wmax = COMPONENT_MAX["web3_fit"]
        dmax = COMPONENT_MAX["description_fit"]
        if web3 >= 0.6 * wmax and desc_fit >= 0.6 * dmax:
            ranking_score = min(100.0, ranking_score + synergy)
            synergy_notes.append(
                f"synergy +{synergy:.1f} (strong web3 + description fit)"
            )

    bucket = _bucket_for(ranking_score)

    notes_all = (
        web3_notes + title_notes + prov_notes + fresh_notes
        + remote_notes + dup_notes + desc_notes + loc_notes + gem_notes
        + negative_notes + synergy_notes
    )
    rationale = " | ".join([n for n in notes_all if n])[:480]

    details: dict[str, Any] = {
        "web3_fit": round(web3, 2),
        "title_quality": round(title_q, 2),
        "provider_trust": round(prov_q, 2),
        "freshness": round(fresh, 2),
        "remote_fit": round(remote_q, 2),
        "duplicate_confidence": round(dup_q, 2),
        "description_fit": round(desc_fit, 2),
        "location_fit": round(loc_fit, 2),
        "hidden_gem_bonus": round(gem_bonus, 2),
        "weighted_raw": round(weighted_raw + weighted_gem, 2),
        "weighted_base": round(weighted_base, 2),
        "quality_raw": round(quality_raw, 2),
        "sighting_count": sighting_count,
        "sighting_domains": domains,
        "profile_slug": rt.slug,
        "weights": {k: round(v, 3) for k, v in weights.items()},
    }
    if negative_details:
        details["negative_hits"] = negative_details

    return ScoreResult(
        ranking_score=Decimal(f"{ranking_score:.3f}"),
        quality_score=Decimal(f"{quality_score:.3f}"),
        bucket=bucket,
        rationale=rationale,
        hidden_gem=hidden_gem,
        freshness_score=Decimal(f"{fresh:.3f}"),
        fit_score=Decimal(f"{(web3 + remote_q + 0.35 * desc_fit):.3f}"),
        details=details,
    )


# ---------------------------------------------------------------------------
# DB driver
# ---------------------------------------------------------------------------

def _load_location_ctx(db: Session) -> dict:
    """Load location preferences from candidate_profiles for build_runtime."""
    try:
        row = db.query(CandidateProfile).first()
        if row:
            return {
                "search_mode": row.search_mode or "remote",
                "home_city": row.home_city or "",
                "target_cities": list(row.target_cities or []),
            }
    except Exception:
        pass
    return {"search_mode": "remote", "home_city": "", "target_cities": []}


@dataclass
class RankerStats:
    scored: int = 0
    failed: int = 0
    by_bucket: dict[str, int] = field(default_factory=dict)
    hidden_gems: int = 0

    def bump(self, bucket: str) -> None:
        self.by_bucket[bucket] = self.by_bucket.get(bucket, 0) + 1


def _gather_sighting_stats(
    db: Session, job_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, list[str]]]:
    """Return {job_id: (count, [distinct_domains])} for the given job ids."""
    if not job_ids:
        return {}

    count_stmt = (
        select(JobSourceSighting.job_id, func.count(JobSourceSighting.id))
        .where(JobSourceSighting.job_id.in_(job_ids))
        .group_by(JobSourceSighting.job_id)
    )
    counts: dict[uuid.UUID, int] = {
        row[0]: int(row[1]) for row in db.execute(count_stmt).all()
    }

    dom_stmt = (
        select(JobSourceSighting.job_id, JobSourceSighting.source_domain)
        .where(JobSourceSighting.job_id.in_(job_ids))
        .distinct()
    )
    domains: dict[uuid.UUID, list[str]] = {}
    for job_id, domain in db.execute(dom_stmt).all():
        domains.setdefault(job_id, []).append(domain)

    return {
        jid: (counts.get(jid, 0), domains.get(jid, []))
        for jid in job_ids
    }


def _upsert_user_job_score(
    db: Session,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    result: "ScoreResult",
    profile_slug: Optional[str],
) -> None:
    """INSERT ... ON CONFLICT DO UPDATE for user_job_scores.

    Keeps exactly one current row per (user_id, job_id); audit history
    lives in job_scores which is append-only.
    """
    import uuid as _uuid
    stmt = (
        pg_insert(UserJobScore)
        .values(
            id=_uuid.uuid4(),
            user_id=user_id,
            job_id=job_id,
            score=float(result.ranking_score),
            scored_at=datetime.now(timezone.utc),
            profile_slug=profile_slug,
            hidden_gem=result.hidden_gem,
            bucket=result.bucket,
            rationale=result.rationale,
        )
        .on_conflict_do_update(
            constraint="uq_user_job_scores_user_job",
            set_={
                "score": float(result.ranking_score),
                "scored_at": datetime.now(timezone.utc),
                "profile_slug": profile_slug,
                "hidden_gem": result.hidden_gem,
                "bucket": result.bucket,
                "rationale": result.rationale,
            },
        )
    )
    db.execute(stmt)


def rescore_jobs(
    db: Session,
    *,
    provider: Optional[str] = None,
    only_active: bool = True,
    only_unscored: bool = False,
    limit: Optional[int] = None,
    now: Optional[datetime] = None,
    profile: Optional[UserProfile] = None,
    user_id: Optional[uuid.UUID] = None,
) -> RankerStats:
    """Score (or re-score) a batch of canonical jobs.

    Args:
        provider: if set, restrict to jobs with this provider.
        only_active: if True (default), skip jobs with is_active=False.
        only_unscored: if True, only score jobs that have never been scored
            (quality_score == 0 AND ranking_score == 0, only meaningful for
            the default profile since v2 always writes per-profile rows).
        limit: cap rows processed (useful for progressive backfills).
        now: injectable clock.
        profile: if set, score against this profile and write per-profile
            `job_scores` rows. `jobs.ranking_score` / `jobs.quality_score`
            are only updated when scoring the default profile (or when
            no profile is supplied).

    Commits once at the end.
    """
    stats = RankerStats()
    runtime = build_runtime(profile, location_ctx=_load_location_ctx(db))
    # Only the default profile (or unspecified) overwrites the summary
    # columns on Job; other profiles only add job_scores rows.
    write_job_columns = profile is None or bool(getattr(profile, "is_default", False))
    effective_user_id = user_id or SEEDED_LOCAL_USER_ID

    stmt = select(Job)
    if provider:
        stmt = stmt.where(Job.provider == provider)
    if only_active:
        stmt = stmt.where(Job.is_active.is_(True))
    if only_unscored and write_job_columns:
        stmt = stmt.where(Job.ranking_score == 0, Job.quality_score == 0)
    stmt = stmt.order_by(Job.last_seen_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)

    jobs: list[Job] = list(db.execute(stmt).scalars().all())
    if not jobs:
        return stats

    sight_map = _gather_sighting_stats(db, [j.id for j in jobs])

    for job in jobs:
        count, domains = sight_map.get(job.id, (1, []))
        try:
            result = score_job(
                job,
                sighting_count=count,
                sighting_domains=domains,
                now=now,
                runtime=runtime,
            )
        except Exception as e:  # noqa: BLE001
            stats.failed += 1
            db.add(
                PipelineEvent(
                    entity_type="job",
                    entity_id=job.id,
                    event_name="rank_failed",
                    details={
                        "error_type": type(e).__name__,
                        "message": str(e)[:500],
                        "profile_slug": runtime.slug,
                    },
                )
            )
            continue

        if write_job_columns:
            job.ranking_score = result.ranking_score
            job.quality_score = result.quality_score

        db.add(
            JobScore(
                job_id=job.id,
                profile_id=runtime.profile_id,
                score=result.ranking_score,
                bucket=result.bucket,
                rationale=result.rationale,
                hidden_gem=result.hidden_gem,
                freshness_score=result.freshness_score,
                fit_score=result.fit_score,
            )
        )

        # Upsert into user_job_scores — one current row per (user, job).
        _upsert_user_job_score(
            db,
            user_id=effective_user_id,
            job_id=job.id,
            result=result,
            profile_slug=runtime.slug,
        )

        stats.scored += 1
        stats.bump(result.bucket)
        if result.hidden_gem:
            stats.hidden_gems += 1

    db.commit()
    return stats


def rescore_one(
    db: Session,
    job_id: uuid.UUID,
    *,
    now: Optional[datetime] = None,
    profile: Optional[UserProfile] = None,
    user_id: Optional[uuid.UUID] = None,
) -> Optional[ScoreResult]:
    """Rescore a single job by id. Returns None if the job is missing."""
    job = db.get(Job, job_id)
    if job is None:
        return None
    count_row = db.execute(
        select(func.count(JobSourceSighting.id)).where(
            JobSourceSighting.job_id == job_id
        )
    ).scalar_one_or_none()
    count = int(count_row or 0)
    dom_rows = db.execute(
        select(JobSourceSighting.source_domain)
        .where(JobSourceSighting.job_id == job_id)
        .distinct()
    ).all()
    domains = [r[0] for r in dom_rows]

    runtime = build_runtime(profile, location_ctx=_load_location_ctx(db))
    result = score_job(
        job,
        sighting_count=count,
        sighting_domains=domains,
        now=now,
        runtime=runtime,
    )

    write_job_columns = profile is None or bool(getattr(profile, "is_default", False))
    if write_job_columns:
        job.ranking_score = result.ranking_score
        job.quality_score = result.quality_score
    db.add(
        JobScore(
            job_id=job.id,
            profile_id=runtime.profile_id,
            score=result.ranking_score,
            bucket=result.bucket,
            rationale=result.rationale,
            hidden_gem=result.hidden_gem,
            freshness_score=result.freshness_score,
            fit_score=result.fit_score,
        )
    )
    _upsert_user_job_score(
        db,
        user_id=user_id or SEEDED_LOCAL_USER_ID,
        job_id=job.id,
        result=result,
        profile_slug=runtime.slug,
    )
    db.commit()
    return result


def score_job_dry(
    db: Session,
    job_id: uuid.UUID,
    *,
    profile: UserProfile,
    now: Optional[datetime] = None,
) -> Optional[ScoreResult]:
    """Score a single job against a profile WITHOUT persisting any rows.
    Returns None when the job doesn't exist. Used by the admin UI's
    'test this profile' button."""
    job = db.get(Job, job_id)
    if job is None:
        return None
    count_row = db.execute(
        select(func.count(JobSourceSighting.id)).where(
            JobSourceSighting.job_id == job_id
        )
    ).scalar_one_or_none()
    count = int(count_row or 0)
    dom_rows = db.execute(
        select(JobSourceSighting.source_domain)
        .where(JobSourceSighting.job_id == job_id)
        .distinct()
    ).all()
    domains = [r[0] for r in dom_rows]

    runtime = build_runtime(profile, location_ctx=_load_location_ctx(db))
    return score_job(
        job,
        sighting_count=count,
        sighting_domains=domains,
        now=now,
        runtime=runtime,
    )
