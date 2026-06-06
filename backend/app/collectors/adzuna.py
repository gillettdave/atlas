"""Adzuna job aggregator collector.

Adzuna is a global job aggregator with strong UK/EU/AU coverage and decent
US presence. Their API is free up to 250 calls/day; paid tiers have no daily
cap and are priced per call (~$0.001).

Free tier is sufficient for personal use and small public release.
Upgrading is a config-only change — same API, no code changes needed.

Sign up at: https://developer.adzuna.com/
You get an app_id and app_key — set both in .env.

Upgrading
---------
Free → Paid: Email Adzuna to lift the 250/day cap. No code changes.
If Adzuna adds a higher-tier endpoint in future: update ATLAS_ADZUNA_API_BASE.

Geography
---------
Adzuna is country-specific. ``adzuna_countries`` in settings controls which
country APIs to query (default: us,gb). Use comma-separated ISO2 codes.
Available: us, gb, ca, au, de, fr, nl, sg, nz, at, be, br, in, it, mx, pl, ru, za
"""
from __future__ import annotations

import time
import random
from typing import Any

import requests

from ..config import get_settings
from .base import RawCollectedRecord, SourceRow, now_iso

_API_BASE_TMPL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

# Default queries — each uses Adzuna's `what` param (phrase/AND match).
# Adzuna `what_or` splits on spaces making it far too broad; `what` is correct.
_DEFAULT_QUERIES = [
    "community manager",
    "head of community",
    "developer relations",
    "community lead",
    "growth marketing",
    "developer advocate",
    "ecosystem growth",
    "community marketing",
    "devrel",
    "community growth",
]

# Title must contain at least one of these for the job to be included.
# Adzuna's `what` searches full text — a "community manager" query will
# also match "community health physician". Title filtering narrows to roles.
_TITLE_MUST_CONTAIN: frozenset[str] = frozenset({
    "community", "marketing", "growth", "brand", "content", "social media",
    "partnerships", "devrel", "developer relations", "developer advocate",
    "developer evangelist", "ecosystem", "engagement", "advocacy",
    "communications", "comms", "go-to-market", "gtm",
})


def _build_params(
    app_id: str,
    app_key: str,
    query: str,
    page: int,
    results_per_page: int,
    *,
    where: str = "",
    category: str = "",
    max_days_old: int = 14,
    full_time: bool = True,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": results_per_page,
        "what": query,          # phrase/AND — far more precise than what_or
        "sort_by": "date",
        "max_days_old": max_days_old,
        "content-type": "application/json",
    }
    if where:
        params["where"] = where
    if category:
        params["category"] = category
    if full_time:
        params["full_time"] = "1"
    return params


def collect_adzuna(
    row: SourceRow,
) -> tuple[list[RawCollectedRecord], str]:
    """Collect jobs via the Adzuna API.

    ``row.notes`` may contain pipe-separated search query overrides.
    ``row.ats_board_url`` is unused — Adzuna is query-based.
    """
    s = get_settings()
    app_id: str | None = getattr(s, "adzuna_app_id", None)
    app_key: str | None = getattr(s, "adzuna_app_key", None)
    if not app_id or not app_key:
        return [], "adzuna_no_credentials"

    max_jobs: int = max(1, int(getattr(s, "adzuna_max_jobs", 200)))
    max_pages: int = max(1, int(getattr(s, "adzuna_max_pages", 3)))
    page_gap: float = max(0.0, float(getattr(s, "adzuna_page_gap_seconds", 0.6)))
    results_per_page: int = min(50, max(1, int(getattr(s, "adzuna_results_per_page", 50))))
    max_days_old: int = max(1, int(getattr(s, "adzuna_max_days_old", 14)))
    countries_raw: str = getattr(s, "adzuna_countries", "us")
    countries = [c.strip().lower() for c in countries_raw.split(",") if c.strip()]

    # Query list: row.notes overrides → settings → default query list
    if row.notes and row.notes.strip():
        queries = [q.strip() for q in row.notes.split("|") if q.strip()]
    elif getattr(s, "adzuna_query", None):
        queries = [q.strip() for q in s.adzuna_query.split("|") if q.strip()]
    else:
        queries = _DEFAULT_QUERIES

    records: list[RawCollectedRecord] = []
    seen_ids: set[str] = set()

    for country in countries:
        for query in queries:
            if len(records) >= max_jobs:
                break

            for page in range(1, max_pages + 1):
                if len(records) >= max_jobs:
                    break
                if page > 1:
                    time.sleep(page_gap + random.uniform(0, 0.4))

                url = _API_BASE_TMPL.format(country=country, page=page)
                params = _build_params(
                    app_id, app_key, query, page, results_per_page,
                    max_days_old=max_days_old,
                )

                try:
                    resp = requests.get(url, params=params, timeout=(12, 30))
                except requests.RequestException as exc:
                    return records, f"adzuna_request_error:{type(exc).__name__}"

                if resp.status_code == 401:
                    return records, "adzuna_invalid_credentials"
                if resp.status_code == 429:
                    return records, "adzuna_rate_limited" if not records else ""
                if not resp.ok:
                    return records, f"adzuna_http_{resp.status_code}" if not records else ""

                try:
                    data = resp.json()
                except ValueError:
                    break

                jobs = data.get("results") or []
                if not jobs:
                    break  # No more results

                for job in jobs:
                    if not isinstance(job, dict):
                        continue

                    job_id = str(job.get("id") or "").strip()
                    if job_id and job_id in seen_ids:
                        continue
                    if job_id:
                        seen_ids.add(job_id)

                    title = str(job.get("title") or "").strip()
                    company_node = job.get("company") or {}
                    company = str(company_node.get("display_name") or "").strip() if isinstance(company_node, dict) else str(company_node).strip()
                    if not title or not company:
                        continue

                    # Title relevance filter — Adzuna's `what` searches full
                    # text so off-target roles (e.g. healthcare) slip through.
                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in _TITLE_MUST_CONTAIN):
                        continue

                    redirect_url = str(job.get("redirect_url") or "").strip()
                    job_url = redirect_url

                    location_node = job.get("location") or {}
                    if isinstance(location_node, dict):
                        area = location_node.get("area") or []
                        location = ", ".join(str(a) for a in area if a) if area else str(location_node.get("display_name") or "")
                    else:
                        location = str(location_node).strip()

                    # Salary
                    sal_min = job.get("salary_min")
                    sal_max = job.get("salary_max")
                    if sal_min or sal_max:
                        parts = []
                        if sal_min:
                            parts.append(f"{sal_min:,.0f}" if isinstance(sal_min, (int, float)) else str(sal_min))
                        if sal_max:
                            parts.append(f"{sal_max:,.0f}" if isinstance(sal_max, (int, float)) else str(sal_max))
                        salary_text = " – ".join(parts)
                    else:
                        salary_text = ""

                    description = str(job.get("description") or "")[:50_000]
                    category_node = job.get("category") or {}
                    category_label = str(category_node.get("label") or "") if isinstance(category_node, dict) else ""

                    records.append(RawCollectedRecord(
                        provider="adzuna",
                        source_url=job_url or url,
                        raw_payload={
                            "company_name": company,
                            "job_title": title,
                            "job_url": job_url,
                            "apply_url": job_url,
                            "location": location.strip(),
                            "description_clean": description,
                            "employment_type": str(job.get("contract_type") or ""),
                            "salary_text": salary_text,
                            "external_job_id": job_id,
                            "source_type": "adzuna_agg",
                            "adzuna_country": country,
                            "adzuna_category": category_label,
                            "adzuna_query": query,
                            "date_posted": str(job.get("created") or ""),
                            "collected_at": now_iso(),
                            "collection_method": "adzuna_api",
                        },
                    ))

                    if len(records) >= max_jobs:
                        break

            time.sleep(random.uniform(0.2, 0.5))

    return records, ("" if records else "adzuna_no_results")
