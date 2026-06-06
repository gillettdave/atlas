"""Gmail IMAP email intake — ports Jobr flow onto Atlas manual ingestion."""
from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.email_sync import EmailSyncEvent, EmailSyncSource
from ..models.job import Job
from ..services import manual_job_url as manual_job_svc
from ..services.url_canonicalize import canonicalize_url as canon_url

URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
}
JOB_URL_HINTS = (
    "/jobs",
    "/careers",
    "/positions",
    "/openings",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
)

NON_JOB_HINTS = (
    "unsubscribe",
    "linkedin.com/pulse",
)


def upsert_email_source(
    db: Session,
    *,
    user_id,
    provider: str,
    label_name: str,
    source_name: str | None,
    enabled: bool,
    cadence_minutes: int,
) -> EmailSyncSource:
    p = provider.strip().lower()
    ln = label_name.strip()
    existing = db.scalar(
        select(EmailSyncSource).where(
            EmailSyncSource.user_id == user_id,
            EmailSyncSource.provider == p,
            EmailSyncSource.label_name == ln,
        )
    )
    cadence_value = max(5, min(24 * 60, cadence_minutes))
    now = datetime.now(timezone.utc)
    if not existing:
        row = EmailSyncSource(
            user_id=user_id,
            provider=p,
            label_name=ln,
            source_name=(source_name or "").strip()[:256] or None,
            enabled=enabled,
            cadence_minutes=cadence_value,
            next_sync_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    existing.source_name = ((source_name or "").strip()[:256]) or existing.source_name
    existing.enabled = enabled
    existing.cadence_minutes = cadence_value
    if existing.next_sync_at is None:
        existing.next_sync_at = now
    db.commit()
    db.refresh(existing)
    return existing


def list_email_sources(db: Session, *, user_id, limit: int = 100) -> list[EmailSyncSource]:
    return list(
        db.scalars(
            select(EmailSyncSource)
            .where(EmailSyncSource.user_id == user_id)
            .order_by(EmailSyncSource.created_at.desc())
            .limit(limit)
        ).all()
    )


def list_email_events(
    db: Session,
    *,
    user_id,
    source_id: object | None = None,
    limit: int = 200,
) -> list[EmailSyncEvent]:
    stmt = (
        select(EmailSyncEvent)
        .join(EmailSyncSource, EmailSyncSource.id == EmailSyncEvent.email_sync_source_id)
        .where(EmailSyncSource.user_id == user_id)
        .order_by(EmailSyncEvent.created_at.desc())
        .limit(limit)
    )
    if source_id is not None:
        stmt = stmt.where(EmailSyncEvent.email_sync_source_id == source_id)
    return list(db.scalars(stmt).all())


def list_due_email_source_ids(db: Session, *, user_id, limit: int = 20) -> list:
    now = datetime.now(timezone.utc)
    return [
        row.id
        for row in db.scalars(
            select(EmailSyncSource)
            .where(
                EmailSyncSource.user_id == user_id,
                EmailSyncSource.enabled.is_(True),
                (EmailSyncSource.next_sync_at.is_(None))
                | (EmailSyncSource.next_sync_at <= now),
            )
            .order_by(EmailSyncSource.created_at.asc())
            .limit(limit)
        ).all()
    ]


def _extract_text_from_message(message_obj: email.message.Message) -> str:
    if message_obj.is_multipart():
        parts: list[str] = []
        for part in message_obj.walk():
            ctype = part.get_content_type()
            if ctype not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="ignore"))
        return "\n".join(parts)
    payload = message_obj.get_payload(decode=True) or b""
    charset = message_obj.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="ignore")


def _msg_id(message_obj: email.message.Message) -> str:
    mid = (message_obj.get("Message-ID") or "").strip()
    if mid:
        return mid[:500]
    subj = (message_obj.get("Subject") or "").strip()[:120]
    dv = (message_obj.get("Date") or "").strip()[:120]
    return f"{subj}|{dv}"[:500]


def _normalize_url(raw_url: str) -> str:
    cleaned = raw_url.strip().rstrip(").,;")
    parts = urlsplit(cleaned)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    query_items = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def _score_url(url: str) -> int:
    low = url.lower()
    score = 0
    if any(h in low for h in JOB_URL_HINTS):
        score += 8
    if any(h in low for h in NON_JOB_HINTS):
        score -= 4
    if low.count("/") > 4:
        score += 1
    return score


def _pick_job_url(raw_text: str) -> str | None:
    cands = [_normalize_url(m) for m in URL_PATTERN.findall(raw_text or "")]
    seen: set[str] = set()
    deduped: list[str] = []
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        deduped.append(c)
    if not deduped:
        return None
    ranked = sorted(deduped, key=_score_url, reverse=True)
    top = ranked[0]
    return top if _score_url(top) > 0 else None


def dup_job_exists(db: Session, *, url: str | None, subject: str) -> tuple[bool, str]:
    if url:
        c = canon_url(url) or url
        jid = db.scalar(select(Job.id).where(Job.canonical_apply_url == c).limit(1))
        if jid:
            return True, f"dup_canonical_job_{jid}"
    return False, ""


def _fetch_imap(label_name: str) -> list[email.message.Message]:
    s = get_settings()
    user = getattr(s, "gmail_imap_username", None) or ""
    pwd = getattr(s, "gmail_imap_password", None) or ""
    host = getattr(s, "gmail_imap_host", None) or "imap.gmail.com"
    port = int(getattr(s, "gmail_imap_port", None) or 993)
    if not str(user).strip() or not str(pwd).strip():
        raise RuntimeError(
            "Gmail IMAP not configured (set ATLAS_GMAIL_IMAP_USERNAME and ATLAS_GMAIL_IMAP_PASSWORD)."
        )
    client = imaplib.IMAP4_SSL(host.strip(), port)
    try:
        client.login(user.strip(), pwd.strip())
        status, _ = client.select(f'"{label_name}"')
        if status != "OK":
            raise RuntimeError(f"Unable to select label: {label_name}")
        status, data = client.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Failed to search unread emails.")
        messages: list[email.message.Message] = []
        ids = data[0].split()[-50:] if data and data[0] else []
        for mid in ids:
            f_status, msg_data = client.fetch(mid, "(RFC822)")
            if f_status != "OK" or not msg_data:
                continue
            raw = msg_data[0][1]
            if not raw:
                continue
            messages.append(email.message_from_bytes(raw))
            client.store(mid, "+FLAGS", "\\Seen")
        return messages
    finally:
        try:
            client.close()
        except Exception:
            pass
        client.logout()


def run_email_sync(db: Session, *, source_id, user_id) -> dict:
    src = db.get(EmailSyncSource, source_id)
    if src is None or src.user_id != user_id:
        return {"synced_count": 0, "created_jobs": 0}
    synced_count = 0
    created = 0
    now = datetime.now(timezone.utc)
    src.last_error = None
    try:
        if src.provider != "gmail_imap":
            raise RuntimeError(f"unsupported provider {src.provider!r}")
        messages = _fetch_imap(src.label_name)
        for mobj in messages:
            pmid = _msg_id(mobj)
            dup_ev = db.scalar(
                select(EmailSyncEvent).where(
                    EmailSyncEvent.email_sync_source_id == src.id,
                    EmailSyncEvent.provider_message_id == pmid,
                )
            )
            if dup_ev:
                continue
            text = _extract_text_from_message(mobj)
            subj = (mobj.get("Subject") or "").strip()
            url = _pick_job_url(text)
            is_dup, reason = dup_job_exists(db, url=url, subject=subj)
            if is_dup:
                db.add(
                    EmailSyncEvent(
                        email_sync_source_id=src.id,
                        provider_message_id=pmid,
                        status="duplicate_skipped",
                        detail=reason,
                    )
                )
                db.commit()
                continue

            preamble = f"Email Subject: {subj}\n\n{text[:16000]}".strip()
            if url:
                ing = manual_job_svc.ingest_manual_job_url(
                    db,
                    page_url=url,
                    tenant_user_id=user_id,
                    then_process=True,
                    then_rescore=False,
                )
                jid = ing.job_id
            else:
                ing = manual_job_svc.ingest_pasted_manual_job(
                    db,
                    manual_text=preamble,
                    source_label=(src.source_name or f"gmail:{src.label_name}")[:120],
                    tenant_user_id=user_id,
                    then_process=True,
                    then_rescore=False,
                )
                jid = ing.job_id
            created += 1
            synced_count += 1
            db.add(
                EmailSyncEvent(
                    email_sync_source_id=src.id,
                    provider_message_id=pmid,
                    status="synced",
                    detail=f"job_id={jid}; url={'yes' if url else 'no'}",
                    canonical_job_id=jid,
                )
            )
            db.commit()
        src.last_synced_at = now
        src.next_sync_at = now + timedelta(minutes=max(5, src.cadence_minutes or 60))
        db.commit()
    except Exception as exc:
        src.last_error = str(exc)[:500]
        src.last_synced_at = now
        src.next_sync_at = now + timedelta(minutes=max(5, src.cadence_minutes or 60))
        db.commit()
        db.add(
            EmailSyncEvent(
                email_sync_source_id=src.id,
                provider_message_id=None,
                status="error",
                detail=src.last_error,
            )
        )
        db.commit()
    return {"synced_count": synced_count, "created_jobs": created}
