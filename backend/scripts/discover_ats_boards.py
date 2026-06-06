"""ATS Board Discovery Script.

Automatically discovers new Greenhouse, Lever, and Ashby company job boards
by searching for known URL patterns. Validates each found board is live, then
appends genuinely new companies to ``scripts/company_ats_sources.csv``.

Safe to re-run — deduplicates on (ats_type, slug) and uses a checkpoint file
to skip already-attempted searches, so overnight runs resume from where they
left off if interrupted.

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/discover_ats_boards.py
    .venv/Scripts/python.exe scripts/discover_ats_boards.py --max-searches 2000
    .venv/Scripts/python.exe scripts/discover_ats_boards.py --dry-run --max-searches 10
    .venv/Scripts/python.exe scripts/discover_ats_boards.py --reset-checkpoint

Options (env vars via .env or shell):
    ATLAS_SERPAPI_KEY          — SerpAPI key (100 free searches/month at serpapi.com).
                                 When absent, falls back to DuckDuckGo (ddgs library).
    ATLAS_COMPANY_SOURCES_CSV  — path to the target CSV (default: scripts/company_ats_sources.csv)

Search strategy
---------------
Greenhouse : site:boards.greenhouse.io        + role/industry keywords
             site:job-boards.greenhouse.io    + role/industry keywords
             site:boards.eu.greenhouse.io     + role/industry keywords  (EU companies)
Lever      : site:jobs.lever.co               + role/industry keywords
Ashby      : site:jobs.ashbyhq.com            + role/industry keywords

Keywords span: engineering, product, design, data/ML/AI, devops/infra, security,
web3/crypto/DeFi/NFT, mobile, QA, finance, HR, ops, sales, marketing, legal —
covering the full breadth of roles at global tech companies.

Validation
----------
Each candidate URL is validated before adding:
  Greenhouse: GET the board page (200 + content > 500 bytes).
  Lever:      GET https://api.lever.co/v0/postings/{slug}?mode=json (public feed).
  Ashby:      GET https://api.ashbyhq.com/posting-api/job-board/{slug}.

Boards returning HTTP 200 with a valid response shape are added regardless of
whether they currently have openings (they will rotate in/out over time).

Checkpoint
----------
A JSON file next to the script (discover_checkpoint.json) records which
(target_site, keyword) pairs have been attempted. Interrupted runs pick up
where they left off. Pass --reset-checkpoint to start fresh.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

try:
    from ddgs import DDGS as _DDGS
    _HAS_DDGS = True
except ImportError:
    _HAS_DDGS = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.collectors.base import SourceRow  # noqa: E402
from app.collectors.web3_ats import load_sources  # noqa: E402

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("ddgs").setLevel(logging.WARNING)
logging.getLogger("duckduckgo_search").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CSV_HEADER = [
    "company_name", "source", "profile_url", "official_site", "jobs_page",
    "ats_type", "ats_board_url", "ats_slug", "cryptojobslist_fallback_jobs_page",
    "resolution_type", "notes",
]

_UA = "Mozilla/5.0 (compatible; AtlasATS-Discovery/1.0; +https://example.invalid)"
_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/html;q=0.9"}

_CHECKPOINT_FILE = Path(__file__).parent / "discover_checkpoint.json"

# ---------------------------------------------------------------------------
# Keywords — comprehensive global tech + web3 coverage
# ---------------------------------------------------------------------------

_INDUSTRY_KEYWORDS: list[str] = [
    # ── Software Engineering ──────────────────────────────────────────────
    "software engineer",
    "senior software engineer",
    "staff software engineer",
    "principal engineer",
    "backend engineer",
    "frontend engineer",
    "full stack engineer",
    "full stack developer",
    "software developer",
    "senior developer",
    "engineering manager",
    "director of engineering",
    "VP of engineering",
    "head of engineering",
    "platform engineer",
    "site reliability engineer",
    "SRE",
    "infrastructure engineer",
    "cloud engineer",
    "DevOps engineer",
    "systems engineer",
    "embedded engineer",
    "firmware engineer",
    "compiler engineer",
    "runtime engineer",

    # ── Languages / Stacks ───────────────────────────────────────────────
    "Python engineer",
    "Go engineer",
    "Rust engineer",
    "TypeScript engineer",
    "React engineer",
    "Node.js engineer",
    "Java engineer",
    "Kotlin engineer",
    "Swift engineer",
    "C++ engineer",
    "Elixir engineer",
    "Rails engineer",
    "Ruby on Rails",

    # ── Mobile ───────────────────────────────────────────────────────────
    "iOS engineer",
    "Android engineer",
    "mobile engineer",
    "React Native engineer",
    "Flutter developer",

    # ── Data / ML / AI ───────────────────────────────────────────────────
    "data engineer",
    "data scientist",
    "machine learning engineer",
    "ML engineer",
    "AI engineer",
    "applied scientist",
    "research scientist",
    "NLP engineer",
    "computer vision engineer",
    "data analyst",
    "analytics engineer",
    "business intelligence engineer",
    "quantitative analyst",
    "quant researcher",
    "head of data",
    "director of data science",

    # ── Infrastructure / Cloud / DevOps ──────────────────────────────────
    "cloud architect",
    "AWS engineer",
    "GCP engineer",
    "Azure engineer",
    "Kubernetes engineer",
    "Terraform engineer",
    "network engineer",
    "distributed systems",
    "platform architect",
    "database engineer",
    "database administrator",
    "DBA",

    # ── Security ─────────────────────────────────────────────────────────
    "security engineer",
    "application security engineer",
    "information security",
    "penetration tester",
    "security researcher",
    "blockchain security",
    "smart contract auditor",
    "cryptography engineer",

    # ── Web3 / Crypto / DeFi / NFT ───────────────────────────────────────
    "blockchain engineer",
    "smart contract engineer",
    "Solidity engineer",
    "Solidity developer",
    "web3 engineer",
    "web3 developer",
    "DeFi engineer",
    "protocol engineer",
    "crypto engineer",
    "layer 2 engineer",
    "consensus engineer",
    "validator engineer",
    "node operator",
    "tokenomics",
    "on-chain analyst",
    "blockchain architect",
    "EVM engineer",
    "Ethereum developer",
    "Solana developer",
    "Move developer",
    "zkEVM engineer",
    "zero knowledge",
    "ZK proof engineer",
    "cryptographic protocol",
    "MEV researcher",
    "defi protocol",
    "NFT engineer",
    "web3 community",
    "crypto community",
    "ecosystem growth",
    "developer relations web3",
    "devrel blockchain",
    "head of community crypto",

    # ── Product ───────────────────────────────────────────────────────────
    "product manager",
    "senior product manager",
    "principal product manager",
    "group product manager",
    "director of product",
    "VP of product",
    "head of product",
    "chief product officer",
    "product lead",
    "product owner",
    "technical product manager",
    "crypto product manager",
    "web3 product manager",

    # ── Design / UX ──────────────────────────────────────────────────────
    "product designer",
    "UX designer",
    "UI designer",
    "UX researcher",
    "design lead",
    "senior designer",
    "head of design",
    "design systems",
    "motion designer",
    "brand designer",

    # ── QA / Testing ─────────────────────────────────────────────────────
    "QA engineer",
    "quality assurance engineer",
    "test engineer",
    "automation engineer",
    "SDET",

    # ── Technical Writing / Documentation ────────────────────────────────
    "technical writer",
    "developer documentation",
    "developer advocate",
    "developer relations",
    "devrel",

    # ── Marketing ────────────────────────────────────────────────────────
    "growth marketing",
    "product marketing manager",
    "content marketing manager",
    "SEO manager",
    "performance marketing",
    "head of marketing",
    "VP marketing",
    "community manager",
    "social media manager",
    "brand manager",
    "partnerships manager",

    # ── Sales / Revenue ──────────────────────────────────────────────────
    "account executive",
    "solutions engineer",
    "sales engineer",
    "enterprise account executive",
    "business development",
    "revenue operations",
    "customer success manager",
    "customer success",
    "head of sales",
    "VP sales",

    # ── Finance / Legal / Ops ────────────────────────────────────────────
    "chief financial officer",
    "finance manager",
    "financial analyst",
    "controller",
    "head of finance",
    "general counsel",
    "legal counsel",
    "compliance officer",
    "AML officer",
    "chief operating officer",
    "head of operations",
    "operations manager",
    "people operations",
    "HR manager",
    "recruiter",
    "talent acquisition",

    # ── Leadership / C-Suite ─────────────────────────────────────────────
    "chief technology officer",
    "CTO",
    "chief executive officer",
    "VP engineering",
    "technical lead",
    "tech lead",

    # ── Remote / Global markers ──────────────────────────────────────────
    "remote software engineer",
    "remote engineer",
    "remote developer",
    "remote work",
    "hybrid engineer",
    "distributed team",
    "globally distributed",
    "remote first",
]

# Shuffle once at module load so each run explores a different order
random.shuffle(_INDUSTRY_KEYWORDS)

# ---------------------------------------------------------------------------
# ATS targets
# ---------------------------------------------------------------------------

_ATS_TARGETS = [
    {
        "ats_type": "greenhouse",
        "site": "site:boards.greenhouse.io",
        "board_url_tpl": "https://boards.greenhouse.io/{slug}",
        "slug_re": r"boards\.greenhouse\.io/([^/?#\s]+)",
    },
    {
        "ats_type": "greenhouse",
        "site": "site:job-boards.greenhouse.io",
        "board_url_tpl": "https://job-boards.greenhouse.io/{slug}",
        "slug_re": r"job-boards\.greenhouse\.io/([^/?#\s]+)",
    },
    {
        "ats_type": "greenhouse",
        "site": "site:boards.eu.greenhouse.io",
        "board_url_tpl": "https://boards.eu.greenhouse.io/{slug}",
        "slug_re": r"boards\.eu\.greenhouse\.io/([^/?#\s]+)",
    },
    {
        "ats_type": "lever",
        "site": "site:jobs.lever.co",
        "board_url_tpl": "https://jobs.lever.co/{slug}",
        "slug_re": r"jobs\.lever\.co/([^/?#\s]+)",
    },
    {
        "ats_type": "ashby",
        "site": "site:jobs.ashbyhq.com",
        "board_url_tpl": "https://jobs.ashbyhq.com/{slug}",
        "slug_re": r"jobs\.ashbyhq\.com/([^/?#\s]+)",
    },
]

# Polite overnight pacing — slow enough to avoid rate limits over hours
_SEARCH_GAP_MIN = 3.0
_SEARCH_GAP_MAX = 6.0
_VALIDATE_TIMEOUT = 12

# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def _load_checkpoint() -> set[str]:
    """Return set of already-attempted 'site::keyword' keys."""
    if not _CHECKPOINT_FILE.exists():
        return set()
    try:
        data = json.loads(_CHECKPOINT_FILE.read_text(encoding="utf-8"))
        return set(data.get("done", []))
    except Exception:
        return set()


def _save_checkpoint(done: set[str]) -> None:
    try:
        _CHECKPOINT_FILE.write_text(
            json.dumps({"done": sorted(done)}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("Could not save checkpoint: %s", exc)


# ---------------------------------------------------------------------------
# Search backends
# ---------------------------------------------------------------------------

def _serpapi_search(query: str, api_key: str, num: int = 10) -> list[str]:
    url = "https://serpapi.com/search"
    params = {"engine": "google", "q": query, "num": num, "api_key": api_key, "gl": "us", "hl": "en"}
    try:
        resp = requests.get(url, params=params, timeout=20, headers={"User-Agent": _UA})
        resp.raise_for_status()
        return [r.get("link", "") for r in (resp.json().get("organic_results") or []) if r.get("link")]
    except Exception as exc:
        log.warning("SerpAPI error for %r: %s", query, exc)
        return []


def _ddg_search(query: str, num: int = 10) -> list[str]:
    if not _HAS_DDGS:
        log.warning("ddgs not installed. Run: pip install ddgs  OR set ATLAS_SERPAPI_KEY.")
        return []
    try:
        results = list(_DDGS().text(query, max_results=num))
        return [r.get("href", "") for r in results if r.get("href")]
    except Exception as exc:
        log.warning("DDG search error for %r: %s", query, exc)
        return []


def _search(query: str, serpapi_key: str | None, num: int = 10) -> list[str]:
    if serpapi_key:
        return _serpapi_search(query, serpapi_key, num=num)
    return _ddg_search(query, num=num)


# ---------------------------------------------------------------------------
# Slug extraction
# ---------------------------------------------------------------------------

def _extract_slug(url: str, pattern: str) -> str | None:
    m = re.search(pattern, url, re.IGNORECASE)
    if not m:
        return None
    slug = m.group(1).strip("/").split("/")[0].split("?")[0].strip()
    if not slug or len(slug) < 2 or slug.isdigit():
        return None
    return slug


# ---------------------------------------------------------------------------
# Board validation
# ---------------------------------------------------------------------------

def _validate_greenhouse(slug: str) -> tuple[bool, str]:
    for base in (
        "https://boards.greenhouse.io",
        "https://job-boards.greenhouse.io",
        "https://boards.eu.greenhouse.io",
    ):
        url = f"{base}/{slug}"
        try:
            r = requests.get(url, headers=_HEADERS, timeout=_VALIDATE_TIMEOUT, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 500:
                return True, url
        except Exception:
            pass
    return False, ""


def _validate_lever(slug: str) -> tuple[bool, str]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_VALIDATE_TIMEOUT)
        if r.status_code == 200 and isinstance(r.json(), list):
            return True, f"https://jobs.lever.co/{slug}"
    except Exception:
        pass
    return False, ""


def _validate_ashby(slug: str) -> tuple[bool, str]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_VALIDATE_TIMEOUT)
        if r.status_code == 200 and isinstance(r.json(), dict) and "jobs" in r.json():
            return True, f"https://jobs.ashbyhq.com/{slug}"
    except Exception:
        pass
    return False, ""


def _validate(ats_type: str, slug: str) -> tuple[bool, str]:
    if ats_type == "greenhouse":
        return _validate_greenhouse(slug)
    if ats_type == "lever":
        return _validate_lever(slug)
    if ats_type == "ashby":
        return _validate_ashby(slug)
    return False, ""


def _company_name_from_slug(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def _dedup_key(ats_type: str, board_url: str, slug: str) -> str:
    s = slug.strip().lower() if slug.strip() else urlparse(board_url).path.strip("/").split("/")[0].lower()
    return f"{ats_type}::{s}"


def _load_existing_keys(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    try:
        rows = load_sources(csv_path)
    except Exception:
        return set()
    return {_dedup_key(r.ats_type, r.ats_board_url, r.ats_slug) for r in rows}


# ---------------------------------------------------------------------------
# Main discovery
# ---------------------------------------------------------------------------

def run_discovery(
    output_csv: Path,
    serpapi_key: str | None = None,
    max_searches: int = 99999,
    dry_run: bool = False,
) -> dict[str, int]:
    """Discover new ATS boards and append to output_csv.

    Uses a checkpoint file to skip already-attempted queries — safe to
    interrupt and resume. Returns stats dict.
    """
    existing_keys = _load_existing_keys(output_csv)
    log.info("Loaded %d existing board slugs from %s", len(existing_keys), output_csv)

    checkpoint = _load_checkpoint()
    log.info("Checkpoint: %d searches already done this session", len(checkpoint))

    # Build full search plan: every target × every keyword
    all_searches: list[tuple[str, str, str, str, str]] = []
    for kw in _INDUSTRY_KEYWORDS:
        for tgt in _ATS_TARGETS:
            ck = f"{tgt['site']}::{kw}"
            all_searches.append((ck, f'{tgt["site"]} "{kw}"', tgt["ats_type"], tgt["board_url_tpl"], tgt["slug_re"]))

    # Exclude already-done, respect max_searches
    pending = [s for s in all_searches if s[0] not in checkpoint]
    log.info(
        "Search plan: %d total combinations, %d pending (max_searches=%d)",
        len(all_searches), len(pending), max_searches,
    )

    stats = {"searched": 0, "candidates": 0, "validated": 0, "added": 0, "skipped_checkpoint": len(all_searches) - len(pending)}
    candidates: dict[str, tuple[str, str, str]] = {}

    for i, (ck, query, ats_type, board_url_tpl, slug_re) in enumerate(pending):
        if stats["searched"] >= max_searches:
            log.info("Reached max_searches=%d — stopping.", max_searches)
            break

        stats["searched"] += 1
        log.info("[%d/%d] %s", stats["searched"], min(max_searches, len(pending)), query)

        urls = _search(query, serpapi_key)
        new_this_query = 0
        for url in urls:
            slug = _extract_slug(url, slug_re)
            if not slug:
                continue
            key = _dedup_key(ats_type, board_url_tpl.format(slug=slug), slug)
            if key in existing_keys or key in candidates:
                continue
            candidates[key] = (ats_type, slug, board_url_tpl.format(slug=slug))
            stats["candidates"] += 1
            new_this_query += 1

        checkpoint.add(ck)

        # Save checkpoint every 10 searches so interruptions lose minimal progress
        if stats["searched"] % 10 == 0:
            _save_checkpoint(checkpoint)
            log.info(
                "  → checkpoint saved. total candidates so far: %d",
                stats["candidates"],
            )

        gap = random.uniform(_SEARCH_GAP_MIN, _SEARCH_GAP_MAX)
        time.sleep(gap)

    _save_checkpoint(checkpoint)
    log.info("Search phase done. %d new board candidates to validate.", len(candidates))

    # Validate and collect new rows — write in batches so progress persists
    new_rows: list[SourceRow] = []
    for j, (key, (ats_type, slug, board_url)) in enumerate(candidates.items(), 1):
        ok, validated_url = _validate(ats_type, slug)
        time.sleep(random.uniform(0.3, 0.8))

        if not ok:
            log.debug("  ✗ %s / %s — not live", ats_type, slug)
            continue

        stats["validated"] += 1
        new_rows.append(SourceRow(
            company_name=_company_name_from_slug(slug),
            source="auto_discovery",
            ats_type=ats_type,
            ats_board_url=validated_url,
            ats_slug=slug,
            resolution_type=f"ats_{ats_type}",
            notes="auto_discovered",
        ))
        log.info("  ✓ %-12s %-45s %s", ats_type, slug, new_rows[-1].company_name)

        # Write every 25 validated boards so progress isn't lost on interruption
        if not dry_run and len(new_rows) % 25 == 0:
            _append_to_csv(output_csv, new_rows[-25:])
            log.info("  → flushed 25 rows to CSV (total validated: %d)", stats["validated"])

    stats["added"] = len(new_rows)
    log.info(
        "Discovery complete: searched=%d  candidates=%d  validated=%d  adding=%d",
        stats["searched"], stats["candidates"], stats["validated"], stats["added"],
    )

    if dry_run:
        log.info("DRY RUN — not writing to CSV.")
        for r in new_rows:
            print(f"  {r.ats_type:<12} {r.ats_slug:<45} {r.company_name}")
        return stats

    # Write remaining rows (those not already flushed in batches above)
    already_flushed = (stats["validated"] // 25) * 25
    remainder = new_rows[already_flushed:]
    if remainder:
        _append_to_csv(output_csv, remainder)

    if new_rows:
        log.info("Total: appended %d new boards to %s", len(new_rows), output_csv)
    else:
        log.info("No new boards found.")

    return stats


def _append_to_csv(output_csv: Path, rows: list[SourceRow]) -> None:
    if not rows:
        return
    write_header = not output_csv.exists() or output_csv.stat().st_size == 0
    with output_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _resolve_output_csv() -> Path:
    s = get_settings()
    if getattr(s, "company_sources_csv", None):
        candidate = Path(s.company_sources_csv)
        if candidate.is_absolute():
            return candidate
        return Path(__file__).resolve().parent.parent / candidate
    return Path(__file__).resolve().parent / "company_ats_sources.csv"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discover and append new ATS boards to the company CSV.")
    parser.add_argument(
        "--max-searches", type=int, default=99999,
        help="Max search queries to fire this run (default: unlimited)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Discover and validate but do not write to CSV.",
    )
    parser.add_argument(
        "--ats-types", nargs="+", choices=["greenhouse", "lever", "ashby"],
        help="Limit to specific ATS types.",
    )
    parser.add_argument(
        "--reset-checkpoint", action="store_true",
        help="Delete the checkpoint file and start fresh.",
    )

    args = parser.parse_args()

    if args.reset_checkpoint:
        if _CHECKPOINT_FILE.exists():
            _CHECKPOINT_FILE.unlink()
            print(f"Checkpoint deleted: {_CHECKPOINT_FILE}")
        else:
            print("No checkpoint file found.")
        sys.exit(0)

    if args.ats_types:
        _ATS_TARGETS[:] = [t for t in _ATS_TARGETS if t["ats_type"] in args.ats_types]

    s = get_settings()
    serpapi_key = getattr(s, "serpapi_key", None) or os.environ.get("ATLAS_SERPAPI_KEY")
    if not serpapi_key:
        log.info("No ATLAS_SERPAPI_KEY — using DuckDuckGo (free). Set key for higher volume.")

    output_csv = _resolve_output_csv()
    log.info("Output CSV: %s", output_csv)

    run_discovery(
        output_csv=output_csv,
        serpapi_key=serpapi_key,
        max_searches=args.max_searches,
        dry_run=args.dry_run,
    )
