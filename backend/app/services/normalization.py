"""Text / identifier normalization used by cleaner_v2 and matching.

Design goals:
- Deterministic.
- No external calls.
- Safe on empty / weird input.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = [
    "normalize_company",
    "normalize_title",
    "normalize_location",
    "normalize_remote_type",
    "description_hash",
]


# Suffixes that add no identity value for dedupe.
_COMPANY_SUFFIX_RE = re.compile(
    r"\b("
    r"inc|inc\.?|incorporated|"
    r"llc|l\.l\.c\.?|"
    r"ltd|ltd\.?|limited|"
    r"gmbh|s\.a\.?|sa|ag|ab|plc|"
    r"co|co\.?|corp|corp\.?|corporation|"
    r"holdings|group|labs|technologies|technology|tech|"
    r"foundation|protocol|network|dao"
    r")\b\.?",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def normalize_company(name: str | None) -> str:
    """Canonicalize company name for matching.

    - Lowercase, strip accents
    - Remove corporate suffixes (inc, llc, ltd, ...)
    - Collapse non-alphanumeric to single space
    """
    if not name:
        return ""
    s = _strip_accents(name).lower().strip()
    s = _COMPANY_SUFFIX_RE.sub(" ", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


# Tokens worth keeping as-is for seniority / scope signals.
_TITLE_NOISE_RE = re.compile(
    r"\b(full[\s-]?time|part[\s-]?time|contract|remote|onsite|hybrid|"
    r"w/|w\\|and|&|the|a|an)\b",
    re.IGNORECASE,
)


def normalize_title(title: str | None) -> str:
    """Canonicalize a job title for matching.

    - Lowercase, strip accents
    - Remove parentheticals / brackets
    - Strip trailing location suffixes like " - Remote" or " (US)"
    - Drop common noise words
    - Collapse to alnum+space
    """
    if not title:
        return ""
    s = _strip_accents(title).lower().strip()

    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\[.*?\]", " ", s)

    s = re.sub(r"\s+[-–—]\s+(remote|hybrid|onsite|on[\s-]?site|us|uk|eu|emea|apac|global).*$", " ", s)

    s = _TITLE_NOISE_RE.sub(" ", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def normalize_location(location: str | None) -> str:
    if not location:
        return ""
    s = _strip_accents(location).lower().strip()
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


_REMOTE_KEYWORDS = ("remote", "anywhere", "distributed", "work from home", "wfh")
_HYBRID_KEYWORDS = ("hybrid",)
_ONSITE_KEYWORDS = ("onsite", "on-site", "on site", "in office", "in-office")


def normalize_remote_type(raw: str | None) -> str | None:
    """Return one of: remote | hybrid | onsite | None."""
    if not raw:
        return None
    s = raw.lower()
    if any(k in s for k in _REMOTE_KEYWORDS):
        return "remote"
    if any(k in s for k in _HYBRID_KEYWORDS):
        return "hybrid"
    if any(k in s for k in _ONSITE_KEYWORDS):
        return "onsite"
    return None


def description_hash(text: str | None) -> str | None:
    """Stable fingerprint of a description for weak-match comparisons.

    Lowercase, collapse whitespace, then sha1 hex digest. None if no text.
    """
    if not text:
        return None
    s = text.lower()
    s = _WHITESPACE_RE.sub(" ", s).strip()
    if not s:
        return None
    return hashlib.sha1(s.encode("utf-8")).hexdigest()
