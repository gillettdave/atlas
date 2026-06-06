"""RemoteOK aggregator collector.

Fetches the public RemoteOK JSON API (no auth required). Filters jobs by
configurable tags and max age. Returns ``RawCollectedRecord`` instances in
the same shape as other Atlas collectors so the standard importer pipeline
parses them without provider-specific logic.

Reference: https://remoteok.com/api  (returns a JSON array; first element is
a legal/metadata object — skip it).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import get_settings
from .base import RawCollectedRecord, SourceRow, now_iso
from .http_utils import json_from_get

_API_URL = "https://remoteok.com/api"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AtlasJobSearch/1.0; aggregator; +https://example.invalid)"
    ),
    "Accept": "application/json",
}

# Tags that indicate community, marketing, growth, and adjacent remote roles.
_DEFAULT_TAGS: frozenset[str] = frozenset(
    {
        "community",
        "marketing",
        "growth",
        "content",
        "social-media",
        "seo",
        "customer-success",
        "customer-support",
        "operations",
        "product-management",
        "partnerships",
        "devrel",
        "developer-relations",
        "communications",
        "brand",
        "pr",
    }
)


def _parse_date(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[:25], fmt[:len(raw[:25])])
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError:
            continue
    return None


def _job_tags(row: dict[str, Any]) -> set[str]:
    raw = row.get("tags") or []
    if isinstance(raw, list):
        return {str(t).lower().strip() for t in raw}
    return set()


def collect_remoteok(
    row: SourceRow,
) -> tuple[list[RawCollectedRecord], str]:
    """Sync entry called from ``web3_ats._collect_one_source``.

    ``row.ats_board_url`` may be set to a custom API URL; falls back to the
    public endpoint. ``row.notes`` may contain comma-separated tag overrides.
    """
    s = get_settings()
    api_url = (row.ats_board_url or _API_URL).strip()
    max_age_days: int = max(1, int(s.remoteok_max_age_days))
    max_jobs: int = max(1, int(s.remoteok_max_jobs))

    # Tag filter: use profile-level override from row.notes if provided, else
    # fall back to settings, then built-in defaults.
    if row.notes and row.notes.strip():
        allowed_tags: frozenset[str] = frozenset(
            t.strip().lower() for t in row.notes.split(",") if t.strip()
        )
    elif s.remoteok_tags:
        allowed_tags = frozenset(
            t.strip().lower() for t in s.remoteok_tags.split(",") if t.strip()
        )
    else:
        allowed_tags = _DEFAULT_TAGS

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    data, err = json_from_get(api_url, headers=_HEADERS)
    if err:
        return [], f"remoteok_fetch_error:{err}"
    if not isinstance(data, list):
        return [], "remoteok_unexpected_format"

    records: list[RawCollectedRecord] = []

    for item in data:
        if not isinstance(item, dict):
            continue
        # Skip the first metadata element (has no "id" job field)
        if "id" not in item or not item.get("company"):
            continue

        # Age filter
        posted = _parse_date(item.get("date"))
        if posted and posted < cutoff:
            continue

        # Tag filter — accept if ANY tag overlaps allowed set
        tags = _job_tags(item)
        if allowed_tags and not (tags & allowed_tags):
            continue

        company = str(item.get("company") or "").strip()
        title = str(item.get("position") or item.get("title") or "").strip()
        if not company or not title:
            continue

        job_url = str(item.get("url") or item.get("apply_url") or "").strip()
        apply_url = str(item.get("apply_url") or job_url).strip()

        salary_parts = []
        if item.get("salary_min"):
            salary_parts.append(f"${item['salary_min']:,}")
        if item.get("salary_max"):
            salary_parts.append(f"${item['salary_max']:,}")
        salary_text = " – ".join(salary_parts) if salary_parts else ""

        payload: dict[str, Any] = {
            "company_name": company,
            "job_title": title,
            "job_url": apply_url or job_url,
            "apply_url": apply_url,
            "location": str(item.get("location") or "Worldwide").strip(),
            "description_clean": str(item.get("description") or "")[:50_000],
            "employment_type": "",
            "salary_text": salary_text,
            "external_job_id": str(item.get("id") or ""),
            "source_type": "remoteok_agg",
            "collected_at": now_iso(),
            "collection_method": "remoteok_api",
            "remoteok_tags": list(tags),
            "remoteok_date": item.get("date"),
        }

        records.append(
            RawCollectedRecord(
                provider="remoteok",
                source_url=job_url or api_url,
                raw_payload=payload,
            )
        )

        if len(records) >= max_jobs:
            break

    return records, ("" if records else "remoteok_no_matching_jobs")
