"""Fetch a manual job posting URL and ingest through the canonical pipeline."""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone as tz
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collectors.http_utils import http_get
from ..models.ingestion_run import IngestionRun
from ..models.ingestion_source import IngestionSource
from ..models.pipeline_event import PipelineEvent
from ..models.raw_job_event import RawJobEvent
from ..services.url_canonicalize import canonicalize_url as canon_url
from . import importer, profiles as profiles_svc
from . import ranker

PROVIDER_MANUAL = "manual_job_page"


def _meta_content(soup: Any, prop: str) -> Optional[str]:
    tag = soup.find("meta", property=prop)
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    if prop == "description":
        tag = soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return None


def _title_tag_text(soup: Any) -> Optional[str]:
    t = soup.find("title")
    if t and t.string:
        s = str(t.string).strip()
        if s:
            return s
    return None


def _strip_noise(title: str) -> str:
    for noise in ("| LinkedIn", "| Indeed", "| Greenhouse", "| Workable"):
        idx = title.find(noise)
        if idx != -1:
            title = title[:idx].strip()
    return title


def _guess_company_from_title(title: str) -> Optional[str]:
    t = title.strip()
    sep_match = re.split(r"\s+[—–\-|]+\s+", t)
    if len(sep_match) >= 2:
        return sep_match[-1].strip()
    tail = re.findall(r"(?: at | @ )(.+)", t, flags=re.IGNORECASE)
    if tail:
        return tail[-1].strip()
    return None


def payload_from_job_page_html(html: str, page_url: str) -> tuple[dict[str, Any], Optional[str]]:
    """Build raw_payload keys matching cleaner_v2. Returns (payload, raw_html optional)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        BeautifulSoup = None  # noqa: N806

    title = ""
    company = ""
    desc = ""
    if BeautifulSoup is not None and html.strip():
        soup = BeautifulSoup(html, "lxml")
        og_title = _meta_content(soup, "og:title") or _meta_content(soup, "twitter:title")
        title_raw = og_title or _title_tag_text(soup) or ""
        title = _strip_noise(title_raw.strip()) if title_raw else ""

        company = (
            _meta_content(soup, "og:site_name")
            or (_meta_content(soup, "application-name"))
            or ""
        )
        if not company:
            company = _guess_company_from_title(title) or ""

        desc = _meta_content(soup, "og:description") or _meta_content(soup, "description") or ""
        if len(desc) < 40:
            article = soup.find("article") or soup.find("main")
            if article:
                cand = article.get_text(" ", strip=True)[:6000]
                if len(cand) > len(desc):
                    desc = cand
    else:
        tail = page_url.strip("/").split("/")
        title = tail[-1].replace("-", " ")[:120] if tail else page_url

    if len(desc) > 28000:
        desc = desc[:28000]

    html_store: Optional[str] = None
    if html and len(html) < 1_250_000:
        html_store = html[:480_000]

    ca = canon_url(page_url) or page_url
    employer = company.strip() if company else _guess_company_from_title(title) or "Employer unknown"
    payload_out: dict[str, Any] = {
        "company_name": employer,
        "job_title": title.strip() or "Untitled posting",
        "job_url": page_url,
        "apply_url": ca,
        "description_clean": desc or None,
    }
    return payload_out, html_store


def synthesize_pasted_manual_payload(manual_text: str) -> dict[str, Any]:
    """Build raw_payload for pasted JD text (no HTTP fetch).

    Uses a synthetic https://atlas.manual/{digest} identity URL so cleaner_v2
    receives company, title, and a canonical apply_url (see ``normalize_raw_event``).
    """
    text = manual_text.strip()
    if not text:
        raise ValueError("manual_text is empty")

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    apply_url = f"https://atlas.manual/{digest}"

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title_line = (lines[0] if lines else "Untitled posting")[:255]

    company_guess = _guess_company_from_title(title_line) or ""
    if not company_guess and len(lines) > 1:
        second = lines[1]
        if len(second) <= 200 and not second.lower().startswith(("http://", "https://")):
            company_guess = second[:256]

    employer = company_guess.strip() if company_guess else "Employer unknown"

    desc = text if len(text) <= 28000 else text[:28000]

    return {
        "company_name": employer,
        "job_title": title_line.strip() or "Untitled posting",
        "job_url": apply_url,
        "apply_url": apply_url,
        "description_clean": desc,
    }


def _job_id_from_pipeline(db: Session, raw_event_id: uuid.UUID) -> Optional[uuid.UUID]:
    details = db.execute(
        select(PipelineEvent.details).where(
            PipelineEvent.entity_type == "raw_job_event",
            PipelineEvent.entity_id == raw_event_id,
            PipelineEvent.event_name.in_(("new_canonical", "matched_existing")),
        ).order_by(PipelineEvent.created_at.desc()).limit(1)
    ).scalar_one_or_none()

    if not isinstance(details, dict):
        return None
    jid = details.get("job_id")
    if jid is None:
        return None
    try:
        return uuid.UUID(str(jid))
    except ValueError:
        return None


@dataclass
class ManualJobUrlResult:
    ingestion_run_id: uuid.UUID
    raw_event_id: uuid.UUID
    fetch_status: str
    parse_status: str | None = None
    job_id: uuid.UUID | None = None


def ingest_manual_job_url(
    db: Session,
    *,
    page_url: str,
    title_override: str | None = None,
    company_override: str | None = None,
    ingest_source_id: uuid.UUID | None = None,
    tenant_user_id: uuid.UUID | None = None,
    then_process: bool = True,
    then_rescore: bool = False,
    profile_slug: str | None = None,
    profile_user_id: uuid.UUID | None = None,
) -> ManualJobUrlResult:
    """Create ingestion_run + raw_job_event; optionally run importer + rescore."""

    url = page_url.strip()
    if ingest_source_id is not None:
        sr = db.get(IngestionSource, ingest_source_id)
        if sr is not None and tenant_user_id is not None and sr.user_id == tenant_user_id:
            sr.last_used_at = datetime.now(tz.utc)

    run = IngestionRun(
        source_name="manual_job_url",
        source_type="manual_url",
        run_metadata={"url": url, "ingestion_source_id": str(ingest_source_id) if ingest_source_id else None},
        status="running",
    )
    db.add(run)
    db.flush()

    resp, fetch_err = http_get(url)
    source_url_eff = url
    payload: dict[str, Any]
    raw_html_store: Optional[str]
    fs = "failed_fetch"

    if resp is not None and getattr(resp, "ok", False) and (resp.text or "").strip():
        source_url_eff = str(resp.url or url)
        payload, raw_html_store = payload_from_job_page_html(resp.text, source_url_eff)
        fs = "fetched"
    else:
        err_txt = fetch_err[:2000] if fetch_err else "HTTP fetch failed"
        payload = {
            "company_name": "Unknown (fetch failed)",
            "job_title": "Posting (page not retrieved)",
            "job_url": url,
            "apply_url": canon_url(url) or url,
            "description_clean": err_txt,
        }
        raw_html_store = None

    if title_override:
        payload["job_title"] = title_override.strip()
    if company_override:
        payload["company_name"] = company_override.strip()

    raw = RawJobEvent(
        ingestion_run_id=run.id,
        provider=PROVIDER_MANUAL,
        source_url=source_url_eff,
        raw_payload=payload,
        raw_html=raw_html_store,
        fetch_status=fs,
        parse_status="pending",
    )
    db.add(raw)
    run.rows_seen = (run.rows_seen or 0) + 1
    run.status = "success"
    run.completed_at = datetime.now(tz.utc)
    db.flush()

    out = ManualJobUrlResult(
        ingestion_run_id=run.id,
        raw_event_id=raw.id,
        fetch_status=raw.fetch_status,
        parse_status=raw.parse_status,
    )

    if then_process:
        importer.process_pending(db, limit=20, ingestion_run_id=run.id)
        db.refresh(raw)
        out.parse_status = raw.parse_status
        out.job_id = _job_id_from_pipeline(db, raw.id)
    else:
        db.commit()
        db.refresh(raw)
        out.parse_status = raw.parse_status

    if then_rescore and then_process and out.job_id is not None:
        profile = profiles_svc.get_effective(db, profile_slug, uid=profile_user_id)
        ranker.rescore_one(db, out.job_id, profile=profile)

    return out


def ingest_pasted_manual_job(
    db: Session,
    *,
    manual_text: str,
    source_label: str | None = None,
    title_override: str | None = None,
    company_override: str | None = None,
    ingest_source_id: uuid.UUID | None = None,
    tenant_user_id: uuid.UUID | None = None,
    then_process: bool = True,
    then_rescore: bool = False,
    profile_slug: str | None = None,
    profile_user_id: uuid.UUID | None = None,
) -> ManualJobUrlResult:
    """Create ingestion_run + raw_job_event from pasted text; optional importer + rescore."""

    if ingest_source_id is not None:
        sr = db.get(IngestionSource, ingest_source_id)
        if sr is not None and tenant_user_id is not None and sr.user_id == tenant_user_id:
            sr.last_used_at = datetime.now(tz.utc)

    label = (source_label or "").strip()
    src_name = (label[:120] if label else "") or "manual_paste"

    payload = synthesize_pasted_manual_payload(manual_text)

    if title_override:
        payload["job_title"] = title_override.strip()
    if company_override:
        payload["company_name"] = company_override.strip()

    run = IngestionRun(
        source_name=src_name,
        source_type="manual_paste",
        run_metadata={
            "kind": "manual_paste",
            "ingestion_source_id": str(ingest_source_id) if ingest_source_id else None,
        },
        status="running",
    )
    db.add(run)
    db.flush()

    raw = RawJobEvent(
        ingestion_run_id=run.id,
        provider=PROVIDER_MANUAL,
        source_url=str(payload["apply_url"]),
        raw_payload=payload,
        raw_html=None,
        fetch_status="manual_paste",
        parse_status="pending",
    )
    db.add(raw)
    run.rows_seen = (run.rows_seen or 0) + 1
    run.status = "success"
    run.completed_at = datetime.now(tz.utc)
    db.flush()

    out = ManualJobUrlResult(
        ingestion_run_id=run.id,
        raw_event_id=raw.id,
        fetch_status=raw.fetch_status,
        parse_status=raw.parse_status,
    )

    if then_process:
        importer.process_pending(db, limit=20, ingestion_run_id=run.id)
        db.refresh(raw)
        out.parse_status = raw.parse_status
        out.job_id = _job_id_from_pipeline(db, raw.id)
    else:
        db.commit()
        db.refresh(raw)
        out.parse_status = raw.parse_status

    if then_rescore and then_process and out.job_id is not None:
        profile = profiles_svc.get_effective(db, profile_slug, uid=profile_user_id)
        ranker.rescore_one(db, out.job_id, profile=profile)

    return out
