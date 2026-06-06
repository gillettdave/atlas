"""URL canonicalization.

Required by cleaner_v2 Tier-1 matching (same canonicalized apply_url ->
match existing canonical job). Keep this pure and fast.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

__all__ = ["canonicalize_url", "source_domain"]


# Query params to strip. Includes utm_*, common tracking, and known
# ATS decorative params that don't change identity.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_EXACT = {
    "gh_src",
    "gh_jid",  # keep? no — the path usually carries identity
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
    "src",
    "lever-source",
    "lever-via",
    "ashby_jid",  # path carries identity
    "hsCtaTracking",
    "hsa_cam",
    "hsa_grp",
}

# Hosts we want to flatten to bare scheme+host+path with no query at all,
# because identity lives entirely in the path for these providers.
_FLATTEN_HOSTS = {
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "apply.workable.com",
    "jobs.smartrecruiters.com",
    "jobs.teamtailor.com",
    "career.teamtailor.com",
    "careers.kula.ai",
}

# Greenhouse is special: the embed form uses ?for=<slug>, and the board_token
# is part of identity. We keep only whitelisted params for these hosts.
_GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
_GREENHOUSE_KEEP_PARAMS = {"for"}


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    if k in _TRACKING_EXACT:
        return True
    return any(k.startswith(p) for p in _TRACKING_PREFIXES)


def canonicalize_url(url: str | None) -> str:
    """Return a canonical form of the given URL.

    Rules:
    - empty / None -> ""
    - lower-case scheme + host
    - force scheme to https (promote http)
    - strip default ports (:80, :443)
    - strip fragment
    - strip trailing slash on path (except root "/")
    - drop tracking params (utm_*, gclid, fbclid, ref, source, ...)
    - for known ATS hosts, flatten all query params
    - for greenhouse embed hosts, keep only identity-bearing params
    - sort remaining query params for determinism
    """
    if not url:
        return ""
    raw = url.strip()
    if not raw:
        return ""

    # Be tolerant of missing scheme.
    if "://" not in raw:
        raw = "https://" + raw

    p = urlparse(raw)
    if not p.netloc or p.netloc == ".":
        return ""

    scheme = "https" if p.scheme in ("", "http", "https") else p.scheme.lower()
    host = p.hostname.lower() if p.hostname else p.netloc.lower()
    # Drop default ports; preserve non-default ports.
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"

    path = p.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Query handling
    query_pairs = parse_qsl(p.query, keep_blank_values=False)

    if host in _FLATTEN_HOSTS:
        query_pairs = []
    elif host in _GREENHOUSE_HOSTS:
        query_pairs = [
            (k, v) for (k, v) in query_pairs
            if k.lower() in _GREENHOUSE_KEEP_PARAMS
        ]
    else:
        query_pairs = [
            (k, v) for (k, v) in query_pairs
            if not _is_tracking_param(k)
        ]

    query_pairs.sort(key=lambda kv: (kv[0].lower(), kv[1]))
    query = urlencode(query_pairs, doseq=True)

    return urlunparse((scheme, host, path, "", query, ""))


def source_domain(url: str | None) -> str:
    """Return the bare registrable host (lowercase, no port) for a URL."""
    if not url:
        return ""
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    p = urlparse(raw)
    host = (p.hostname or p.netloc or "").lower()
    return host
