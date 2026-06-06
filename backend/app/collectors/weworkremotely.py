"""We Work Remotely RSS collector.

Fetches one or more WWR category RSS feeds and returns ``RawCollectedRecord``
instances. No auth required. Categories are configured via settings.

RSS feed URLs follow the pattern:
  https://weworkremotely.com/categories/remote-{category}-jobs.rss

Supported categories (as of 2025):
  marketing  customer-support  management-and-finance  design  devops-sysadmin
  programming  all-other  full-stack  frontend  backend  data-science
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from ..config import get_settings
from .base import RawCollectedRecord, SourceRow, now_iso
from .http_utils import http_get

_BASE_RSS = "https://weworkremotely.com/categories/remote-{category}-jobs.rss"
_ALL_JOBS_RSS = "https://weworkremotely.com/remote-jobs.rss"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AtlasJobSearch/1.0; aggregator; +https://example.invalid)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Default categories for a community/marketing/growth job hunt.
_DEFAULT_CATEGORIES: list[str] = [
    "marketing",
    "customer-support",
    "management-and-finance",
    "all-other",
]


def _rss_url(category: str) -> str:
    if category == "all":
        return _ALL_JOBS_RSS
    return _BASE_RSS.format(category=category.strip().lower())


def _parse_pub_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw.strip())
    except Exception:  # noqa: BLE001
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(raw.strip()[:31], fmt)
        except ValueError:
            continue
    return None


def _split_wwr_title(raw_title: str) -> tuple[str, str]:
    """WWR titles are often 'Company: Job Title' — split on the first colon."""
    if ":" in raw_title:
        company, _, title = raw_title.partition(":")
        return company.strip(), title.strip()
    return "", raw_title.strip()


def _parse_feed(
    xml_text: str,
    feed_url: str,
    cutoff: datetime,
    max_per_feed: int,
) -> list[RawCollectedRecord]:
    """Parse a single WWR RSS feed into RawCollectedRecord list."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    channel = root.find("channel")
    if channel is None:
        channel = root

    records: list[RawCollectedRecord] = []

    for item in channel.findall("item"):
        if len(records) >= max_per_feed:
            break

        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_str = item.findtext("pubDate")
        description = (item.findtext("description") or "").strip()
        region = (item.findtext("region") or "Worldwide").strip()
        category_text = (item.findtext("category") or "").strip()

        # Age filter
        pub_date = _parse_pub_date(pub_date_str)
        if pub_date and pub_date < cutoff:
            continue

        company, title = _split_wwr_title(raw_title)
        if not title:
            continue

        # Build a deterministic external ID from the URL slug
        ext_id = link.rstrip("/").rsplit("/", 1)[-1] if link else ""

        payload: dict[str, Any] = {
            "company_name": company,
            "job_title": title,
            "job_url": link,
            "apply_url": link,
            "location": region,
            "description_clean": description[:50_000],
            "employment_type": "",
            "salary_text": "",
            "external_job_id": ext_id,
            "source_type": "weworkremotely_agg",
            "collected_at": now_iso(),
            "collection_method": "wwr_rss",
            "wwr_category": category_text,
            "wwr_pub_date": pub_date_str,
            "wwr_feed_url": feed_url,
        }

        records.append(
            RawCollectedRecord(
                provider="weworkremotely",
                source_url=link or feed_url,
                raw_payload=payload,
            )
        )

    return records


def collect_weworkremotely(
    row: SourceRow,
) -> tuple[list[RawCollectedRecord], str]:
    """Sync entry called from ``web3_ats._collect_one_source``.

    ``row.notes`` may carry comma-separated category overrides (e.g.
    ``marketing,customer-support``). Falls back to settings, then defaults.
    """
    s = get_settings()
    max_age_days = max(1, int(s.wwr_max_age_days))
    max_jobs = max(1, int(s.wwr_max_jobs))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    # Category list: row notes → settings → built-in defaults
    if row.notes and row.notes.strip():
        categories = [c.strip() for c in row.notes.split(",") if c.strip()]
    elif s.wwr_categories:
        categories = [c.strip() for c in s.wwr_categories.split(",") if c.strip()]
    else:
        categories = _DEFAULT_CATEGORIES

    per_feed_limit = max(1, max_jobs // max(1, len(categories)))
    all_records: list[RawCollectedRecord] = []

    for category in categories:
        if len(all_records) >= max_jobs:
            break

        feed_url = _rss_url(category)
        resp, err = http_get(feed_url, headers=_HEADERS)
        if err or resp is None or not resp.ok:
            continue

        xml_text = resp.text
        recs = _parse_feed(
            xml_text,
            feed_url=feed_url,
            cutoff=cutoff,
            max_per_feed=per_feed_limit,
        )
        all_records.extend(recs)

    return all_records, ("" if all_records else "wwr_no_records")
