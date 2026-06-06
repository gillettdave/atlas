"""Jobicy remote jobs aggregator collector.

Free public JSON API — no auth required. Strong coverage of remote marketing,
community, operations, and customer success roles.

API docs: https://jobicy.com/jobs-rss-feed
Endpoint: GET https://jobicy.com/api/v2/remote-jobs
  - Returns JSON: { jobs: [...], jobCount: N, ... }
  - Single response (no pagination) — up to 50 jobs per call.
  - Filters: count (1-50), geo, industry, tag (title+description keyword).
  - Posts have a 6-hour intentional delay; poll at most once per hour.

Usage policy: attribute links back to Jobicy.com. Do not syndicate to
Google Jobs, LinkedIn, Jooble, etc.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import get_settings
from .base import RawCollectedRecord, SourceRow, now_iso
from .http_utils import json_from_get

_API_BASE = "https://jobicy.com/api/v2/remote-jobs"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AtlasJobSearch/1.0; aggregator; +https://example.invalid)"
    ),
    "Accept": "application/json",
}

# Industry values Jobicy accepts (server-side filter).
# We request each relevant industry separately to maximise recall.
_INDUSTRIES: list[str] = [
    "marketing",
    "customer-support",
    "business",
    "management",
    "design",
    "hr",
    "sales",
]

# Post-fetch title keyword filter — keeps only target roles.
_ROLE_INCLUDE: frozenset[str] = frozenset({
    "community",
    "marketing",
    "growth",
    "content",
    "social media",
    "customer success",
    "customer support",
    "devrel",
    "developer relations",
    "developer advocate",
    "communications",
    "brand",
    "partnerships",
    "ecosystem",
    "engagement",
    "operations",
    "product manager",
    "product management",
    "go-to-market",
    "gtm",
    "advocacy",
    "account manager",
    "program manager",
    "seo",
})

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub(" ", text)).strip()


def _parse_date(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    # Jobicy returns ISO-8601 with timezone offset, e.g. "2026-06-03T13:34:32+00:00"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


def _matches_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _ROLE_INCLUDE)


def collect_jobicy(row: SourceRow) -> tuple[list[RawCollectedRecord], str]:
    """Collect jobs from the Jobicy public API.

    Iterates over target industries, deduplicates by job ID, applies title
    filter, and respects ``jobicy_max_jobs`` + ``jobicy_max_age_days`` settings.
    """
    s = get_settings()
    max_jobs: int = max(1, int(getattr(s, "jobicy_max_jobs", 200)))
    max_age_days: int = max(1, int(getattr(s, "jobicy_max_age_days", 14)))
    count_per_call: int = min(50, max(1, int(getattr(s, "jobicy_count_per_call", 50))))

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    seen_ids: set[str] = set()
    records: list[RawCollectedRecord] = []

    for industry in _INDUSTRIES:
        if len(records) >= max_jobs:
            break

        params = f"count={count_per_call}&industry={industry}"
        url = f"{_API_BASE}?{params}"

        data, err = json_from_get(url, headers=_HEADERS)
        if err:
            # Skip this industry on error; try the next.
            continue

        if not isinstance(data, dict):
            continue

        jobs = data.get("jobs")
        if not isinstance(jobs, list) or not jobs:
            continue

        for job in jobs:
            if not isinstance(job, dict):
                continue

            title = str(job.get("jobTitle") or "").strip()
            if not title:
                continue

            # Title-based role filter
            if not _matches_role(title):
                continue

            # Dedup by Jobicy job ID
            job_id = str(job.get("id") or "").strip()
            if job_id and job_id in seen_ids:
                continue
            if job_id:
                seen_ids.add(job_id)

            # Age filter
            published_at = _parse_date(job.get("pubDate"))
            if published_at and published_at < cutoff:
                continue

            company = str(job.get("companyName") or "").strip()
            job_url = str(job.get("url") or "").strip()

            # Location / remote
            geo = str(job.get("jobGeo") or "").strip()
            remote_hint: bool | None = None
            if geo:
                if geo.lower() in {"worldwide", "remote", "anywhere"}:
                    remote_hint = True
                else:
                    remote_hint = False

            # Employment type — Jobicy returns a list
            job_types = job.get("jobType") or []
            employment_type = ", ".join(str(t) for t in job_types) if isinstance(job_types, list) else ""

            # Industries — Jobicy returns a list
            industries = job.get("jobIndustry") or []
            industry_str = ", ".join(str(i) for i in industries) if isinstance(industries, list) else ""

            # Description — strip HTML
            description_raw = str(job.get("jobDescription") or job.get("jobExcerpt") or "")
            description_clean = _strip_html(description_raw)[:50_000]

            payload: dict[str, Any] = {
                "company_name": company,
                "job_title": title,
                "job_url": job_url,
                "apply_url": job_url,
                "location": geo,
                "description_clean": description_clean,
                "employment_type": employment_type,
                "external_job_id": job_id,
                "source_type": "jobicy_agg",
                "remote_hint": remote_hint,
                "jobicy_industry": industry_str,
                "jobicy_level": str(job.get("jobLevel") or "").strip(),
                "jobicy_pub_date": job.get("pubDate"),
                "collected_at": now_iso(),
                "collection_method": "jobicy_api",
            }

            records.append(
                RawCollectedRecord(
                    provider="jobicy",
                    source_url=job_url or url,
                    raw_payload=payload,
                )
            )

            if len(records) >= max_jobs:
                break

    return records, ("" if records else "jobicy_no_matching_jobs")
