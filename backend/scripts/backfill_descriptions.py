"""Backfill job descriptions for active jobs that are missing them.

Targets Greenhouse, Ashby, and Lever jobs. Fetches descriptions from
each provider's public API and updates description_clean in the DB.

Usage:
    python scripts/backfill_descriptions.py
    python scripts/backfill_descriptions.py --provider greenhouse
    python scripts/backfill_descriptions.py --limit 100 --dry-run
    python scripts/backfill_descriptions.py --batch-size 50

Rate limits (conservative):
    Greenhouse: 0.5s sleep between requests
    Ashby:      0.2s sleep (batch-able per board)
    Lever:      0.3s sleep between requests
"""
from __future__ import annotations

import argparse
import html as html_lib
import logging
import re
import sys
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# Allow running as `python scripts/backfill_descriptions.py` from backend dir
sys.path.insert(0, ".")

from app.db import SessionLocal
from app.models.job import Job
from sqlalchemy import select, and_, or_

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_DESC_MAX_CHARS = 8_000
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "Atlas-Job-Tracker/1.0 (job description backfill)"


# ---------------------------------------------------------------------------
# HTML → plain text
# ---------------------------------------------------------------------------

def _html_to_text(raw: str) -> str:
    if not raw:
        return ""
    unescaped = html_lib.unescape(raw)
    soup = BeautifulSoup(unescaped, "lxml")
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines()]
    cleaned = "\n".join(l for l in lines if l)
    return cleaned[:_DESC_MAX_CHARS]


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------
# URL patterns:
#   https://job-boards.greenhouse.io/{slug}/jobs/{id}
#   https://boards.greenhouse.io/{slug}/jobs/{id}
#   https://boards.eu.greenhouse.io/{slug}/jobs/{id}
#   https://custom.domain.com/job/{id}?gh_jid={id}    ← extract gh_jid

_GH_PATH_RE = re.compile(r"/jobs/(\d+)")


def _parse_greenhouse_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """Return (slug, job_id) from a Greenhouse apply_url, or (None, None)."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    # Custom domain with ?gh_jid= or ?gh_src_jid=
    job_id = None
    for key in ("gh_jid", "gh_src_jid"):
        if key in qs:
            job_id = qs[key][0]
            break

    if job_id:
        # Need to find slug from the path — not always in URL for custom domains
        # Try extracting from path like /job/{slug}/{id} or /careers/{slug}
        # For custom domains, we may not have the slug. Skip those.
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        # Look for a slug-like segment before the job id
        m = _GH_PATH_RE.search(parsed.path)
        if not m:
            # Path like /job/123 — no slug in URL, skip
            return None, None
        # Check for greenhouse-style /jobs/{id} with slug in earlier segment
        # e.g. /careers/flix/jobs/8525194002 — slug is segment before "jobs"
        idx = parts.index("jobs") if "jobs" in parts else -1
        if idx > 0:
            slug = parts[idx - 1]
            return slug, job_id
        return None, None

    # Standard Greenhouse board URL: {host}/{slug}/jobs/{id}
    # Hostname is job-boards.greenhouse.io or boards.greenhouse.io etc.
    host = parsed.netloc.lower()
    if "greenhouse.io" in host:
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        m = _GH_PATH_RE.search(parsed.path)
        if m and len(parts) >= 2:
            # Find index of "jobs" in parts
            try:
                jobs_idx = parts.index("jobs")
                if jobs_idx > 0:
                    slug = parts[jobs_idx - 1]
                    job_id = parts[jobs_idx + 1] if jobs_idx + 1 < len(parts) else m.group(1)
                    return slug, job_id
            except ValueError:
                pass
        return None, None

    return None, None


def fetch_greenhouse_description(url: str) -> Optional[str]:
    slug, job_id = _parse_greenhouse_url(url)
    if not slug or not job_id:
        return None

    api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
    try:
        r = _SESSION.get(api_url, timeout=15)
        if r.status_code == 404:
            # Try EU endpoint
            api_url = f"https://boards-api.eu.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
            r = _SESSION.get(api_url, timeout=15)
        r.raise_for_status()
        content = r.json().get("content") or ""
        return _html_to_text(content) if content else None
    except Exception as e:
        log.debug("greenhouse fetch failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------
# URL pattern: https://jobs.ashbyhq.com/{slug}/{uuid}

def _parse_ashby_url(url: str) -> tuple[Optional[str], Optional[str]]:
    parsed = urlparse(url)
    if "ashbyhq.com" not in parsed.netloc:
        return None, None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def fetch_ashby_description(url: str) -> Optional[str]:
    slug, job_id = _parse_ashby_url(url)
    if not slug or not job_id:
        return None

    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        r = _SESSION.get(api_url, timeout=15, params={"includeCompensation": "false"})
        r.raise_for_status()
        jobs = r.json().get("jobs") or []
        for job in jobs:
            if job.get("id") == job_id or job.get("id", "").lower() == job_id.lower():
                desc = job.get("descriptionPlain") or _html_to_text(job.get("descriptionHtml") or "")
                return desc if desc else None
        return None
    except Exception as e:
        log.debug("ashby fetch failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------
# URL pattern: https://jobs.lever.co/{slug}/{uuid}

def _parse_lever_url(url: str) -> tuple[Optional[str], Optional[str]]:
    parsed = urlparse(url)
    if "lever.co" not in parsed.netloc:
        return None, None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def fetch_lever_description(url: str) -> Optional[str]:
    slug, job_id = _parse_lever_url(url)
    if not slug or not job_id:
        return None

    api_url = f"https://api.lever.co/v0/postings/{slug}/{job_id}"
    try:
        r = _SESSION.get(api_url, timeout=15)
        r.raise_for_status()
        data = r.json()
        # Lever splits content across multiple fields; assemble them
        parts: list[str] = []

        # Plain description fields (may be empty)
        for field in ("descriptionPlain", "descriptionBodyPlain", "openingPlain"):
            val = (data.get(field) or "").strip()
            if val:
                parts.append(val)

        # Section lists (requirements, responsibilities, etc.)
        for section in data.get("lists") or []:
            header = (section.get("text") or "").strip()
            content_html = section.get("content") or ""
            if header:
                parts.append(header)
            if content_html:
                parts.append(_html_to_text(content_html))

        # Additional info (benefits etc.)
        additional = (data.get("additionalPlain") or "").strip()
        if additional:
            parts.append(additional)

        combined = "\n\n".join(p for p in parts if p)
        return combined[:_DESC_MAX_CHARS] if combined else None
    except Exception as e:
        log.debug("lever fetch failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Main backfill loop
# ---------------------------------------------------------------------------

PROVIDER_HANDLERS = {
    "greenhouse": (fetch_greenhouse_description, 0.5),
    "ashby": (fetch_ashby_description, 0.2),
    "lever": (fetch_lever_description, 0.3),
}


def run_backfill(
    providers: list[str],
    limit: int,
    batch_size: int,
    dry_run: bool,
) -> None:
    db = SessionLocal()
    try:
        for provider in providers:
            fetch_fn, sleep_secs = PROVIDER_HANDLERS[provider]

            stmt = (
                select(Job)
                .where(
                    Job.is_active.is_(True),
                    Job.provider == provider,
                    or_(Job.description_clean.is_(None), Job.description_clean == ""),
                    Job.apply_url.is_not(None),
                )
                .order_by(Job.ranking_score.desc())  # do highest-scored first
                .limit(limit)
            )
            jobs = db.execute(stmt).scalars().all()
            total = len(jobs)
            log.info("[%s] %d jobs to backfill", provider, total)

            ok = 0
            failed = 0
            skipped = 0

            for i, job in enumerate(jobs, 1):
                desc = fetch_fn(job.apply_url)
                time.sleep(sleep_secs)

                if not desc:
                    skipped += 1
                    if i % 100 == 0 or i <= 3:
                        log.info(
                            "[%s] %d/%d — no desc: %s @ %s",
                            provider, i, total, job.title[:40], job.company_name,
                        )
                    continue

                if dry_run:
                    log.info(
                        "[%s] DRY-RUN %d/%d — would update: %s @ %s (%d chars)",
                        provider, i, total, job.title[:40], job.company_name, len(desc),
                    )
                    ok += 1
                    continue

                job.description_clean = desc
                ok += 1

                if i % batch_size == 0:
                    db.commit()
                    log.info(
                        "[%s] %d/%d — committed batch. ok=%d skipped=%d failed=%d",
                        provider, i, total, ok, skipped, failed,
                    )
                elif i % 10 == 0:
                    log.info(
                        "[%s] %d/%d — ok=%d skipped=%d failed=%d",
                        provider, i, total, ok, skipped, failed,
                    )

            if not dry_run:
                db.commit()

            log.info(
                "[%s] Done. ok=%d / skipped=%d / failed=%d out of %d",
                provider, ok, skipped, failed, total,
            )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill job descriptions")
    parser.add_argument(
        "--provider",
        choices=["greenhouse", "ashby", "lever", "all"],
        default="all",
        help="Which provider to backfill (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=99999,
        help="Max jobs per provider (default: all)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Commit to DB every N jobs (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch descriptions but don't write to DB",
    )
    args = parser.parse_args()

    providers = (
        list(PROVIDER_HANDLERS.keys())
        if args.provider == "all"
        else [args.provider]
    )

    log.info(
        "Starting backfill: providers=%s limit=%d dry_run=%s",
        providers, args.limit, args.dry_run,
    )
    run_backfill(
        providers=providers,
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    log.info("Backfill complete.")


if __name__ == "__main__":
    main()
