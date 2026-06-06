"""Workday ATS collector.

Workday boards load job data via an authenticated POST to a JSON endpoint:

    POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs

The problem is that Workday sits behind Cloudflare and requires a browser
session — raw requests.post returns 422/500.  The solution is Playwright:

  1. Open the board page in a real browser context (bypasses Cloudflare).
  2. Intercept every /wday/cxs/.../jobs POST response.
  3. Parse those JSON payloads directly — no HTML parsing needed.
  4. If interception captures nothing (JS failed, wrong URL) fall back to
     scraping visible job card text from the rendered HTML.

Board URL format
----------------
Pass the company's Workday careers URL as ``ats_board_url``:
    https://{tenant}.wd{N}.myworkdayjobs.com/en-US/{board}/jobs
    (or the root board page without /jobs)

``ats_slug`` overrides the board path segment if autodetection fails.
``notes`` may contain comma-separated title keywords to filter results
(useful for large boards like Salesforce with thousands of unrelated roles).
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlparse

from .base import RawCollectedRecord, SourceRow, now_iso

_WAIT_MS = 4000          # ms to wait after page load for XHR to fire
_INTERCEPT_TIMEOUT = 25  # seconds to wait for at least one API response


def _parse_workday_board_url(board_url: str, ats_slug: str = "") -> tuple[str, str, str] | None:
    """Return (tenant, wd_instance, board_path) or None.

    Strips locale prefixes (/en-US/, /en_US/) and /jobs suffix.
    ats_slug overrides the autodetected board_path.
    """
    u = (board_url or "").strip().rstrip("/")
    if not u:
        return None
    parsed = urlparse(u)
    host = parsed.netloc.lower()
    m = re.match(r"^([a-z0-9_-]+)\.(wd\d+)\.myworkdayjobs\.com$", host)
    if not m:
        return None
    tenant = m.group(1)
    wd_inst = m.group(2)
    # Strip locale and trailing /jobs from path
    path_parts = [
        p for p in parsed.path.strip("/").split("/")
        if p and not re.match(r"^(en[-_][A-Z]{2}|jobs)$", p)
    ]
    board = (ats_slug.strip() if ats_slug.strip()
             else (path_parts[0] if path_parts else tenant))
    return tenant, wd_inst, board


def _job_url_from_ext_path(tenant: str, wd_inst: str, ext_path: str) -> str:
    if not ext_path:
        return ""
    if ext_path.startswith("http"):
        return ext_path
    return f"https://{tenant}.{wd_inst}.myworkdayjobs.com/{ext_path.lstrip('/')}"


def _parse_jobs_response(
    data: dict[str, Any],
    company_name: str,
    tenant: str,
    wd_inst: str,
    board: str,
    source_url: str,
    kw_filter: list[str],
) -> list[RawCollectedRecord]:
    postings = data.get("jobPostings") or []
    records: list[RawCollectedRecord] = []
    for job in postings:
        if not isinstance(job, dict):
            continue
        title = str(job.get("title") or "").strip()
        if not title:
            continue
        if kw_filter and not any(kw in title.lower() for kw in kw_filter):
            continue
        ext_path = str(job.get("externalPath") or "").strip()
        job_url = _job_url_from_ext_path(tenant, wd_inst, ext_path)
        location_raw = job.get("locationsText") or job.get("location") or ""
        location = (
            str(location_raw.get("description", "")) if isinstance(location_raw, dict)
            else str(location_raw)
        ).strip()
        remote_hint: bool | None = None
        if location and ("remote" in location.lower() or "anywhere" in location.lower()):
            remote_hint = True
        records.append(RawCollectedRecord(
            provider="workday",
            source_url=source_url,
            raw_payload={
                "company_name": company_name,
                "source_type": "ats_board",
                "ats_type": "workday",
                "job_title": title,
                "job_url": job_url,
                "apply_url": job_url,
                "location": location,
                "remote_hint": remote_hint,
                "external_job_id": ext_path,
                "workday_tenant": tenant,
                "workday_board": board,
                "collected_at": now_iso(),
                "collection_method": "workday_xhr_intercept",
                "native_api_item": job,
            },
        ))
    return records


async def collect_workday(
    browser,
    board_url: str,
    company_name: str,
    source_url: str,
    *,
    ats_slug: str = "",
    keyword_filter: str = "",
) -> tuple[list[RawCollectedRecord], str]:
    """Collect jobs from a Workday board using Playwright network interception.

    Called by ``web3_ats._collect_one_source`` (async path).
    """
    parsed = _parse_workday_board_url(board_url, ats_slug)
    if parsed is None:
        return [], "workday_unparseable_url"

    tenant, wd_inst, board = parsed
    kw_filter = [k.strip().lower() for k in keyword_filter.split(",") if k.strip()] if keyword_filter else []

    # Navigate to the jobs listing page (with /jobs suffix so it loads results)
    navigate_url = board_url
    if not navigate_url.rstrip("/").endswith("/jobs"):
        navigate_url = navigate_url.rstrip("/") + "/jobs"

    # Collect all intercepted JSON responses from the Workday API
    intercepted_payloads: list[dict[str, Any]] = []

    page = await browser.new_page()
    try:
        async def handle_response(response) -> None:
            url = response.url
            if "/wday/cxs/" in url and url.endswith("/jobs"):
                try:
                    body = await response.body()
                    data = json.loads(body)
                    if isinstance(data, dict) and "jobPostings" in data:
                        intercepted_payloads.append(data)
                except Exception:
                    pass

        page.on("response", handle_response)

        await page.goto(navigate_url, wait_until="domcontentloaded", timeout=35000)
        # Wait for XHR to fire
        await page.wait_for_timeout(_WAIT_MS)

        # If we got API data via interception, use it
        if intercepted_payloads:
            records: list[RawCollectedRecord] = []
            for payload in intercepted_payloads:
                records.extend(_parse_jobs_response(
                    payload, company_name, tenant, wd_inst, board, source_url, kw_filter,
                ))
            return records, ("" if records else "workday_api_empty")

        # Fallback: extract job links from rendered HTML
        html = await page.content()
        records = _scrape_html_fallback(html, company_name, tenant, wd_inst, board, source_url, kw_filter)
        reason = "" if records else "workday_no_postings"
        return records, reason

    except Exception as exc:
        err_type = type(exc).__name__
        return [], f"workday_playwright_error:{err_type}"
    finally:
        await page.close()


def _scrape_html_fallback(
    html: str,
    company_name: str,
    tenant: str,
    wd_inst: str,
    board: str,
    source_url: str,
    kw_filter: list[str],
) -> list[RawCollectedRecord]:
    """Parse job cards from rendered Workday HTML as a last resort."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    records: list[RawCollectedRecord] = []
    seen: set[str] = set()

    # Workday job cards are typically inside <li> with data-automation-id
    for el in soup.find_all(attrs={"data-automation-id": True}):
        aid = str(el.get("data-automation-id") or "")
        if "jobItem" not in aid and "job-posting" not in aid.lower():
            continue
        a_tag = el.find("a", href=True)
        if not a_tag:
            continue
        href = str(a_tag.get("href") or "").strip()
        if not href:
            continue
        title = a_tag.get_text(" ", strip=True)
        if not title or title.lower() in seen:
            continue
        if kw_filter and not any(kw in title.lower() for kw in kw_filter):
            continue
        seen.add(title.lower())
        full_url = (f"https://{tenant}.{wd_inst}.myworkdayjobs.com{href}"
                    if href.startswith("/") else href)
        records.append(RawCollectedRecord(
            provider="workday",
            source_url=source_url,
            raw_payload={
                "company_name": company_name,
                "source_type": "ats_board",
                "ats_type": "workday",
                "job_title": title,
                "job_url": full_url,
                "apply_url": full_url,
                "workday_tenant": tenant,
                "workday_board": board,
                "collected_at": now_iso(),
                "collection_method": "workday_html_fallback",
            },
        ))
    return records
