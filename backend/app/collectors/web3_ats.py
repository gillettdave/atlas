"""Web3 ATS collector.

Refactored from jobs_collector_v4.py. Differences:
- No business dedupe. Cleaner v2 is the sole authority on duplicates.
- No CSV output. Emits RawCollectedRecord instances.
- No filesystem side effects.
- Yields in streaming fashion so the runner can submit in batches.

Sprint M.2: Ashby uses the official posting HTTP API before Playwright.
SmartRecruiters is collected via GET /v1/companies/{id}/postings (no API key).

Sprint M.3: ``ats_type=jobstash`` is handled via ``collectors/jobstash.py``
(public sitemap + JSON-LD, or optional Middleware API when configured).

Sprint M.4: Shared ``http_utils`` retries 429/transient HTTP; Workable uses the
public widget JSON feed when inferable from the board URL + optional ``ats_slug``;
Teamtailor uses ``/jobs.rss`` before Playwright fallback.

Parse hygiene is kept (skip obvious nav links, filter single-word titles
that aren't role words) because these are fetch/parse discipline, not
dedupe — they prevent pollution of raw_job_events with plainly non-job
anchor tags like "Apply Now" or "Learn More".
"""
from __future__ import annotations

import csv
import random
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from ..config import get_settings
from .base import CollectionStats, RawCollectedRecord, SourceRow, now_iso
from .http_utils import http_get, json_from_get
from .adzuna import collect_adzuna
from .arbeitnow import collect_arbeitnow
from .himalayas import collect_himalayas
from .jobicy import collect_jobicy
from .themuse import collect_themuse
from .jobstash import collect_jobstash
from .jsearch import collect_jsearch
from .remoteok import collect_remoteok
from .weworkremotely import collect_weworkremotely
from .workday import collect_workday  # async, uses Playwright browser


BLACKLIST_URLS = {"https://cryptojobslist.com/internship"}
BAD_JOB_TITLES = {
    "apply now", "apply", "learn more", "view role", "view job", "read more",
    "clear", "see all opportunities", "how we hire", "work with us",
    "grow with us",
}
BAD_TITLE_CONTAINS = [
    "feedback", "internal communication", "how we hire",
    "work with us", "grow with us", "see all opportunities",
]
ROLE_WORDS = [
    "engineer", "manager", "designer", "analyst", "lead", "director",
    "developer", "specialist", "intern", "marketing", "sales", "product",
    "operations", "counsel", "associate", "scientist", "recruiter",
    "trader", "writer", "editor", "growth", "legal", "finance",
    "accountant", "compliance", "security", "researcher", "architect",
    "consultant", "strategist", "partner", "coordinator", "officer",
    "administrator",
]
BINANCE_OVERRIDE = "https://www.binance.com/en/careers/job-openings?team=All"

_PUBLIC_UA_HEADERS = {
    # Some ATS CDNs omit responses for empty/generic agents; Atlas is explicit.
    "User-Agent": "Mozilla/5.0 (compatible; AtlasRecruiter/1.1; +https://example.invalid)",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# Description helpers
# ---------------------------------------------------------------------------

_DESC_MAX_CHARS = 8_000  # truncate beyond this — full JDs rarely need more


def _html_to_text(html: str) -> str:
    """Strip HTML tags and normalise whitespace to plain text.

    Handles both raw HTML and HTML-entity-encoded strings (Greenhouse returns
    the latter — &lt;p&gt; instead of <p>).
    """
    import html as html_lib
    if not html:
        return ""
    # Unescape entities first so BeautifulSoup sees real tags
    unescaped = html_lib.unescape(html)
    soup = BeautifulSoup(unescaped, "lxml")
    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines to at most one
    lines = [l.strip() for l in text.splitlines()]
    cleaned = "\n".join(l for l in lines if l)
    return cleaned[:_DESC_MAX_CHARS]


def _fetch_greenhouse_description(slug: str, job_id: str) -> Optional[str]:
    """Fetch full job description from Greenhouse detail endpoint.

    Returns plain text or None on failure.
    Rate-limit: callers should sleep between calls.
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
    data, tag = json_from_get(url, headers=_PUBLIC_UA_HEADERS)
    if not isinstance(data, dict):
        return None
    content = data.get("content") or ""
    if content:
        return _html_to_text(content)
    return None


# ---------------------------------------------------------------------------
# Parse hygiene
# ---------------------------------------------------------------------------

def _bad_title(title: str) -> bool:
    low = (title or "").strip().lower()
    if not low:
        return True
    if low in BAD_JOB_TITLES:
        return True
    if any(x in low for x in BAD_TITLE_CONTAINS):
        return True
    words = low.split()
    if len(words) == 1 and low not in ROLE_WORDS:
        return True
    return False


def _joblike_title(title: str) -> bool:
    low = (title or "").strip().lower()
    if _bad_title(low):
        return False
    return any(w in low for w in ROLE_WORDS)


def _light_normalize_url(url: str) -> str:
    """Very light URL normalization at the collector layer.

    Only enough to avoid emitting obviously-junk URLs (empty, no host).
    The full canonicalization (stripping tracking params etc.) happens
    in services/url_canonicalize.py during the cleaner stage.
    """
    url = (url or "").strip()
    if not url:
        return ""
    p = urlparse(url if "://" in url else "https://" + url)
    if not p.netloc or p.netloc == ".":
        return ""
    return url if "://" in url else "https://" + url


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def load_sources(path: Path, limit: Optional[int] = None) -> list[SourceRow]:
    rows: list[SourceRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(SourceRow(
                company_name=(row.get("company_name") or "").strip(),
                source=(row.get("source") or "").strip(),
                profile_url=(row.get("profile_url") or "").strip(),
                official_site=(row.get("official_site") or "").strip(),
                jobs_page=(row.get("jobs_page") or "").strip(),
                ats_type=(row.get("ats_type") or "").strip(),
                ats_board_url=(row.get("ats_board_url") or "").strip(),
                ats_slug=(row.get("ats_slug") or "").strip(),
                cryptojobslist_fallback_jobs_page=(row.get("cryptojobslist_fallback_jobs_page") or "").strip(),
                resolution_type=(row.get("resolution_type") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            ))
    return rows[:limit] if limit is not None else rows


# ---------------------------------------------------------------------------
# Link extraction helper (for rendered pages)
# ---------------------------------------------------------------------------

def _extract_links_with_text(html_text: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html_text, "lxml")
    out: list[tuple[str, str]] = []
    p = urlparse(base_url)
    origin = f"{p.scheme}://{p.netloc}"
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        if href.startswith("/"):
            href = origin + href
        href = _light_normalize_url(href)
        text = a.get_text(" ", strip=True)
        if href and href not in BLACKLIST_URLS:
            out.append((href, text))
    return out


def _nearest_heading_title(a_tag) -> str:
    node = a_tag
    for _ in range(4):
        if node is None:
            break
        for sel in ["h1", "h2", "h3", "h4", "strong", "b"]:
            found = node.find(sel)
            if found:
                t = found.get_text(" ", strip=True)
                if t and not _bad_title(t):
                    return t
        node = node.parent
    return ""


# ---------------------------------------------------------------------------
# Native API collectors (no browser required)
# ---------------------------------------------------------------------------

def collect_lever(board_url: str, company_name: str, source_url: str) -> tuple[list[RawCollectedRecord], str]:
    slug = board_url.rstrip("/").split("/")[-1]
    api_u = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data_e, tag = json_from_get(api_u, headers=_PUBLIC_UA_HEADERS)
    data = data_e if isinstance(data_e, list) else None
    if data is None:
        suffix = tag or "lever_api_empty_json"
        return [], f"lever_api:{suffix}"

    records: list[RawCollectedRecord] = []
    for item in data:
        title = (item.get("text") or "").strip()
        if _bad_title(title):
            continue
        categories = item.get("categories") or {}
        records.append(RawCollectedRecord(
            provider="lever",
            source_url=source_url or board_url,
            raw_payload={
                "company_name": company_name,
                "source_type": "ats_board",
                "ats_type": "lever",
                "job_title": title,
                "job_url": (item.get("hostedUrl") or "").strip(),
                "apply_url": (item.get("applyUrl") or "").strip(),
                "external_job_id": item.get("id"),
                "location": (categories.get("location") or "").strip(),
                "department": (categories.get("team") or "").strip(),
                "commitment": (categories.get("commitment") or "").strip(),
                "description": item.get("descriptionPlain") or _html_to_text(item.get("descriptionHtml") or "") or item.get("description") or None,
                "collected_at": now_iso(),
                "native_api_item": item,
            },
        ))
    return records, ""


def collect_greenhouse(board_url: str, company_name: str, source_url: str) -> tuple[list[RawCollectedRecord], str]:
    p = urlparse(board_url)
    host = p.netloc.lower()
    parts = [x for x in p.path.strip("/").split("/") if x]
    qs = parse_qs(p.query)

    slug = ""
    if "for" in qs and qs["for"]:
        slug = qs["for"][0]
    elif host == "job-boards.greenhouse.io" and len(parts) >= 1 and parts[0] != "jobs":
        slug = parts[0]
    elif host == "boards.greenhouse.io" and len(parts) >= 1:
        slug = parts[0]

    records: list[RawCollectedRecord] = []
    if slug:
        data_o, gh_tag = json_from_get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            headers=_PUBLIC_UA_HEADERS,
        )
        data = data_o if isinstance(data_o, dict) else {}
        if gh_tag:
            return [], f"greenhouse_api:{gh_tag}"
        for item in data.get("jobs", []):
            title = (item.get("title") or "").strip()
            if _bad_title(title):
                continue
            loc = (item.get("location") or {})
            job_id = str(item.get("id")) if item.get("id") is not None else None
            # Fetch full description from detail endpoint (rate-limited)
            description: Optional[str] = None
            if slug and job_id:
                description = _fetch_greenhouse_description(slug, job_id)
                time.sleep(0.5)  # 2 req/s max to avoid bans
            records.append(RawCollectedRecord(
                provider="greenhouse",
                source_url=source_url or board_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "ats_board",
                    "ats_type": "greenhouse",
                    "job_title": title,
                    "job_url": (item.get("absolute_url") or "").strip(),
                    "external_job_id": job_id,
                    "location": (loc.get("name") or "").strip(),
                    "department": ", ".join(
                        d.get("name", "") for d in (item.get("departments") or [])
                    ).strip(", "),
                    "updated_at": item.get("updated_at"),
                    "collected_at": now_iso(),
                    "description": description,
                    "native_api_item": item,
                },
            ))
        return records, ""

    # No slug extractable — fall back to scraping the board page title.
    rsp, fr_tag = http_get(board_url, headers=_PUBLIC_UA_HEADERS)
    if rsp is None or not rsp.ok:
        return [], (f"greenhouse_scrape:{fr_tag}" if fr_tag else "greenhouse_scrape_failed")
    html = rsp.text
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
    if title and not _bad_title(title):
        records.append(RawCollectedRecord(
            provider="greenhouse",
            source_url=source_url or board_url,
            raw_payload={
                "company_name": company_name,
                "source_type": "ats_board",
                "ats_type": "greenhouse",
                "job_title": title,
                "job_url": board_url,
                "collected_at": now_iso(),
            },
        ))
    return records, ""


# ---------------------------------------------------------------------------
# Sprint M.2 — additional native ATS HTTP APIs (no Playwright)
# ---------------------------------------------------------------------------

def ashby_board_slug_from_url(board_url: str) -> Optional[str]:
    """`/company` segment from ``https://jobs.ashbyhq.com/{slug}``.

    Embedded boards like ``jobs.ashbyhq.com/embed/...`` are not resolved
    here; the rendered collector may still recover links.
    """
    u = _light_normalize_url(board_url)
    if not u:
        return None
    p = urlparse(u)
    if "ashbyhq.com" not in p.netloc.lower():
        return None
    parts = [x for x in p.path.strip("/").split("/") if x]
    if not parts:
        return None
    if parts[0] == "embed":
        qs = parse_qs(p.query)
        if qs.get("for"):
            return (qs["for"][0] or "").strip() or None
        return None
    return parts[0]


def collect_ashby_posting_api(
    board_url: str, company_name: str, source_url: str,
) -> tuple[list[RawCollectedRecord], bool]:
    """GET Ashby public posting JSON. Second return value: try Playwright fallback.

    See https://developers.ashbyhq.com/docs/public-job-posting-api
    """
    slug = ashby_board_slug_from_url(board_url)
    if not slug:
        return [], True
    api = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data_o, tag = json_from_get(api, headers=_PUBLIC_UA_HEADERS)
    data = data_o if isinstance(data_o, dict) else None
    if data is None:
        if tag and "http_404" in tag:
            return [], True
        return [], True
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if jobs is None:
        return [], True
    out: list[RawCollectedRecord] = []
    for job in jobs:
        if isinstance(job, dict) and job.get("isListed") is False:
            continue
        if not isinstance(job, dict):
            continue
        title = (job.get("title") or "").strip()
        if _bad_title(title):
            continue
        ju = (job.get("jobUrl") or "").strip()
        if not ju:
            continue
        dept = job.get("department")
        dept_s = dept if isinstance(dept, str) else str(dept or "")
        team_obj = job.get("team")
        team_s = team_obj if isinstance(team_obj, str) else ""
        emp = job.get("employmentType")
        emp_s = emp if isinstance(emp, str) else str(emp or "")
        out.append(RawCollectedRecord(
            provider="ashby",
            source_url=source_url or board_url,
            raw_payload={
                "company_name": company_name,
                "source_type": "ats_board",
                "ats_type": "ashby",
                "job_title": title,
                "job_url": ju,
                "apply_url": (job.get("applyUrl") or "").strip(),
                "location": (job.get("location") or "").strip(),
                "department": dept_s.strip(),
                "team": team_s.strip(),
                "employment_type": emp_s,
                "remote_hint": job.get("isRemote"),
                "workplace_type": job.get("workplaceType"),
                "description": job.get("descriptionPlain") or _html_to_text(job.get("descriptionHtml") or "") or None,
                "published_at": job.get("publishedAt"),
                "collected_at": now_iso(),
                "native_api_item": job,
                "collection_method": "ashby_posting_api",
            },
        ))
    return out, False


def _smartrecruiters_company_id(board_url: str, ats_slug: str = "") -> Optional[str]:
    if (ats_slug or "").strip():
        return ats_slug.strip()
    u = _light_normalize_url(board_url)
    if not u:
        return None
    p = urlparse(u)
    if "smartrecruiters.com" not in p.netloc.lower():
        return None
    parts = [x for x in p.path.strip("/").split("/") if x]
    if not parts:
        return None
    return parts[0]


def _smartrecruiters_slug_for_url(name: str) -> str:
    s = (name or "job").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "job"


def _smartrecruiters_public_job_url(company_id: str, row: dict) -> str:
    if row.get("postingUrl"):
        return str(row["postingUrl"]).strip()
    jid = row.get("id")
    nm = row.get("name") or ""
    slug = _smartrecruiters_slug_for_url(str(nm))
    return f"https://jobs.smartrecruiters.com/{company_id}/{jid}-{slug}"


def collect_smartrecruiters_api(
    board_url: str,
    company_name: str,
    source_url: str,
    *,
    ats_slug: str = "",
) -> tuple[list[RawCollectedRecord], str]:
    """GET SmartRecruiters public posting feed (pagination).

    Uses ``GET https://api.smartrecruiters.com/v1/companies/{companyId}/postings``

    Prefer ``ats_slug`` in the CSV when the career URL path is the canonical
    company identifier (example: ``McDonaldsCanada``).
    """
    cid = _smartrecruiters_company_id(board_url, ats_slug)
    if not cid:
        return [], "smartrecruiters_no_company_id"
    out: list[RawCollectedRecord] = []
    offset = 0
    page_limit = 100
    total = None
    base_api = f"https://api.smartrecruiters.com/v1/companies/{cid}/postings"
    pause = max(0.0, get_settings().smartrecruiters_page_pause_seconds)
    while True:
        if offset > 0 and pause > 0:
            time.sleep(pause + random.uniform(0.0, min(pause * 0.2, 1.0)))

        data_o, tag = json_from_get(
            base_api,
            params={"limit": page_limit, "offset": offset},
            headers=_PUBLIC_UA_HEADERS,
        )
        if tag:
            if out:
                return out, ""
            return [], f"smartrecruiters:{tag}"
        data = data_o if isinstance(data_o, dict) else {}
        if not isinstance(data, dict):
            break
        content = data.get("content") or []
        total = data.get("totalFound")
        for row in content:
            if not isinstance(row, dict):
                continue
            title = (row.get("name") or "").strip()
            if _bad_title(title):
                continue
            vis = row.get("visibility")
            if isinstance(vis, str) and vis.upper() == "INTERNAL":
                continue
            loc = row.get("location") if isinstance(row.get("location"), dict) else {}
            location = ""
            if isinstance(loc, dict):
                location = str(loc.get("fullLocation") or "").strip()
            job_u = _smartrecruiters_public_job_url(cid, row)
            out.append(RawCollectedRecord(
                provider="smartrecruiters",
                source_url=source_url or board_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "ats_board",
                    "ats_type": "smartrecruiters",
                    "job_title": title,
                    "job_url": job_u,
                    "external_job_id": str(row.get("id") or ""),
                    "apply_url": (row.get("applyUrl") or "").strip(),
                    "ref_number": (row.get("refNumber") or "").strip(),
                    "released_date": row.get("releasedDate"),
                    "location": location,
                    "collected_at": now_iso(),
                    "native_api_item": row,
                    "collection_method": "smartrecruiters_v1_public",
                },
            ))
        if not content:
            break
        offset += page_limit
        if total is not None and offset >= int(total):
            break
        if len(content) < page_limit:
            break
    return out, ""


# ---------------------------------------------------------------------------
# Workable widget + Teamtailor RSS (prefer HTTP before Playwright)
# ---------------------------------------------------------------------------

_WORKABLE_SKIP_SEGS = frozenset(
    {"gdpr-policy", "gdpr_policy", "cookie", "privacy", "legal", "embed"},
)


def workable_widget_slug_from_url(board_url: str, ats_slug: str = "") -> Optional[str]:
    """Public JSON at ``/api/v1/widget/accounts/{slug}`` (no API key)."""

    s = (ats_slug or "").strip()
    if s:
        return s
    u = _light_normalize_url(board_url)
    if not u or "apply.workable.com" not in urlparse(u).netloc.lower():
        return None
    parts = [x for x in urlparse(u).path.strip("/").split("/") if x]
    if not parts:
        return None
    if parts[0].lower() == "j" and len(parts) <= 2:
        return None
    for seg in parts:
        low = seg.lower()
        if low in _WORKABLE_SKIP_SEGS:
            continue
        return seg
    return None


def collect_workable_widget_http(
    board_url: str,
    company_name: str,
    source_url: str,
    *,
    ats_slug: str = "",
) -> tuple[list[RawCollectedRecord], str]:
    slug = workable_widget_slug_from_url(board_url, ats_slug)
    if not slug:
        return [], "workable_widget_need_ats_slug_or_hub_url"
    api = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    data_o, tag = json_from_get(api, headers=_PUBLIC_UA_HEADERS)
    payload = data_o if isinstance(data_o, dict) else None
    if payload is None:
        return [], (f"workable_widget:{tag}" if tag else "workable_widget_empty")
    rows = payload.get("jobs")
    if not isinstance(rows, list) or not rows:
        return [], "workable_widget_no_jobs_array"
    out: list[RawCollectedRecord] = []
    for job in rows:
        if not isinstance(job, dict):
            continue
        title = (job.get("title") or "").strip()
        if _bad_title(title):
            continue
        raw_link = job.get("url") or job.get("shortlink") or job.get("application_url") or ""
        if isinstance(raw_link, (list, tuple)):
            raw_link = raw_link[0] if raw_link else ""
        ju = str(raw_link).strip()
        if not ju:
            continue
        parts_loc: list[str] = []
        if job.get("country"):
            parts_loc.append(str(job.get("country")))
        if job.get("city"):
            parts_loc.append(str(job.get("city")))
        location = ", ".join([p for p in parts_loc if p]).strip()

        shortcode = job.get("shortcode")
        external_id = str(shortcode) if shortcode is not None else ""

        out.append(
            RawCollectedRecord(
                provider="workable",
                source_url=source_url or board_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "ats_board",
                    "ats_type": "workable",
                    "job_title": title,
                    "job_url": ju,
                    "location": location,
                    "external_job_id": external_id or None,
                    "collected_at": now_iso(),
                    "native_api_item": job,
                    "collection_method": "workable_widget_public_v1",
                },
            )
        )

    return (out, ("" if out else "workable_widget_empty_roles"))


def collect_teamtailor_rss_http(
    board_url: str,
    company_name: str,
    source_url: str,
) -> tuple[list[RawCollectedRecord], str]:
    """RSS 2 feed ``https://{career-host}/jobs.rss`` (no auth)."""

    parsed = urlparse(board_url if "://" in board_url else ("https://" + board_url))
    host = (parsed.netloc or "").lower().strip()
    if not host.endswith("teamtailor.com"):
        return [], "teamtailor_rss_need_teamtailor_host"
    rss_url = f"https://{host}/jobs.rss"
    resp, rs_tag = http_get(rss_url, headers=_PUBLIC_UA_HEADERS)
    if resp is None:
        return [], f"teamtailor_rss:{rs_tag}"
    if not resp.ok:
        return [], f"teamtailor_rss:http_{resp.status_code}_{rs_tag or ''}".rstrip("_")
    rss = resp.text.encode("utf-8", errors="replace")
    try:
        root = ET.fromstring(rss)
    except ET.ParseError:
        return [], "teamtailor_rss:invalid_xml"

    items: list[ET.Element] = []
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.endswith("item"):
            items.append(el)

    if not items:
        return [], "teamtailor_rss:no_items"

    def _kid_text(par: ET.Element, local: str) -> str:
        for ch in par:
            if isinstance(ch.tag, str) and ch.tag.endswith(local):
                return (ch.text or "").strip()
        return ""

    out: list[RawCollectedRecord] = []
    for node in items:
        title_t = _kid_text(node, "title")
        link_t = _kid_text(node, "link")
        if not title_t or _bad_title(title_t):
            continue
        ju = (link_t or "").strip() or (board_url.split("?")[0])
        out.append(
            RawCollectedRecord(
                provider="teamtailor",
                source_url=source_url or board_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "ats_board",
                    "ats_type": "teamtailor",
                    "job_title": title_t.strip(),
                    "job_url": ju.strip() or board_url,
                    "collected_at": now_iso(),
                    "collection_method": "teamtailor_jobs_rss",
                },
            ),
        )

    return (out, ("" if out else "teamtailor_rss_empty_after_filter"))


# ---------------------------------------------------------------------------
# Rendered page collectors (browser required)
# ---------------------------------------------------------------------------

async def _fetch_rendered_html(browser, url: str, wait_ms: int = 2500) -> Optional[str]:
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(wait_ms)
        return await page.content()
    except Exception:
        return None
    finally:
        await page.close()


async def _collect_rendered_generic(
    browser,
    url: str,
    company_name: str,
    provider: str,
    source_type: str,
    ats_type: str = "",
    wait_ms: int = 2500,
) -> list[RawCollectedRecord]:
    html = await _fetch_rendered_html(browser, url, wait_ms=wait_ms)
    if not html:
        return []

    records: list[RawCollectedRecord] = []
    for href, text in _extract_links_with_text(html, url):
        title = (text or "").strip()
        low_u = href.lower()
        if href in BLACKLIST_URLS or _bad_title(title):
            continue
        if (
            any(k in low_u for k in ["/jobs/", "/job/", "/positions/", "/openings/", "/careers/"])
            or _joblike_title(title)
        ):
            records.append(RawCollectedRecord(
                provider=provider,
                source_url=url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": source_type,
                    "ats_type": ats_type,
                    "job_title": title,
                    "job_url": href,
                    "collected_at": now_iso(),
                },
            ))
    return records


async def _collect_workable_browser(
    browser,
    board_url: str,
    company_name: str,
) -> tuple[list[RawCollectedRecord], str]:
    html = await _fetch_rendered_html(browser, board_url, wait_ms=3500)
    if not html:
        return [], "workable_render_timeout"

    records: list[RawCollectedRecord] = []
    for href, text in _extract_links_with_text(html, board_url):
        title = (text or "").strip()
        if "apply.workable.com" in href.lower() and not _bad_title(title):
            records.append(RawCollectedRecord(
                provider="workable",
                source_url=board_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "ats_board",
                    "ats_type": "workable",
                    "job_title": title,
                    "job_url": href,
                    "collected_at": now_iso(),
                    "collection_method": "workable_rendered_dom",
                },
            ))

    if not records:
        soup = BeautifulSoup(html, "lxml")
        seen = set()
        for tag in soup.find_all(["h2", "h3", "h4", "a", "div", "span"]):
            t = tag.get_text(" ", strip=True)
            if 4 <= len(t) <= 140 and _joblike_title(t) and t.lower() not in seen:
                seen.add(t.lower())
                records.append(RawCollectedRecord(
                    provider="workable",
                    source_url=board_url,
                    raw_payload={
                        "company_name": company_name,
                        "source_type": "ats_board",
                        "ats_type": "workable",
                        "job_title": t,
                        "job_url": board_url,
                        "heading_fallback": True,
                        "collected_at": now_iso(),
                        "collection_method": "workable_rendered_heading_fallback",
                    },
                ))
    return records, ("" if records else "workable_zero_cards_found")


async def collect_workable(
    browser,
    board_url: str,
    company_name: str,
    *,
    ats_slug: str = "",
) -> tuple[list[RawCollectedRecord], str]:
    """Try public widget JSON, then Playwright on flaky or job-only URLs."""

    http_recs, http_tag = collect_workable_widget_http(
        board_url, company_name, board_url, ats_slug=ats_slug,
    )
    if http_recs:
        return http_recs, ""

    br_recs, br_tag = await _collect_workable_browser(browser, board_url, company_name)
    if br_recs:
        return br_recs, ""

    tail = http_tag or br_tag or "workable_empty"
    return [], tail


async def collect_teamtailor(
    browser,
    board_url: str,
    company_name: str,
) -> tuple[list[RawCollectedRecord], str]:
    rss_recs, rss_tag = collect_teamtailor_rss_http(board_url, company_name, board_url)
    if rss_recs:
        return rss_recs, ""
    gen = await _collect_rendered_generic(
        browser,
        board_url,
        company_name,
        provider="teamtailor",
        source_type="ats_board",
        ats_type="teamtailor",
        wait_ms=3500,
    )
    if gen:
        return gen, ""
    return [], rss_tag or "teamtailor_empty"


async def _collect_ashby_rendered(
    browser, board_url: str, company_name: str,
) -> tuple[list[RawCollectedRecord], str]:
    html = await _fetch_rendered_html(browser, board_url, wait_ms=3500)
    if not html:
        return [], "ashby_render_timeout"

    records: list[RawCollectedRecord] = []
    for href, text in _extract_links_with_text(html, board_url):
        title = (text or "").strip()
        if ("/jobs/" in href.lower() or "jobs.ashbyhq.com" in href.lower()) and not _bad_title(title):
            records.append(RawCollectedRecord(
                provider="ashby",
                source_url=board_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "ats_board",
                    "ats_type": "ashby",
                    "job_title": title,
                    "job_url": href,
                    "collected_at": now_iso(),
                    "collection_method": "rendered_jobs_page",
                },
            ))

    if not records:
        soup = BeautifulSoup(html, "lxml")
        seen = set()
        for tag in soup.find_all(["h2", "h3", "h4", "a", "div", "span"]):
            t = tag.get_text(" ", strip=True)
            if 4 <= len(t) <= 140 and _joblike_title(t) and t.lower() not in seen:
                seen.add(t.lower())
                records.append(RawCollectedRecord(
                    provider="ashby",
                    source_url=board_url,
                    raw_payload={
                        "company_name": company_name,
                        "source_type": "ats_board",
                        "ats_type": "ashby",
                        "job_title": t,
                        "job_url": board_url,
                        "heading_fallback": True,
                        "collected_at": now_iso(),
                        "collection_method": "rendered_heading_fallback",
                    },
                ))
    return records, ("" if records else "ashby_zero_cards_found")


async def collect_ashby(
    browser, board_url: str, company_name: str,
) -> tuple[list[RawCollectedRecord], str]:
    """Prefer Ashby's public posting API; fall back to Playwright scraping."""
    api_recs, need_fallback = collect_ashby_posting_api(
        board_url, company_name, board_url,
    )
    if api_recs:
        return api_recs, ""
    if not need_fallback:
        return [], "ashby_api_empty"
    return await _collect_ashby_rendered(browser, board_url, company_name)


async def collect_kula(browser, board_url: str, company_name: str) -> tuple[list[RawCollectedRecord], str]:
    html = await _fetch_rendered_html(browser, board_url, wait_ms=3500)
    if not html:
        return [], "kula_render_timeout"

    soup = BeautifulSoup(html, "lxml")
    records: list[RawCollectedRecord] = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if href.startswith("/"):
            href = board_url.rstrip("/") + "/" + href.lstrip("/")
        href_n = _light_normalize_url(href)
        if not href_n or href_n in BLACKLIST_URLS:
            continue
        text = a.get_text(" ", strip=True)
        low = text.lower()
        if low in BAD_JOB_TITLES or low in {"apply now", "apply"}:
            title = _nearest_heading_title(a)
            if title and _joblike_title(title):
                records.append(RawCollectedRecord(
                    provider="kula",
                    source_url=board_url,
                    raw_payload={
                        "company_name": company_name,
                        "source_type": "ats_board",
                        "ats_type": "kula",
                        "job_title": title,
                        "job_url": href_n,
                        "collected_at": now_iso(),
                    },
                ))
        elif ("careers.kula.ai" in href_n.lower() or "/jobs/" in href_n.lower()) and not _bad_title(text):
            records.append(RawCollectedRecord(
                provider="kula",
                source_url=board_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "ats_board",
                    "ats_type": "kula",
                    "job_title": text.strip(),
                    "job_url": href_n,
                    "collected_at": now_iso(),
                },
            ))

    if not records:
        seen = set()
        for tag in soup.find_all(["h2", "h3", "h4", "a", "div", "span"]):
            t = tag.get_text(" ", strip=True)
            if 4 <= len(t) <= 140 and _joblike_title(t) and t.lower() not in seen:
                seen.add(t.lower())
                records.append(RawCollectedRecord(
                    provider="kula",
                    source_url=board_url,
                    raw_payload={
                        "company_name": company_name,
                        "source_type": "ats_board",
                        "ats_type": "kula",
                        "job_title": t,
                        "job_url": board_url,
                        "heading_fallback": True,
                        "collected_at": now_iso(),
                    },
                ))
    return records, ("" if records else "kula_empty_dom")


async def collect_binance_native(browser, jobs_url: str, company_name: str) -> tuple[list[RawCollectedRecord], str]:
    html = await _fetch_rendered_html(browser, jobs_url, wait_ms=4000)
    if not html:
        return [], "binance_render_timeout"

    records: list[RawCollectedRecord] = []
    for href, text in _extract_links_with_text(html, jobs_url):
        title = (text or "").strip()
        if _bad_title(title):
            continue
        if _joblike_title(title):
            records.append(RawCollectedRecord(
                provider="native_jobs_page",
                source_url=jobs_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "native_jobs_page",
                    "job_title": title,
                    "job_url": href or jobs_url,
                    "collected_at": now_iso(),
                },
            ))
    return records, ("" if records else "binance_no_role_rows")


async def collect_oracle_native(browser, jobs_url: str, company_name: str) -> tuple[list[RawCollectedRecord], str]:
    html = await _fetch_rendered_html(browser, jobs_url, wait_ms=4000)
    if not html:
        return [], "oracle_render_timeout"

    records: list[RawCollectedRecord] = []
    for href, text in _extract_links_with_text(html, jobs_url):
        title = (text or "").strip()
        if _bad_title(title):
            continue
        if _joblike_title(title):
            records.append(RawCollectedRecord(
                provider="native_jobs_page",
                source_url=jobs_url,
                raw_payload={
                    "company_name": company_name,
                    "source_type": "native_jobs_page",
                    "job_title": title,
                    "job_url": href or jobs_url,
                    "collected_at": now_iso(),
                },
            ))
    return records, ("" if records else "oracle_no_role_rows")


# ---------------------------------------------------------------------------
# Dispatch + driver
# ---------------------------------------------------------------------------

async def _collect_one_source(browser, row: SourceRow) -> tuple[list[RawCollectedRecord], str]:
    """Return (records, error_reason). Error reason is "" on success."""
    if row.official_site and "binance.com" in row.official_site:
        return await collect_binance_native(browser, BINANCE_OVERRIDE, row.company_name)

    if row.jobs_page and "oraclecloud.com" in row.jobs_page:
        return await collect_oracle_native(browser, row.jobs_page, row.company_name)

    if row.ats_board_url:
        if row.ats_type == "jobstash":
            recs_js, jst_reason = collect_jobstash(row)
            return (
                recs_js,
                ("" if recs_js else (jst_reason or "jobstash_empty")),
            )
        if row.ats_type == "lever":
            return collect_lever(row.ats_board_url, row.company_name, row.ats_board_url)
        if row.ats_type == "greenhouse":
            return collect_greenhouse(row.ats_board_url, row.company_name, row.ats_board_url)
        if row.ats_type == "workable":
            return await collect_workable(
                browser, row.ats_board_url, row.company_name, ats_slug=row.ats_slug,
            )
        if row.ats_type == "smartrecruiters":
            su = row.ats_board_url or ""
            cid = _smartrecruiters_company_id(su, row.ats_slug)
            src = (
                row.ats_board_url or row.jobs_page
                or (f"https://jobs.smartrecruiters.com/{cid}/" if cid else "")
            )
            return collect_smartrecruiters_api(
                su,
                row.company_name,
                src,
                ats_slug=row.ats_slug,
            )
        if row.ats_type == "teamtailor":
            return await collect_teamtailor(browser, row.ats_board_url, row.company_name)
        if row.ats_type == "ashby":
            return await collect_ashby(browser, row.ats_board_url, row.company_name)
        if row.ats_type == "kula":
            return await collect_kula(browser, row.ats_board_url, row.company_name)
        if row.ats_type == "remoteok":
            recs, reason = collect_remoteok(row)
            return recs, ("" if recs else (reason or "remoteok_empty"))
        if row.ats_type == "weworkremotely":
            recs, reason = collect_weworkremotely(row)
            return recs, ("" if recs else (reason or "wwr_empty"))
        if row.ats_type == "arbeitnow":
            recs, reason = collect_arbeitnow(row)
            return recs, ("" if recs else (reason or "arbeitnow_empty"))
        if row.ats_type == "workday":
            recs, reason = await collect_workday(
                browser, row.ats_board_url, row.company_name, row.ats_board_url,
                ats_slug=row.ats_slug, keyword_filter=row.notes,
            )
            return recs, ("" if recs else (reason or "workday_empty"))
        if row.ats_type == "jsearch":
            recs, reason = collect_jsearch(row)
            return recs, ("" if recs else (reason or "jsearch_empty"))
        if row.ats_type == "adzuna":
            recs, reason = collect_adzuna(row)
            return recs, ("" if recs else (reason or "adzuna_empty"))
        if row.ats_type == "themuse":
            recs, reason = collect_themuse(row)
            return recs, ("" if recs else (reason or "themuse_empty"))
        if row.ats_type == "jobicy":
            recs, reason = collect_jobicy(row)
            return recs, ("" if recs else (reason or "jobicy_empty"))
        if row.ats_type == "himalayas":
            recs, reason = collect_himalayas(row)
            return recs, ("" if recs else (reason or "himalayas_empty"))
        return [], "unsupported_ats_type"

    if row.resolution_type == "validated_native_jobs_page" and row.jobs_page:
        recs = await _collect_rendered_generic(
            browser, row.jobs_page, row.company_name,
            provider="native_jobs_page", source_type="native_jobs_page",
        )
        return recs, ("" if recs else "native_page_no_links")

    if row.resolution_type == "cryptojobslist_fallback_only" and row.cryptojobslist_fallback_jobs_page:
        recs = await _collect_rendered_generic(
            browser, row.cryptojobslist_fallback_jobs_page, row.company_name,
            provider="cryptojobslist", source_type="cryptojobslist_fallback",
        )
        return recs, ("" if recs else "fallback_no_links")

    if row.jobs_page:
        recs = await _collect_rendered_generic(
            browser, row.jobs_page, row.company_name,
            provider="jobs_page", source_type="jobs_page",
        )
        return recs, ("" if recs else "jobs_page_no_links")

    return [], "no_source_url"


async def collect_all(
    sources: list[SourceRow],
    *,
    headless: bool = True,
    progress_cb: Any = None,
) -> AsyncIterator[tuple[SourceRow, list[RawCollectedRecord], str]]:
    """Async generator yielding one tuple per source:
        (source_row, records, error_reason)

    Playwright is imported lazily so importing this module in API-only
    environments doesn't require a browser install.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            for idx, row in enumerate(sources, start=1):
                if progress_cb is not None:
                    progress_cb(idx, len(sources), row)
                try:
                    records, reason = await _collect_one_source(browser, row)
                    yield row, records, reason
                except Exception as e:  # noqa: BLE001
                    yield row, [], f"error:{type(e).__name__}:{str(e)[:200]}"
        finally:
            await browser.close()
