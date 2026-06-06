"""The Muse job board collector.

Free public API — no auth required (500 req/hr unauthenticated, 3600/hr with key).
Strong coverage of marketing, community, operations, and customer success roles.

API docs: https://www.themuse.com/developers/api/v2
Endpoint: GET https://www.themuse.com/api/public/jobs
  - Returns JSON: { page, page_count, results: [...] }
  - Up to 20 results per page, paginated via ?page=N (0-indexed).
  - Optional filters: category, level, location, company.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from .base import RawCollectedRecord, SourceRow, now_iso
from .http_utils import json_from_get

_API_BASE = "https://www.themuse.com/api/public/jobs"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AtlasJobSearch/1.0; aggregator; +https://example.invalid)"
    ),
    "Accept": "application/json",
}

# Categories to request — The Muse uses these exact strings
_CATEGORIES = [
    "Marketing and PR",
    "Customer Service",
    "Business and Strategy",
    "Operations",
    "Sales",
    "Social Media and Community",
    "Content",
    "Communications",
    "Account Management",
    "Project and Program Management",
]

# Post-fetch title keyword filter (same pattern as Arbeitnow)
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
})


def _parse_date(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
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


def collect_themuse(row: SourceRow) -> tuple[list[RawCollectedRecord], str]:
    """Collect jobs from The Muse public API.

    Iterates over target categories, paginates each, applies title filter.
    Bounded by ``themuse_max_jobs`` config setting.
    """
    s = get_settings()
    max_jobs: int = max(1, int(getattr(s, "themuse_max_jobs", 200)))
    max_pages_per_cat: int = max(1, int(getattr(s, "themuse_max_pages_per_category", 5)))
    page_gap: float = max(0.0, float(getattr(s, "themuse_page_gap_seconds", 0.5)))
    api_key: str | None = getattr(s, "themuse_api_key", None) or None

    seen_ids: set[str] = set()
    records: list[RawCollectedRecord] = []

    for category in _CATEGORIES:
        if len(records) >= max_jobs:
            break

        for page in range(max_pages_per_cat):
            if len(records) >= max_jobs:
                break

            params: dict[str, str] = {
                "category": category,
                "page": str(page),
            }
            if api_key:
                params["api_key"] = api_key

            qs = "&".join(f"{k}={v.replace(' ', '%20')}" for k, v in params.items())
            url = f"{_API_BASE}?{qs}"

            data, err = json_from_get(url, headers=_HEADERS)
            if err:
                if page == 0:
                    break  # skip this category on first-page error
                break

            if not isinstance(data, dict):
                break

            results = data.get("results")
            if not isinstance(results, list) or not results:
                break

            for job in results:
                if not isinstance(job, dict):
                    continue

                title = str(job.get("name") or "").strip()
                if not title:
                    continue

                # Title-based role filter
                if not _matches_role(title):
                    continue

                # Dedup by The Muse job ID
                job_id = str(job.get("id") or "").strip()
                if job_id and job_id in seen_ids:
                    continue
                if job_id:
                    seen_ids.add(job_id)

                # Company
                company_obj = job.get("company") or {}
                company = str(company_obj.get("name") or "").strip() if isinstance(company_obj, dict) else ""

                # Location — The Muse returns a list of location objects
                locations = job.get("locations") or []
                location_str = ""
                if isinstance(locations, list) and locations:
                    loc_names = [
                        str(loc.get("name") or "").strip()
                        for loc in locations
                        if isinstance(loc, dict) and loc.get("name")
                    ]
                    location_str = " | ".join(loc_names[:3])

                # Remote hint
                remote_hint: bool | None = None
                if location_str:
                    loc_lower = location_str.lower()
                    if "remote" in loc_lower or "flexible" in loc_lower:
                        remote_hint = True
                    elif any(c.isalpha() for c in loc_lower):
                        remote_hint = False

                # Apply URL
                refs = job.get("refs") or {}
                apply_url = str(refs.get("landing_page") or "").strip() if isinstance(refs, dict) else ""
                if not apply_url:
                    apply_url = f"https://www.themuse.com/jobs/{job_id}" if job_id else ""

                # Level
                levels = job.get("levels") or []
                level_str = ""
                if isinstance(levels, list) and levels:
                    level_str = ", ".join(
                        str(lv.get("name") or "").strip()
                        for lv in levels
                        if isinstance(lv, dict)
                    )

                # Published date
                published_at = _parse_date(job.get("publication_date"))

                payload: dict[str, Any] = {
                    "company_name": company,
                    "job_title": title,
                    "job_url": apply_url,
                    "apply_url": apply_url,
                    "location": location_str,
                    "description_clean": str(job.get("contents") or "")[:50_000],
                    "employment_type": level_str,
                    "external_job_id": job_id,
                    "source_type": "themuse_agg",
                    "remote_hint": remote_hint,
                    "themuse_category": category,
                    "themuse_published_at": published_at.isoformat(timespec="seconds") if published_at else None,
                    "collected_at": now_iso(),
                    "collection_method": "themuse_api",
                }

                records.append(
                    RawCollectedRecord(
                        provider="themuse",
                        source_url=apply_url or url,
                        raw_payload=payload,
                    )
                )

                if len(records) >= max_jobs:
                    break

            # Stop paginating this category if we're on the last page
            page_count = int(data.get("page_count") or 1)
            if page >= page_count - 1:
                break

            if page_gap > 0:
                time.sleep(page_gap)

    return records, ("" if records else "themuse_no_matching_jobs")
