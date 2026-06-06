"""Jobstash aggregator collector (Sprint M.3).

Jobstash aggregates Web3/crypto roles. Atlas marks sightings ``aggregator_jobstash``
when URLs reference ``jobstash.xyz`` (see ``services/importer._source_kind_for``).

**Public mode** — Crawls Jobstash shard sitemaps for two-segment job URLs, GETs each
listing page, and parses JobPosting schema.org JSON-LD (no Atlas Playwright dependency
for those rows). HTTP uses ``http_utils`` so ``ATLAS_HTTP_*`` retry/backoff applies.

**Middleware API mode (optional)** — If ``ATLAS_JOBSTASH_API_BASE`` points at Jobstash's
Nest ``/jobs/list`` backend, Atlas paginates HTTP JSON (page size **≤20**, backoff between
pages, ``publicationDate`` driven by ``ATLAS_JOBSTASH_PULL_PROFILE`` / optional override).

Base URL and partner bearer token vary by deployment; ops configure ``backend/.env``.
"""

from __future__ import annotations

import json
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from ..config import get_settings

from .base import RawCollectedRecord, SourceRow, now_iso
from .http_utils import http_get, json_from_get

_PUBLIC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AtlasRecruiter/1.2; collector; +https://example.invalid)"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Two-segment URLs (example: …/technical-account-manager-lifi/qus9Z8 ); excludes /t-tags.
_JOB_DETAIL_PATTERN = re.compile(
    r"^https://(?:www\.)?jobstash\.xyz/(?!jobs/)([^/?#]+)/([A-Za-z0-9]+)/?$",
)


def _parse_job_posting_date(ld: dict[str, Any]) -> datetime | None:
    """Best-effort ``datePosted`` from JSON-LD (date or datetime)."""
    raw = ld.get("datePosted") or ld.get("date_posted")
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    s = raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            d = datetime.strptime(raw[:10], "%Y-%m-%d").date()
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except ValueError:
        pass
    return None


def _include_listing_by_pull_profile(
    posted: datetime | None,
    profile: Literal["initial", "incremental"],
    *,
    initial_max_days: int,
    incremental_max_hours: float,
) -> bool:
    """Filter sitemap/JSON-LD rows by age (public mode; API mode uses publicationDate)."""
    now = datetime.now(timezone.utc)
    if posted is None:
        return profile == "initial"
    if profile == "initial":
        return (now - posted) <= timedelta(days=max(1, initial_max_days))
    return (now - posted) < timedelta(hours=max(1.0, incremental_max_hours))


def _effective_middleware_publication_date(
    pull_profile: Literal["initial", "incremental"],
    override: str | None,
) -> str | None:
    """Head-dev alignment: map profile to middleware enum; override wins if set."""
    o = (override or "").strip()
    if o:
        return o
    if pull_profile == "initial":
        return "past-2-weeks"
    # Middleware only supports "past-2-weeks"; "today" returns 400.
    # For incremental runs, omit the filter and rely on post-fetch age filtering.
    return None


def _parse_json_ld_job_posting(html: str) -> dict[str, Any] | None:
    m = re.search(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    try:
        blob = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    candidates = blob if isinstance(blob, list) else [blob]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        tp = item.get("@type")
        if tp == "JobPosting":
            return item
        if isinstance(tp, list) and "JobPosting" in tp:
            return item
        if tp is None and item.get("title") and (
            item.get("hiringOrganization") or item.get("description")
        ):
            continue
    return None


def _salary_ld(obj: dict[str, Any]) -> str | None:
    bs = obj.get("baseSalary")
    if not isinstance(bs, dict):
        return None
    val = bs.get("value")
    currency = str(bs.get("currency") or "")
    if isinstance(val, dict):
        lo = val.get("minValue")
        hi = val.get("maxValue")
        ut = str(val.get("unitText") or "")
        chunks: list[str] = []
        if lo is not None:
            chunks.append(str(lo))
        if hi is not None and hi != lo:
            chunks.append(str(hi))
        if chunks:
            return f"{currency} {'–'.join(chunks)} {ut}".strip()
    return None


def _http_timeouts(*, min_read: float | None = None) -> tuple[float, float]:
    s = get_settings()
    c = float(s.http_timeout_connect_seconds)
    r = float(s.http_timeout_read_seconds)
    if min_read is not None:
        r = max(r, float(min_read))
    return (c, r)


def discover_job_urls_from_public_sitemap(
    max_urls: int, *, max_shards: int
) -> tuple[list[str], str]:
    root_r, root_err = http_get(
        "https://jobstash.xyz/sitemap.xml",
        headers=_PUBLIC_HEADERS,
        timeout=_http_timeouts(min_read=45.0),
    )
    if root_r is None:
        return [], f"jobstash_sitemap_root_{root_err}"
    if not root_r.ok:
        return [], f"jobstash_sitemap_root_http_{root_r.status_code}"
    shard_urls: list[str] = []
    rt = ET.fromstring(root_r.content)
    for tag in rt.iter():
        if (tag.tag or "").endswith("loc") and tag.text:
            u = tag.text.strip()
            if u.endswith(".xml"):
                shard_urls.append(u)

    cap_shards = max(1, int(max_shards))
    job_urls: list[str] = []
    for shard in shard_urls[:cap_shards]:
        if len(job_urls) >= max_urls:
            break
        try:
            sr, _sr_err = http_get(
                shard,
                headers=_PUBLIC_HEADERS,
                timeout=_http_timeouts(min_read=90.0),
            )
            if sr is None or not sr.ok:
                continue
            for shard_tag in ET.fromstring(sr.content).iter():
                if not (shard_tag.tag or "").endswith("loc") or not shard_tag.text:
                    continue
                url = shard_tag.text.strip()
                m = _JOB_DETAIL_PATTERN.match(url)
                if not m:
                    continue
                slug = m.group(1)
                if slug.startswith("t-"):
                    continue
                job_urls.append(url)
                if len(job_urls) >= max_urls:
                    break
        except (OSError, ET.ParseError):
            continue

    return job_urls, ("" if job_urls else "jobstash_no_sitemap_jobs")


def _record_from_ld(
    *,
    ld: dict[str, Any],
    page_url: str,
    discovery_source_url: str,
    collection_method: str,
    native_item: dict[str, Any] | None,
    pull_profile: Literal["initial", "incremental"],
    publication_hint: str | None,
) -> RawCollectedRecord:
    ho = ld.get("hiringOrganization") or {}
    company = ""
    if isinstance(ho, dict):
        company = (ho.get("name") or "").strip()
    title = (ld.get("title") or "").strip()
    desc = (ld.get("description") or "").strip()
    loc_hint = ld.get("jobLocation") or ld.get("applicantLocationRequirements")
    location = ""
    if isinstance(loc_hint, dict):
        location = str(
            loc_hint.get("name")
            or (loc_hint.get("address") or {}).get("addressLocality")
            or "",
        ).strip()

    slug_match = _JOB_DETAIL_PATTERN.match(page_url)
    short_uuid = slug_match.group(2) if slug_match else ""

    posted = _parse_job_posting_date(ld)
    payload: dict[str, Any] = {
        "company_name": company,
        "job_title": title,
        "job_url": page_url.strip(),
        "location": location,
        "description_clean": desc,
        "employment_type": (ld.get("employmentType") or "") or "",
        "salary_text": _salary_ld(ld) or "",
        "external_job_id": short_uuid,
        "source_type": "jobstash_agg",
        "collected_at": now_iso(),
        "collection_method": collection_method,
        "jobstash_pull_profile": pull_profile,
        "jobstash_date_posted_utc": posted.isoformat(timespec="seconds") if posted else None,
        "jobstash_publication_filter": publication_hint,
    }
    if native_item is not None:
        payload["native_api_item"] = native_item

    return RawCollectedRecord(
        provider="jobstash",
        source_url=discovery_source_url or page_url,
        raw_payload=payload,
        fetch_status="fetched",
    )


def collect_public_sitemap(
    *,
    source_label_url: str,
    target_record_cap: int,
    discovery_url_cap: int,
    sitemap_max_shards: int,
    min_gap_seconds: float,
    pull_profile: Literal["initial", "incremental"],
    publication_hint: str | None,
    initial_max_days: int,
    incremental_max_hours: float,
) -> tuple[list[RawCollectedRecord], str]:
    urls, hint = discover_job_urls_from_public_sitemap(
        discovery_url_cap, max_shards=sitemap_max_shards
    )
    if not urls:
        return [], hint or "jobstash_empty_sitemap"

    records: list[RawCollectedRecord] = []
    list_to = _http_timeouts(min_read=35.0)
    for i, ju in enumerate(reversed(urls)):
        if len(records) >= target_record_cap:
            break
        if i > 0 and min_gap_seconds > 0:
            time.sleep(min_gap_seconds)
        try:
            pg, _pg_err = http_get(ju, headers=_PUBLIC_HEADERS, timeout=list_to)
            if pg is None or not pg.ok:
                continue
            ld = _parse_json_ld_job_posting(pg.text)
            if not ld:
                continue
            posted = _parse_job_posting_date(ld)
            if not _include_listing_by_pull_profile(
                posted,
                pull_profile,
                initial_max_days=initial_max_days,
                incremental_max_hours=incremental_max_hours,
            ):
                continue
            records.append(
                _record_from_ld(
                    ld=ld,
                    page_url=ju,
                    discovery_source_url=source_label_url,
                    collection_method="jobstash_sitemap_jsonld",
                    native_item=None,
                    pull_profile=pull_profile,
                    publication_hint=publication_hint,
                )
            )
            if len(records) >= target_record_cap:
                break
        except OSError:
            continue

    return records, ("" if records else "jobstash_jsonld_empty")


def _unwrap_job_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    d = body.get("data")
    if isinstance(d, dict) and isinstance(d.get("data"), list):
        return [x for x in d["data"] if isinstance(x, dict)]
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    return []


def _org_name(job: dict[str, Any]) -> str:
    org = job.get("organization")
    if isinstance(org, list) and org:
        org = org[0]
    if isinstance(org, dict):
        return (org.get("name") or "").strip()
    return ""


def _jobstash_public_url(job: dict[str, Any]) -> str | None:
    raw_url = job.get("url")
    if isinstance(raw_url, str) and raw_url.startswith("http"):
        return raw_url.strip()
    return None


def collect_middleware_api(
    *,
    api_base: str,
    bearer_token: str | None,
    publication_date_filter: str | None,
    page_size: int,
    max_pages: int,
    source_label_url: str,
    backoff_seconds: float,
    jitter_seconds: float,
    pull_profile: Literal["initial", "incremental"],
    publication_hint: str | None,
) -> tuple[list[RawCollectedRecord], str]:
    base = api_base.strip().rstrip("/")
    list_url = base + "/jobs/list"
    page_size = min(20, max(1, page_size))

    headers = dict(_PUBLIC_HEADERS)
    headers["Accept"] = "application/json"
    if bearer_token:
        t = bearer_token.strip()
        headers["Authorization"] = t if t.lower().startswith("bearer ") else f"Bearer {t}"

    records: list[RawCollectedRecord] = []
    page_n = 1

    while page_n <= max_pages:
        if page_n > 1:
            jitter = random.uniform(0.0, max(0.0, jitter_seconds))
            time.sleep(max(0.0, backoff_seconds) + jitter)
        params: dict[str, str] = {
            "page": str(page_n),
            "limit": str(page_size),
        }
        if publication_date_filter:
            params["publicationDate"] = publication_date_filter
        try:
            body, tag = json_from_get(
                list_url,
                headers=headers,
                params=params,
                timeout=_http_timeouts(min_read=120.0),
            )
            if body is None:
                if tag == "http_403":
                    return [], "jobstash_api_forbidden_check_token"
                if tag == "bad_json_body":
                    return [], "jobstash_api_invalid_json"
                if tag.startswith("http_"):
                    return [], f"jobstash_api_http_{tag.removeprefix('http_')}"
                return [], f"jobstash_api_network:{tag}"

            if not isinstance(body, dict):
                return [], "jobstash_api_invalid_json"

            if body.get("success") is False:
                msg = body.get("message") or body.get("error") or "api_error"
                return [], f"jobstash_api_error:{str(msg)[:200]}"

            rows = _unwrap_job_rows(body)
            if not rows:
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue
                jp = _jobstash_public_url(row)
                if not jp:
                    continue
                title = (row.get("title") or "").strip()
                org = _org_name(row)
                desc = str(
                    row.get("description")
                    or row.get("summary")
                    or row.get("requirements")
                    or "",
                )
                loc = str(row.get("location") or "")
                ext = str(
                    row.get("shortUUID")
                    or row.get("short_uuid")
                    or row.get("id")
                    or "",
                )

                native = {k: v for k, v in row.items() if k in (
                    "title", "shortUUID", "url", "timestamp", "organization",
                )}

                payload: dict[str, Any] = {
                    "company_name": org,
                    "job_title": title,
                    "job_url": jp,
                    "location": loc,
                    "description_clean": desc[:200_000],
                    "employment_type": str(row.get("commitment") or ""),
                    "salary_text": str(row.get("salary") or ""),
                    "external_job_id": ext,
                    "source_type": "jobstash_agg",
                    "collected_at": now_iso(),
                    "collection_method": "jobstash_middleware_api",
                    "native_api_item": native,
                    "jobstash_pull_profile": pull_profile,
                    "jobstash_publication_filter": publication_hint,
                }
                records.append(
                    RawCollectedRecord(
                        provider="jobstash",
                        source_url=source_label_url,
                        raw_payload=payload,
                        fetch_status="fetched",
                    )
                )

            if len(rows) < page_size:
                break
            page_n += 1
        except OSError as e:
            return [], f"jobstash_api_network:{type(e).__name__}"

    return records, ("" if records else "jobstash_api_empty")


def collect_jobstash(row: SourceRow) -> tuple[list[RawCollectedRecord], str]:
    """Sync entry used from ``web3_ats._collect_one_source``."""

    s = get_settings()
    label = (row.ats_board_url or row.jobs_page or "https://jobstash.xyz/").strip()
    profile = s.jobstash_pull_profile
    pub = _effective_middleware_publication_date(profile, s.jobstash_api_publication_date)

    if s.jobstash_api_base and s.jobstash_api_base.strip():
        return collect_middleware_api(
            api_base=s.jobstash_api_base,
            bearer_token=s.jobstash_api_bearer_token,
            publication_date_filter=pub,
            page_size=min(20, max(1, s.jobstash_api_page_size)),
            max_pages=max(1, s.jobstash_api_max_pages),
            source_label_url=label,
            backoff_seconds=s.jobstash_api_request_backoff_seconds,
            jitter_seconds=s.jobstash_api_request_jitter_seconds,
            pull_profile=profile,
            publication_hint=pub,
        )

    return collect_public_sitemap(
        source_label_url=label,
        target_record_cap=max(1, s.jobstash_sitemap_max_jobs),
        discovery_url_cap=max(50, s.jobstash_sitemap_discovery_max_urls),
        sitemap_max_shards=max(1, s.jobstash_sitemap_max_shards),
        min_gap_seconds=max(0.0, s.jobstash_sitemap_request_gap_seconds),
        pull_profile=profile,
        publication_hint=pub,
        initial_max_days=max(1, s.jobstash_initial_max_age_days),
        incremental_max_hours=float(s.jobstash_incremental_max_age_hours),
    )
