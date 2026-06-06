"""Arbeitnow aggregator collector.

Fetches the free Arbeitnow public jobs API — no auth required.
Strong coverage of remote + Europe-friendly roles including community,
marketing, growth, and developer relations.

API docs: https://www.arbeitnow.com/api/job-board-api
Endpoint: GET https://www.arbeitnow.com/api/job-board-api
  - Returns JSON: { data: [...], links: {...}, meta: {...} }
  - Paginated via `?page=N` (1-indexed), up to ~100 results per page.
  - Free, no rate limit stated; be polite with delays.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import get_settings
from .base import RawCollectedRecord, SourceRow, now_iso
from .http_utils import json_from_get

_API_BASE = "https://www.arbeitnow.com/api/job-board-api"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AtlasJobSearch/1.0; aggregator; +https://example.invalid)"
    ),
    "Accept": "application/json",
}

# Keyword sets for filtering — Arbeitnow has no server-side tag filter.
_ROLE_INCLUDE: frozenset[str] = frozenset(
    {
        "community",
        "marketing",
        "growth",
        "content",
        "social media",
        "seo",
        "customer success",
        "customer support",
        "devrel",
        "developer relations",
        "developer advocate",
        "developer evangelist",
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
    }
)


def _matches_role(title: str, tags: list[str]) -> bool:
    """Return True if this job looks like a target role."""
    combined = (title + " " + " ".join(tags)).lower()
    return any(kw in combined for kw in _ROLE_INCLUDE)


def _parse_date(raw: Any) -> datetime | None:
    """Parse arbeitnow `created_at` — epoch int or ISO string."""
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw[:26], fmt[:len(raw[:26])])
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            except ValueError:
                continue
    return None


def collect_arbeitnow(
    row: SourceRow,
) -> tuple[list[RawCollectedRecord], str]:
    """Sync entry called from ``web3_ats._collect_one_source``.

    ``row.notes`` may contain comma-separated keyword overrides for the role
    filter. Pagination is bounded by ``arbeitnow_max_jobs`` setting.
    """
    s = get_settings()
    max_jobs: int = max(1, int(getattr(s, "arbeitnow_max_jobs", 200)))
    max_age_days: int = max(1, int(getattr(s, "arbeitnow_max_age_days", 14)))
    page_gap: float = max(0.0, float(getattr(s, "arbeitnow_page_gap_seconds", 0.5)))

    # Optional per-row keyword override via notes field
    if row.notes and row.notes.strip():
        role_filter: frozenset[str] = frozenset(
            kw.strip().lower() for kw in row.notes.split(",") if kw.strip()
        )
    else:
        role_filter = _ROLE_INCLUDE

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    records: list[RawCollectedRecord] = []
    page = 1

    while len(records) < max_jobs:
        url = f"{_API_BASE}?page={page}"
        data, err = json_from_get(url, headers=_HEADERS)
        if err:
            if page == 1:
                return [], f"arbeitnow_fetch_error:{err}"
            break  # partial results — return what we have
        if not isinstance(data, dict):
            break
        jobs = data.get("data")
        if not isinstance(jobs, list) or not jobs:
            break

        for job in jobs:
            if not isinstance(job, dict):
                continue
            title = str(job.get("title") or "").strip()
            if not title:
                continue

            # Age filter
            posted = _parse_date(job.get("created_at"))
            if posted and posted < cutoff:
                continue  # paginated newest-first — could break here, but be safe

            # Tag + title role filter
            raw_tags = job.get("tags") or []
            tags = [str(t).lower().strip() for t in raw_tags if t]
            combined = (title + " " + " ".join(tags)).lower()
            if not any(kw in combined for kw in role_filter):
                continue

            company = str(job.get("company_name") or "").strip()
            slug = str(job.get("slug") or "").strip()
            job_url = str(job.get("url") or "").strip()
            if not job_url and slug:
                job_url = f"https://www.arbeitnow.com/jobs/{slug}"

            remote_hint: bool | None = job.get("remote")
            location = str(job.get("location") or "").strip()
            description = str(job.get("description") or "")[:50_000]

            salary_parts: list[str] = []
            if job.get("salary_from"):
                salary_parts.append(str(job["salary_from"]))
            if job.get("salary_to"):
                salary_parts.append(str(job["salary_to"]))
            salary_text = " – ".join(salary_parts)
            if job.get("currency") and salary_parts:
                salary_text = f"{salary_text} {job['currency']}"

            payload: dict[str, Any] = {
                "company_name": company,
                "job_title": title,
                "job_url": job_url,
                "apply_url": job_url,
                "location": location,
                "description_clean": description,
                "employment_type": str(job.get("job_types") or "").strip(),
                "salary_text": salary_text,
                "external_job_id": slug,
                "source_type": "arbeitnow_agg",
                "remote_hint": remote_hint,
                "arbeitnow_tags": tags,
                "arbeitnow_created_at": job.get("created_at"),
                "collected_at": now_iso(),
                "collection_method": "arbeitnow_api",
            }

            records.append(
                RawCollectedRecord(
                    provider="arbeitnow",
                    source_url=job_url or url,
                    raw_payload=payload,
                )
            )
            if len(records) >= max_jobs:
                break

        # Check pagination — stop if no next page
        links = data.get("links") or {}
        if not links.get("next"):
            break

        page += 1
        if page_gap > 0:
            time.sleep(page_gap)

    return records, ("" if records else "arbeitnow_no_matching_jobs")
