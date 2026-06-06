"""Seed-based job discovery — ports Jobr crawler onto ``ingest_manual_job_url``.

Each discovered posting URL is ingested through the canonical Atlas pipeline
(RawJobEvent → importer), not Jobr's SQLite ``jobs`` table.
"""
from __future__ import annotations

import re
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.discovery_event import DiscoveryEvent
from ..models.discovery_seed import DiscoverySeed
from ..models.job import Job
from ..services import manual_job_url as manual_job_svc
from ..services.url_canonicalize import canonicalize_url as canon_url
from ..collectors.http_utils import http_get

ATS_POSTING_PATTERNS: dict[str, re.Pattern[str]] = {
    "lever.co": re.compile(r"^/[^/]+/[0-9a-f-]{36}/?$", re.IGNORECASE),
    "greenhouse.io": re.compile(r"^/[^/]+/jobs/\d+/?$", re.IGNORECASE),
    "ashbyhq.com": re.compile(r"^/[^/]+/[0-9a-f-]{36}/?$", re.IGNORECASE),
}
JOB_PATH_HINTS = ("/jobs", "/careers", "/positions", "/openings", "/job/")


def _norm_domain(d: str) -> str:
    return (d or "").strip().lower()


def _is_allowed_domain(domain: str, include: list[str], exclude: list[str]) -> bool:
    d = _norm_domain(domain)
    if any(d == e or d.endswith(f".{e}") for e in exclude if e):
        return False
    if not include:
        return True
    return any(d == a or d.endswith(f".{a}") for a in include if a)


def looks_like_job_posting_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or "/"
    host = (parsed.hostname or "").lower()
    for host_hint, pattern in ATS_POSTING_PATTERNS.items():
        if host_hint in host:
            return bool(pattern.search(path))
    return any(h in path.lower() for h in JOB_PATH_HINTS)


def extract_links_from_page(url: str) -> tuple[list[str], str]:
    """Return (absolute links, final_url or page url)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        )
    }
    resp, err = http_get(url, headers=headers)
    if resp is None or not getattr(resp, "ok", False) or not (resp.text or "").strip():
        raise RuntimeError(err or "fetch failed")
    final = str(resp.url or url)
    soup = BeautifulSoup(resp.text, "html.parser")
    out: list[str] = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        out.append(urljoin(final, href))
    return out, final


def _log_event(
    db: Session,
    *,
    user_id: uuid.UUID,
    seed_id: uuid.UUID,
    seed_url: str,
    discovered_url: str,
    event_type: str,
    status: str | None,
    detail: str | None,
    canonical_job_id: uuid.UUID | None,
) -> None:
    db.add(
        DiscoveryEvent(
            user_id=user_id,
            discovery_seed_id=seed_id,
            seed_url=seed_url,
            discovered_url=discovered_url,
            event_type=event_type,
            status=status,
            detail=(detail or "")[:8000] if detail else None,
            canonical_job_id=canonical_job_id,
        )
    )
    db.commit()


def run_seed_discovery(
    db: Session,
    *,
    seed_id: uuid.UUID,
    user_id: uuid.UUID,
    profile_slug: str | None = None,
    test_max_pages: int | None = None,
) -> None:
    """Crawl one seed; ingest job-like URLs through ``ingest_manual_job_url``."""
    seed = db.get(DiscoverySeed, seed_id)
    if seed is None or seed.user_id != user_id:
        return
    if seed.status == "running":
        return

    include = [str(x).lower() for x in (seed.include_domains or []) if str(x).strip()]
    exclude = [str(x).lower() for x in (seed.exclude_domains or []) if str(x).strip()]

    seed.status = "running"
    seed.last_error = None
    db.commit()

    max_depth = max(0, min(3, seed.max_depth))
    max_pages = max(1, min(100, seed.max_pages))
    if test_max_pages is not None:
        max_pages = min(max_pages, max(1, min(int(test_max_pages), 50)))

    queue: deque[tuple[str, int]] = deque([(seed.seed_url, 0)])
    visited: set[str] = set()
    processed = 0
    discovered = 0

    seed_domain = _norm_domain(urlparse(seed.seed_url).hostname or "")

    try:
        while queue and processed < max_pages:
            db.refresh(seed)
            if seed.stop_requested in {"pause", "cancel"}:
                _log_event(
                    db,
                    user_id=user_id,
                    seed_id=seed.id,
                    seed_url=seed.seed_url,
                    discovered_url=seed.seed_url,
                    event_type="crawl_error",
                    status="stopped",
                    detail=f"user:{seed.stop_requested}",
                    canonical_job_id=None,
                )
                break

            current_url, depth = queue.popleft()
            if current_url in visited:
                continue
            visited.add(current_url)
            dom = _norm_domain(urlparse(current_url).hostname or "")
            if not _is_allowed_domain(dom, include, exclude):
                continue

            try:
                links, canonical_page = extract_links_from_page(current_url)
                processed += 1
                _log_event(
                    db,
                    user_id=user_id,
                    seed_id=seed.id,
                    seed_url=seed.seed_url,
                    discovered_url=canonical_page,
                    event_type="page_scanned",
                    status="ok",
                    detail=f"depth={depth} links={len(links)}",
                    canonical_job_id=None,
                )
            except Exception as exc:
                _log_event(
                    db,
                    user_id=user_id,
                    seed_id=seed.id,
                    seed_url=seed.seed_url,
                    discovered_url=current_url,
                    event_type="crawl_error",
                    status="error",
                    detail=str(exc)[:500],
                    canonical_job_id=None,
                )
                continue

            for link in links:
                if discovered >= 5000:
                    break
                ldom = _norm_domain(urlparse(link).hostname or "")
                if not _is_allowed_domain(ldom, include, exclude):
                    continue
                if link in visited:
                    continue
                if depth < max_depth:
                    queue.append((link, depth + 1))
                if not looks_like_job_posting_url(link):
                    continue

                dupe = db.scalar(
                    select(Job.id).where(Job.canonical_apply_url == (canon_url(link) or link)).limit(1)
                )
                if dupe:
                    _log_event(
                        db,
                        user_id=user_id,
                        seed_id=seed.id,
                        seed_url=seed.seed_url,
                        discovered_url=link,
                        event_type="listing_candidate",
                        status="duplicate_skipped",
                        detail="canonical_apply_url already exists",
                        canonical_job_id=dupe,
                    )
                    continue

                try:
                    ing = manual_job_svc.ingest_manual_job_url(
                        db,
                        page_url=link,
                        tenant_user_id=user_id,
                        then_process=True,
                        then_rescore=False,
                        profile_slug=profile_slug,
                        profile_user_id=user_id,
                    )
                    jid = ing.job_id
                    st = "ingested" if jid else "pending_importer"
                    _log_event(
                        db,
                        user_id=user_id,
                        seed_id=seed.id,
                        seed_url=seed.seed_url,
                        discovered_url=link,
                        event_type="listing_candidate",
                        status=st,
                        detail=None,
                        canonical_job_id=jid,
                    )
                    discovered += 1
                except Exception as exc:
                    _log_event(
                        db,
                        user_id=user_id,
                        seed_id=seed.id,
                        seed_url=seed.seed_url,
                        discovered_url=link,
                        event_type="listing_candidate",
                        status="ingest_error",
                        detail=str(exc)[:500],
                        canonical_job_id=None,
                    )

        if seed.stop_requested == "pause":
            seed.status = "paused"
        elif seed.stop_requested == "cancel":
            seed.status = "cancelled"
        else:
            seed.status = "completed"
        seed.discovered_count = discovered
        seed.last_run_at = datetime.now(timezone.utc)
        seed.completed_at = datetime.now(timezone.utc)
        if seed.status not in {"cancelled", "paused"}:
            seed.next_run_at = seed.last_run_at + timedelta(hours=max(1, seed.cadence_hours))
        else:
            seed.next_run_at = None
        seed.stop_requested = None
        db.commit()
    except Exception as exc:
        seed.status = "failed"
        seed.last_error = str(exc)[:500]
        seed.last_run_at = datetime.now(timezone.utc)
        seed.next_run_at = seed.last_run_at + timedelta(hours=max(1, seed.cadence_hours))
        seed.completed_at = datetime.now(timezone.utc)
        db.commit()


def create_seeds_from_payload(
    db: Session,
    *,
    user_id: uuid.UUID,
    seed_urls: Iterable[str],
    source_name: str | None,
    cadence_hours: int,
    max_depth: int,
    max_pages: int,
    include_domains: list[str],
    exclude_domains: list[str],
    mode: str,
) -> list[DiscoverySeed]:
    """Create one persisted seed row per URL."""
    mode_v = mode if mode in {"strict", "balanced", "explore"} else "balanced"
    out: list[DiscoverySeed] = []
    now = datetime.now(timezone.utc)
    for su in seed_urls:
        url = str(su).strip()
        if not url.startswith("http"):
            continue
        row = DiscoverySeed(
            user_id=user_id,
            seed_url=url,
            source_name=(source_name or "")[:256] or None,
            status="queued",
            enabled=True,
            cadence_hours=max(1, min(cadence_hours, 336)),
            max_depth=max(0, min(3, max_depth)),
            max_pages=max(1, min(100, max_pages)),
            include_domains=[x.lower().strip() for x in include_domains if x.strip()],
            exclude_domains=[x.lower().strip() for x in exclude_domains if x.strip()],
            discovery_mode=mode_v,
            next_run_at=now,
        )
        db.add(row)
        out.append(row)
    db.commit()
    for r in out:
        db.refresh(r)
    return out


def list_seeds(db: Session, *, user_id: uuid.UUID, limit: int = 50) -> list[DiscoverySeed]:
    return list(
        db.scalars(
            select(DiscoverySeed)
            .where(DiscoverySeed.user_id == user_id)
            .order_by(DiscoverySeed.created_at.desc())
            .limit(limit)
        ).all()
    )


def pause_seed(db: Session, *, user_id: uuid.UUID, seed_id: uuid.UUID) -> DiscoverySeed | None:
    s = db.get(DiscoverySeed, seed_id)
    if s is None or s.user_id != user_id:
        return None
    s.enabled = False
    s.stop_requested = "pause"
    if s.status != "running":
        s.status = "paused"
        s.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return s


def cancel_seed(db: Session, *, user_id: uuid.UUID, seed_id: uuid.UUID) -> DiscoverySeed | None:
    s = db.get(DiscoverySeed, seed_id)
    if s is None or s.user_id != user_id:
        return None
    s.stop_requested = "cancel"
    if s.status != "running":
        s.status = "cancelled"
        s.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return s


def cancel_all_running(db: Session, *, user_id: uuid.UUID) -> dict:
    seeds = list(
        db.scalars(
            select(DiscoverySeed).where(
                DiscoverySeed.user_id == user_id,
                DiscoverySeed.status.in_(["running", "queued"]),
            )
        ).all()
    )
    ri, qi = [], []
    now = datetime.now(timezone.utc)
    for s in seeds:
        s.stop_requested = "cancel"
        if s.status == "running":
            ri.append(str(s.id))
        else:
            s.status = "cancelled"
            s.completed_at = now
            qi.append(str(s.id))
    db.commit()
    return {"running_seed_ids": ri, "queued_seed_ids": qi, "running_count": len(ri), "queued_count": len(qi)}


def list_due_seed_ids(db: Session, *, user_id: uuid.UUID, limit: int = 20) -> list[uuid.UUID]:
    now = datetime.now(timezone.utc)
    seeds = list(
        db.scalars(
            select(DiscoverySeed)
            .where(
                DiscoverySeed.user_id == user_id,
                DiscoverySeed.enabled.is_(True),
                DiscoverySeed.status.notin_(["running", "cancelled"]),
                (DiscoverySeed.next_run_at.is_(None)) | (DiscoverySeed.next_run_at <= now),
            )
            .order_by(DiscoverySeed.created_at.asc())
            .limit(limit)
        ).all()
    )
    return [s.id for s in seeds]


def list_queue_rows(
    db: Session,
    *,
    user_id: uuid.UUID,
    limit: int = 100,
    status_filter: str | None = None,
) -> list[dict]:
    q = (
        select(DiscoveryEvent)
        .where(
            DiscoveryEvent.user_id == user_id,
            DiscoveryEvent.event_type == "listing_candidate",
        )
        .order_by(DiscoveryEvent.created_at.desc())
        .limit(limit)
    )
    rows = list(db.scalars(q).all())
    out: list[dict] = []
    for ev in rows:
        if status_filter and (ev.status or "") != status_filter:
            continue
        out.append(
            {
                "event_id": str(ev.id),
                "discovery_seed_id": str(ev.discovery_seed_id),
                "seed_url": ev.seed_url,
                "discovered_url": ev.discovered_url,
                "status": ev.status,
                "detail": ev.detail,
                "canonical_job_id": str(ev.canonical_job_id) if ev.canonical_job_id else None,
                "created_at": ev.created_at.isoformat(),
            }
        )
    return out
