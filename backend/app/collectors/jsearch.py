"""JSearch aggregator collector (RapidAPI).

JSearch aggregates Indeed, Glassdoor, LinkedIn, ZipRecruiter and others into
a single search API. It is the single best source for Indeed jobs, which are
otherwise impossible to scrape directly.

Free tier: 200 requests/month (plenty for personal use)
Basic:     3,000 requests/month  (~$10/mo)
Pro:       30,000 requests/month (~$50/mo)

Upgrading is a single env-var change — same API, same endpoint, same parser.
The ``jsearch_monthly_request_budget`` setting lets you cap usage to stay on
a given tier without accidentally burning credits.

Sign up at: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
Then set ATLAS_JSEARCH_API_KEY in .env.
"""
from __future__ import annotations

import time
import random
from typing import Any

import requests

from ..config import get_settings
from .base import RawCollectedRecord, SourceRow, now_iso

import logging
log = logging.getLogger("atlas.collectors.jsearch")

_API_BASE = "https://jsearch.p.rapidapi.com/search"
_HEADERS_TMPL = {
    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    "Accept": "application/json",
}

# Searches that focus on community/marketing/growth roles posted remotely.
# Each query uses one API request; results are 10 jobs by default (up to 100).
DEFAULT_QUERIES = [
    "community manager remote",
    "head of community remote",
    "developer relations remote",
    "growth marketing remote",
    "community growth remote",
    "ecosystem growth remote",
    "marketing manager remote web3",
    "community lead remote",
    "customer success remote",
    "social media manager remote",
]


def _parse_date_posted(raw: str | None) -> str:
    """Normalise JSearch date_posted → ISO-ish string."""
    if not raw:
        return ""
    # JSearch returns strings like "3 days ago", "today", "2024-03-15"
    return str(raw).strip()


def collect_jsearch(
    row: SourceRow,
) -> tuple[list[RawCollectedRecord], str]:
    """Collect jobs via JSearch (RapidAPI).

    ``row.notes`` may contain comma-separated search query overrides.
    ``row.ats_board_url`` is unused — JSearch is query-based, not board-based.
    """
    s = get_settings()
    api_key: str | None = getattr(s, "jsearch_api_key", None)
    if not api_key:
        return [], "jsearch_no_api_key"

    max_jobs: int = max(1, int(getattr(s, "jsearch_max_jobs", 200)))
    max_pages: int = max(1, int(getattr(s, "jsearch_max_pages", 2)))
    page_gap: float = max(0.0, float(getattr(s, "jsearch_page_gap_seconds", 0.8)))
    employment_types: str = getattr(s, "jsearch_employment_types", "FULLTIME,CONTRACTOR")
    date_posted: str = getattr(s, "jsearch_date_posted", "week")  # today|3days|week|month

    # Query list: row.notes overrides, else settings override, else defaults
    if row.notes and row.notes.strip():
        queries = [q.strip() for q in row.notes.split("|") if q.strip()]
    elif getattr(s, "jsearch_queries", None):
        queries = [q.strip() for q in s.jsearch_queries.split("|") if q.strip()]
    else:
        queries = DEFAULT_QUERIES

    headers = {
        **_HEADERS_TMPL,
        "X-RapidAPI-Key": api_key,
    }

    records: list[RawCollectedRecord] = []
    seen_ids: set[str] = set()

    for query in queries:
        if len(records) >= max_jobs:
            break

        for page in range(1, max_pages + 1):
            if len(records) >= max_jobs:
                break
            if page > 1:
                time.sleep(page_gap + random.uniform(0, 0.5))

            params: dict[str, Any] = {
                "query": query,
                "page": page,
                "num_pages": 1,
                "employment_types": employment_types,
                "date_posted": date_posted,
                "remote_jobs_only": "true",
            }

            try:
                resp = requests.get(_API_BASE, headers=headers, params=params, timeout=(12, 30))
            except requests.RequestException as exc:
                return records, f"jsearch_request_error:{type(exc).__name__}"

            if resp.status_code == 429:
                log.warning("[jsearch] 429 rate limited — body: %s", resp.text[:500])
                return records, "jsearch_rate_limited" if not records else ""
            if resp.status_code == 403:
                log.warning("[jsearch] 403 forbidden — body: %s", resp.text[:500])
                return records, "jsearch_invalid_api_key"
            if not resp.ok:
                log.warning("[jsearch] HTTP %s — body: %s", resp.status_code, resp.text[:500])
                return records, f"jsearch_http_{resp.status_code}" if not records else ""

            try:
                data = resp.json()
            except ValueError:
                break

            jobs = data.get("data") or []
            if not jobs:
                break  # No more results for this query

            for job in jobs:
                if not isinstance(job, dict):
                    continue

                job_id = str(job.get("job_id") or "").strip()
                if job_id and job_id in seen_ids:
                    continue
                if job_id:
                    seen_ids.add(job_id)

                title = str(job.get("job_title") or "").strip()
                company = str(job.get("employer_name") or "").strip()
                if not title or not company:
                    continue

                apply_url = str(job.get("job_apply_link") or "").strip()
                job_url = str(job.get("job_job_link") or apply_url).strip()

                # Location
                city = str(job.get("job_city") or "").strip()
                state = str(job.get("job_state") or "").strip()
                country = str(job.get("job_country") or "").strip()
                location_parts = [p for p in [city, state, country] if p]
                location = ", ".join(location_parts) if location_parts else "Remote"

                # Salary
                sal_min = job.get("job_min_salary")
                sal_max = job.get("job_max_salary")
                sal_currency = str(job.get("job_salary_currency") or "USD")
                sal_period = str(job.get("job_salary_period") or "").lower()
                if sal_min or sal_max:
                    parts = []
                    if sal_min:
                        parts.append(f"{sal_currency} {sal_min:,.0f}" if isinstance(sal_min, (int, float)) else str(sal_min))
                    if sal_max:
                        parts.append(f"{sal_currency} {sal_max:,.0f}" if isinstance(sal_max, (int, float)) else str(sal_max))
                    salary_text = " – ".join(parts)
                    if sal_period:
                        salary_text += f" / {sal_period}"
                else:
                    salary_text = ""

                description = str(job.get("job_description") or "")[:50_000]

                records.append(RawCollectedRecord(
                    provider="jsearch",
                    source_url=job_url or apply_url or _API_BASE,
                    raw_payload={
                        "company_name": company,
                        "job_title": title,
                        "job_url": job_url,
                        "apply_url": apply_url,
                        "location": location,
                        "description_clean": description,
                        "employment_type": str(job.get("job_employment_type") or ""),
                        "salary_text": salary_text,
                        "external_job_id": job_id,
                        "source_type": "jsearch_agg",
                        "remote_hint": job.get("job_is_remote"),
                        "jsearch_publisher": str(job.get("job_publisher") or ""),
                        "jsearch_query": query,
                        "date_posted": _parse_date_posted(job.get("job_posted_at_datetime_utc") or job.get("job_posted_at_timestamp")),
                        "collected_at": now_iso(),
                        "collection_method": "jsearch_api",
                    },
                ))

                if len(records) >= max_jobs:
                    break

        # Polite gap between queries
        time.sleep(random.uniform(0.3, 0.8))

    return records, ("" if records else "jsearch_no_results")
