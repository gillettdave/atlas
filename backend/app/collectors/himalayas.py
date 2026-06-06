"""Himalayas remote jobs aggregator collector.

Free public JSON API — no auth required. Remote-first job board with strong
coverage of marketing, community, operations, and customer success roles.

API docs: https://himalayas.app/api
Browse endpoint:  GET https://himalayas.app/jobs/api?limit=20&offset=N
Search endpoint:  GET https://himalayas.app/jobs/api/search?q=KEYWORD&limit=20&page=N

Usage policy: attribute links back to Himalayas.app. Rate limit enforced
server-side (429 on excess). Default page size capped at 20.
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import get_settings
from .base import RawCollectedRecord, SourceRow, now_iso
from .http_utils import json_from_get

_BROWSE_URL = "https://himalayas.app/jobs/api"
_SEARCH_URL = "https://himalayas.app/jobs/api/search"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AtlasJobSearch/1.0; aggregator; +https://example.invalid)"
    ),
    "Accept": "application/json",
}

# Search queries targeting our roles. The search endpoint is more precise
# than the browse endpoint, so we run several focused passes.
_SEARCH_QUERIES: list[str] = [
    "community manager",
    "developer relations",
    "devrel",
    "marketing manager",
    "growth marketing",
    "content marketing",
    "customer success",
    "customer support",
    "brand marketing",
    "social media",
    "communications manager",
    "partnerships manager",
    "product marketing",
    "operations manager",
]

# Post-fetch title keyword filter (belt-and-suspenders).
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
    "product marketing",
    "go-to-market",
    "gtm",
    "advocacy",
    "account manager",
    "program manager",
    "seo",
})

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PAGE_SIZE = 20  # Himalayas caps at 20


def _strip_html(text: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub(" ", text)).strip()


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse pubDate (Unix ms or seconds) or ISO string."""
    if isinstance(raw, (int, float)):
        try:
            # Himalayas returns Unix seconds (not ms)
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError:
            return None
    return None


def _matches_role(title: str, categories: list[str]) -> bool:
    combined = (title + " " + " ".join(categories)).lower()
    return any(kw in combined for kw in _ROLE_INCLUDE)


def _build_record(job: dict[str, Any], collected_url: str) -> RawCollectedRecord | None:
    title = str(job.get("title") or "").strip()
    if not title:
        return None

    company = str(job.get("companyName") or "").strip()
    apply_url = str(job.get("applicationLink") or "").strip()
    guid = str(job.get("guid") or "").strip()

    # Location / remote — Himalayas is remote-first; flag accordingly
    location_restrictions = job.get("locationRestrictions") or []
    location_str = ", ".join(str(l) for l in location_restrictions) if isinstance(location_restrictions, list) else ""
    remote_hint: bool = True  # all Himalayas jobs are remote

    # Employment type
    employment_type = str(job.get("employmentType") or "").strip()

    # Categories
    categories = job.get("categories") or []
    if not isinstance(categories, list):
        categories = []
    category_str = ", ".join(str(c) for c in categories)

    # Salary
    salary_parts: list[str] = []
    if job.get("minSalary"):
        salary_parts.append(f"${job['minSalary']:,}")
    if job.get("maxSalary"):
        salary_parts.append(f"${job['maxSalary']:,}")
    salary_text = " – ".join(salary_parts)

    # Description — strip HTML
    description_raw = str(job.get("description") or job.get("excerpt") or "")
    description_clean = _strip_html(description_raw)[:50_000]

    # Published date
    published_at = _parse_timestamp(job.get("pubDate"))

    payload: dict[str, Any] = {
        "company_name": company,
        "job_title": title,
        "job_url": apply_url,
        "apply_url": apply_url,
        "location": location_str or "Remote",
        "description_clean": description_clean,
        "employment_type": employment_type,
        "salary_text": salary_text,
        "external_job_id": guid,
        "source_type": "himalayas_agg",
        "remote_hint": remote_hint,
        "himalayas_categories": category_str,
        "himalayas_seniority": ", ".join(job.get("seniority") or []),
        "himalayas_pub_date": published_at.isoformat(timespec="seconds") if published_at else None,
        "collected_at": now_iso(),
        "collection_method": "himalayas_api",
    }

    return RawCollectedRecord(
        provider="himalayas",
        source_url=apply_url or collected_url,
        raw_payload=payload,
    )


def collect_himalayas(row: SourceRow) -> tuple[list[RawCollectedRecord], str]:
    """Collect jobs from the Himalayas public API.

    Runs targeted search queries for each role type, paginates results,
    deduplicates by GUID, and applies age + title filters.
    Bounded by ``himalayas_max_jobs`` setting.
    """
    s = get_settings()
    max_jobs: int = max(1, int(getattr(s, "himalayas_max_jobs", 300)))
    max_age_days: int = max(1, int(getattr(s, "himalayas_max_age_days", 14)))
    max_pages_per_query: int = max(1, int(getattr(s, "himalayas_max_pages_per_query", 5)))
    page_gap: float = max(0.0, float(getattr(s, "himalayas_page_gap_seconds", 0.5)))

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    seen_guids: set[str] = set()
    records: list[RawCollectedRecord] = []

    for query in _SEARCH_QUERIES:
        if len(records) >= max_jobs:
            break

        for page in range(1, max_pages_per_query + 1):
            if len(records) >= max_jobs:
                break

            q_enc = query.replace(" ", "+")
            url = f"{_SEARCH_URL}?q={q_enc}&limit={_PAGE_SIZE}&page={page}"
            data, err = json_from_get(url, headers=_HEADERS)
            if err:
                break  # skip remaining pages for this query on error

            if not isinstance(data, dict):
                break

            jobs = data.get("jobs")
            if not isinstance(jobs, list) or not jobs:
                break

            for job in jobs:
                if not isinstance(job, dict):
                    continue

                title = str(job.get("title") or "").strip()
                categories = job.get("categories") or []
                if not isinstance(categories, list):
                    categories = []

                # Role filter
                if not _matches_role(title, [str(c) for c in categories]):
                    continue

                # Dedup
                guid = str(job.get("guid") or "").strip()
                if guid and guid in seen_guids:
                    continue
                if guid:
                    seen_guids.add(guid)

                # Age filter
                published_at = _parse_timestamp(job.get("pubDate"))
                if published_at and published_at < cutoff:
                    continue

                record = _build_record(job, url)
                if record:
                    records.append(record)
                    if len(records) >= max_jobs:
                        break

            # Himalayas search: if fewer results than page size, we're on the last page
            if len(jobs) < _PAGE_SIZE:
                break

            if page_gap > 0:
                time.sleep(page_gap)

    return records, ("" if records else "himalayas_no_matching_jobs")
