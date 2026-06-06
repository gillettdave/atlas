"""Digest delivery — CSV export, Slack webhook, email (SMTP).

Scope for v1:
- Pure formatting functions that take a persisted Digest + its items
  (joined to Jobs) and render CSV / Markdown-for-Slack / HTML-for-email.
- Thin senders that push through Slack's webhook URL or an SMTP server.
- Every send writes a `pipeline_events` row (entity_type=digest,
  event_name=digest_delivered, details={channel, recipient, ok, ...}).

Config lives in env vars:
- ATLAS_SLACK_WEBHOOK_URL          fallback webhook if none supplied on call
- ATLAS_SMTP_HOST                  required for email send
- ATLAS_SMTP_PORT                  default 587
- ATLAS_SMTP_USERNAME / _PASSWORD  auth if host requires it
- ATLAS_SMTP_FROM                  From: address
- ATLAS_SMTP_USE_TLS               'true' (default) enables STARTTLS

This file is intentionally dependency-light: `requests` for Slack,
stdlib `smtplib` / `email` for mail. No Slack SDK, no Jinja.
"""
from __future__ import annotations

import csv
import io
import os
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Iterable, Optional

import requests
from sqlalchemy.orm import Session

from ..models.digest import Digest
from ..models.digest_item import DigestItem
from ..models.job import Job
from ..models.pipeline_event import PipelineEvent
from . import digest_builder


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DeliveryResult:
    channel: str
    recipient: str
    ok: bool
    sent_at: datetime
    item_count: int
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Fetch helper
# ---------------------------------------------------------------------------

def _load_digest(
    db: Session, digest_id: uuid.UUID
) -> tuple[Digest, list[tuple[DigestItem, Job]]]:
    result = digest_builder.get_digest_with_items(db, digest_id)
    if result is None:
        raise ValueError(f"digest {digest_id} not found")
    return result


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_FIELDS: tuple[str, ...] = (
    "rank",
    "lane",
    "company",
    "title",
    "location",
    "remote_type",
    "employment_type",
    "ranking_score",
    "quality_score",
    "reason",
    "provider",
    "apply_url",
    "first_seen_at",
    "last_seen_at",
)


def render_csv(
    digest: Digest, rows: Iterable[tuple[DigestItem, Job]]
) -> bytes:
    """Flat CSV of every digest item, both lanes interleaved."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for item, job in sorted(
        rows, key=lambda pair: (pair[0].lane, pair[0].rank_position)
    ):
        writer.writerow(
            {
                "rank": item.rank_position,
                "lane": item.lane,
                "company": job.company_name,
                "title": job.title,
                "location": job.location or "",
                "remote_type": job.remote_type or "",
                "employment_type": job.employment_type or "",
                "ranking_score": float(job.ranking_score or 0),
                "quality_score": float(job.quality_score or 0),
                "reason": item.reason or "",
                "provider": job.provider,
                "apply_url": job.apply_url,
                "first_seen_at": job.first_seen_at.isoformat(),
                "last_seen_at": job.last_seen_at.isoformat(),
            }
        )
    return buf.getvalue().encode("utf-8")


def csv_filename(digest: Digest) -> str:
    ts = digest.generated_at.strftime("%Y%m%d-%H%M%S")
    return f"atlas-digest-{digest.digest_type}-{ts}.csv"


# ---------------------------------------------------------------------------
# Slack (mrkdwn over incoming webhook)
# ---------------------------------------------------------------------------

def _lane_label(lane: str) -> str:
    return {"fresh": "Fresh", "hidden_gem": "Hidden gems"}.get(lane, lane)


def render_slack_blocks(
    digest: Digest,
    rows: list[tuple[DigestItem, Job]],
    *,
    include_hidden_gems: bool = True,
    max_items_per_lane: int = 15,
) -> dict:
    """Build a Slack `blocks` payload.

    Falls back to a plain-text `text` field so webhooks that don't render
    blocks still show something useful.
    """
    by_lane: dict[str, list[tuple[DigestItem, Job]]] = {"fresh": [], "hidden_gem": []}
    for item, job in rows:
        by_lane.setdefault(item.lane, []).append((item, job))
    for lane in by_lane:
        by_lane[lane].sort(key=lambda p: p[0].rank_position)

    header_text = (
        f"Atlas digest - {digest.digest_type} - "
        f"{digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
    ]

    def _add_lane(lane_key: str) -> None:
        entries = by_lane.get(lane_key) or []
        if not entries:
            return
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{_lane_label(lane_key)}* ({len(entries)})",
                },
            }
        )
        for item, job in entries[:max_items_per_lane]:
            score = float(job.ranking_score or 0)
            bits = [f"*{job.company_name}* - <{job.apply_url}|{job.title}>"]
            facts: list[str] = [f"score {score:.1f}"]
            if job.remote_type:
                facts.append(job.remote_type)
            if job.location:
                facts.append(job.location)
            bits.append(" · ".join(facts))
            if item.reason:
                bits.append(f"_{item.reason}_")
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(bits)},
                }
            )
        if len(entries) > max_items_per_lane:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"...+{len(entries) - max_items_per_lane} more in this lane",
                        }
                    ],
                }
            )
        blocks.append({"type": "divider"})

    _add_lane("fresh")
    if include_hidden_gems:
        _add_lane("hidden_gem")

    # Fallback text (used by clients that don't support blocks)
    plain_lines = [header_text]
    for lane in ("fresh", "hidden_gem") if include_hidden_gems else ("fresh",):
        entries = by_lane.get(lane) or []
        if not entries:
            continue
        plain_lines.append(f"-- {_lane_label(lane)} ({len(entries)}) --")
        for item, job in entries[:max_items_per_lane]:
            score = float(job.ranking_score or 0)
            plain_lines.append(
                f"[{score:.1f}] {job.company_name} - {job.title} - {job.apply_url}"
            )

    return {"text": "\n".join(plain_lines), "blocks": blocks}


def send_slack(
    digest: Digest,
    rows: list[tuple[DigestItem, Job]],
    *,
    webhook_url: Optional[str] = None,
    include_hidden_gems: bool = True,
    timeout: float = 10.0,
) -> DeliveryResult:
    url = webhook_url or os.environ.get("ATLAS_SLACK_WEBHOOK_URL")
    if not url:
        return DeliveryResult(
            channel="slack",
            recipient="",
            ok=False,
            sent_at=datetime.now(timezone.utc),
            item_count=len(rows),
            detail="no webhook url supplied and ATLAS_SLACK_WEBHOOK_URL is unset",
        )

    payload = render_slack_blocks(
        digest, rows, include_hidden_gems=include_hidden_gems
    )
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        ok = 200 <= resp.status_code < 300
        detail = None if ok else f"{resp.status_code}: {resp.text[:400]}"
    except requests.RequestException as e:
        ok = False
        detail = f"network error: {e}"

    # Redact the webhook URL when recording.
    recipient_label = f"slack:{url.rsplit('/', 1)[-1][:8]}..."
    return DeliveryResult(
        channel="slack",
        recipient=recipient_label,
        ok=ok,
        sent_at=datetime.now(timezone.utc),
        item_count=len(rows),
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Email (SMTP)
# ---------------------------------------------------------------------------

@dataclass
class SmtpConfig:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    from_addr: str
    use_tls: bool

    @classmethod
    def from_env(cls) -> Optional["SmtpConfig"]:
        host = os.environ.get("ATLAS_SMTP_HOST")
        from_addr = os.environ.get("ATLAS_SMTP_FROM")
        if not (host and from_addr):
            return None
        return cls(
            host=host,
            port=int(os.environ.get("ATLAS_SMTP_PORT", "587")),
            username=os.environ.get("ATLAS_SMTP_USERNAME"),
            password=os.environ.get("ATLAS_SMTP_PASSWORD"),
            from_addr=from_addr,
            use_tls=os.environ.get("ATLAS_SMTP_USE_TLS", "true").lower()
            in {"1", "true", "yes"},
        )


def render_email_subject(digest: Digest) -> str:
    when = digest.generated_at.strftime("%Y-%m-%d")
    return f"[Atlas] {digest.digest_type} digest - {when}"


def _job_row_html(job: Job, item: DigestItem) -> str:
    score = float(job.ranking_score or 0)
    loc = job.location or "-"
    remote = job.remote_type or "-"
    reason = item.reason or ""
    return (
        "<tr>"
        f"<td style='padding:4px 8px;'>{item.rank_position}</td>"
        f"<td style='padding:4px 8px;font-weight:600'>{_esc(job.company_name)}</td>"
        f"<td style='padding:4px 8px;'><a href='{_esc(job.apply_url)}'>"
        f"{_esc(job.title)}</a></td>"
        f"<td style='padding:4px 8px;'>{score:.1f}</td>"
        f"<td style='padding:4px 8px;'>{_esc(remote)}</td>"
        f"<td style='padding:4px 8px;'>{_esc(loc)}</td>"
        f"<td style='padding:4px 8px;color:#666;font-size:12px'>{_esc(reason)}</td>"
        "</tr>"
    )


def _esc(s: Optional[str]) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_email_bodies(
    digest: Digest,
    rows: list[tuple[DigestItem, Job]],
    *,
    include_hidden_gems: bool = True,
) -> tuple[str, str]:
    """Return (plain_text, html) bodies."""
    by_lane: dict[str, list[tuple[DigestItem, Job]]] = {"fresh": [], "hidden_gem": []}
    for item, job in rows:
        by_lane.setdefault(item.lane, []).append((item, job))
    for lane in by_lane:
        by_lane[lane].sort(key=lambda p: p[0].rank_position)

    # Plain text
    text_lines = [
        f"Atlas digest ({digest.digest_type}) - "
        f"{digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    lanes = ["fresh", "hidden_gem"] if include_hidden_gems else ["fresh"]
    for lane in lanes:
        entries = by_lane.get(lane) or []
        if not entries:
            continue
        text_lines.append(f"-- {_lane_label(lane)} ({len(entries)}) --")
        for item, job in entries:
            score = float(job.ranking_score or 0)
            text_lines.append(
                f"  [{score:.1f}] {job.company_name} - {job.title}"
            )
            text_lines.append(f"        {job.apply_url}")
            if item.reason:
                text_lines.append(f"        ({item.reason})")
        text_lines.append("")
    text_body = "\n".join(text_lines)

    # HTML
    html_parts = [
        "<html><body style=\"font-family:system-ui,-apple-system,Segoe UI,sans-serif;\">",
        f"<h2>Atlas digest - {_esc(digest.digest_type)}</h2>",
        f"<p style='color:#666'>{digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')}</p>",
    ]
    for lane in lanes:
        entries = by_lane.get(lane) or []
        if not entries:
            continue
        html_parts.append(f"<h3>{_esc(_lane_label(lane))} ({len(entries)})</h3>")
        html_parts.append(
            "<table style='border-collapse:collapse;width:100%;font-size:14px;'>"
            "<thead><tr style='background:#f2f2f2;text-align:left'>"
            "<th style='padding:4px 8px;'>#</th>"
            "<th style='padding:4px 8px;'>Company</th>"
            "<th style='padding:4px 8px;'>Title</th>"
            "<th style='padding:4px 8px;'>Score</th>"
            "<th style='padding:4px 8px;'>Remote</th>"
            "<th style='padding:4px 8px;'>Location</th>"
            "<th style='padding:4px 8px;'>Reason</th>"
            "</tr></thead><tbody>"
        )
        for item, job in entries:
            html_parts.append(_job_row_html(job, item))
        html_parts.append("</tbody></table>")
    html_parts.append("</body></html>")
    html_body = "".join(html_parts)

    return text_body, html_body


def send_email(
    digest: Digest,
    rows: list[tuple[DigestItem, Job]],
    *,
    recipients: list[str],
    smtp: Optional[SmtpConfig] = None,
    include_hidden_gems: bool = True,
) -> DeliveryResult:
    cfg = smtp or SmtpConfig.from_env()
    if cfg is None:
        return DeliveryResult(
            channel="email",
            recipient=",".join(recipients),
            ok=False,
            sent_at=datetime.now(timezone.utc),
            item_count=len(rows),
            detail="ATLAS_SMTP_HOST / ATLAS_SMTP_FROM not configured",
        )
    if not recipients:
        return DeliveryResult(
            channel="email",
            recipient="",
            ok=False,
            sent_at=datetime.now(timezone.utc),
            item_count=len(rows),
            detail="no recipients supplied",
        )

    text_body, html_body = render_email_bodies(
        digest, rows, include_hidden_gems=include_hidden_gems
    )
    msg = EmailMessage()
    msg["Subject"] = render_email_subject(digest)
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    try:
        if cfg.use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as s:
                s.ehlo()
                s.starttls(context=context)
                s.ehlo()
                if cfg.username and cfg.password:
                    s.login(cfg.username, cfg.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as s:
                if cfg.username and cfg.password:
                    s.login(cfg.username, cfg.password)
                s.send_message(msg)
        ok = True
        detail = None
    except (smtplib.SMTPException, OSError) as e:
        ok = False
        detail = f"{type(e).__name__}: {e}"[:500]

    return DeliveryResult(
        channel="email",
        recipient=",".join(recipients),
        ok=ok,
        sent_at=datetime.now(timezone.utc),
        item_count=len(rows),
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Top-level driver + audit
# ---------------------------------------------------------------------------

def deliver(
    db: Session,
    digest_id: uuid.UUID,
    *,
    channel: str,
    webhook_url: Optional[str] = None,
    recipients: Optional[list[str]] = None,
    include_hidden_gems: bool = True,
) -> DeliveryResult:
    """Send a persisted digest to a channel. Always writes a pipeline event."""
    digest, rows = _load_digest(db, digest_id)

    ch = channel.lower().strip()
    if ch == "slack":
        result = send_slack(
            digest, rows,
            webhook_url=webhook_url,
            include_hidden_gems=include_hidden_gems,
        )
    elif ch == "email":
        result = send_email(
            digest, rows,
            recipients=recipients or [],
            include_hidden_gems=include_hidden_gems,
        )
    else:
        result = DeliveryResult(
            channel=ch,
            recipient="",
            ok=False,
            sent_at=datetime.now(timezone.utc),
            item_count=len(rows),
            detail=f"unknown channel {channel!r}",
        )

    db.add(
        PipelineEvent(
            entity_type="digest",
            entity_id=digest.id,
            event_name="digest_delivered",
            details={
                "channel": result.channel,
                "recipient": result.recipient,
                "ok": result.ok,
                "item_count": result.item_count,
                "include_hidden_gems": include_hidden_gems,
                "detail": result.detail,
            },
        )
    )
    db.commit()
    return result


def export_csv(db: Session, digest_id: uuid.UUID) -> tuple[bytes, str]:
    """Return (csv_bytes, filename). Audited as a delivery event too."""
    digest, rows = _load_digest(db, digest_id)
    data = render_csv(digest, rows)
    filename = csv_filename(digest)
    db.add(
        PipelineEvent(
            entity_type="digest",
            entity_id=digest.id,
            event_name="digest_delivered",
            details={
                "channel": "csv",
                "recipient": filename,
                "ok": True,
                "item_count": len(rows),
            },
        )
    )
    db.commit()
    return data, filename
