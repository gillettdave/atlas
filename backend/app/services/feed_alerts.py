"""Optional alerts when a built digest contains high-scoring jobs (W5).

Fires **after** :func:`digest_builder.build_digest` (digest already persisted).
Controlled by ``ATLAS_DIGEST_ALERT_*`` env vars — disabled by default.
Never raises into callers; failures are logged and surfaced in ``DigestAlertSummary``.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from decimal import Decimal
from email.message import EmailMessage
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models.pipeline_event import PipelineEvent
from . import digest_builder
from .digest_delivery import SmtpConfig

logger = logging.getLogger("atlas.feed_alerts")


@dataclass
class DigestAlertSummary:
    """Return value for callers to merge into ``pipeline_events`` / logs."""

    skipped: bool = True
    reason: str = ""
    threshold: Optional[float] = None
    matched: int = 0
    webhook_attempted: bool = False
    webhook_ok: Optional[bool] = None
    email_attempted: bool = False
    email_ok: Optional[bool] = None
    detail: str = ""

    def to_details(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "skipped": self.skipped,
            "reason": self.reason,
            "matched": self.matched,
            "webhook_attempted": self.webhook_attempted,
            "webhook_ok": self.webhook_ok,
            "email_attempted": self.email_attempted,
            "email_ok": self.email_ok,
            "detail": self.detail[:500] if self.detail else "",
        }
        if self.threshold is not None:
            out["threshold"] = self.threshold
        return out


def _parse_recipients(raw: Optional[str]) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _eligible_jobs(
    built: digest_builder.BuiltDigest,
    threshold: Decimal,
    top_k: int,
) -> list[digest_builder.BuiltDigestItem]:
    tol = float(threshold)
    picked: list[digest_builder.BuiltDigestItem] = []
    for it in built.items:
        score = float(it.job.ranking_score or Decimal("0"))
        if score >= tol:
            picked.append(it)
    picked.sort(
        key=lambda x: (
            float(x.job.ranking_score or Decimal("0")),
            x.job.last_seen_at,
        ),
        reverse=True,
    )
    return picked[: max(1, top_k)]


def _plaintext_body(built: digest_builder.BuiltDigest, items: list, source: str) -> str:
    lines = [
        f"[Atlas] Digest alert — digest_id={built.digest.id} ({source})",
        f"type={built.digest.digest_type} · generated {built.digest.generated_at.isoformat()}",
        "",
        "Jobs at/above threshold:",
    ]
    for it in items:
        score = float(it.job.ranking_score or 0)
        lines.append(f"  [{score:.1f}] {it.job.company_name} — {it.job.title}")
        lines.append(f"      {it.job.apply_url}  ({it.lane})")
    return "\n".join(lines)


def maybe_digest_top_jobs_alert(
    db: Session,
    built: digest_builder.BuiltDigest,
    *,
    source: str,
    settings: Optional[Settings] = None,
) -> DigestAlertSummary:
    try:
        return _maybe_digest_top_jobs_alert_impl(
            db, built, source=source, settings=settings
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("digest top-job alert failed unexpectedly")
        out = DigestAlertSummary(
            skipped=True,
            reason="internal_error",
            detail=str(e)[:500],
        )
        return out


def _maybe_digest_top_jobs_alert_impl(
    db: Session,
    built: digest_builder.BuiltDigest,
    *,
    source: str,
    settings: Optional[Settings] = None,
) -> DigestAlertSummary:
    settings = settings or get_settings()

    summary = DigestAlertSummary()

    if not settings.digest_alert_enabled:
        summary.reason = "disabled"
        return summary

    thresh = Decimal(str(settings.digest_alert_min_ranking_score))
    summary.threshold = float(thresh)

    url = (settings.digest_alert_webhook_url or "").strip()
    recipients = _parse_recipients(settings.digest_alert_email_to)
    top_k = int(settings.digest_alert_top_jobs)

    if not url and not recipients:
        summary.reason = "no_webhook_or_email"
        return summary

    items = _eligible_jobs(built, thresh, top_k)
    summary.matched = len(items)

    if not items:
        summary.skipped = True
        summary.reason = "none_at_or_above_threshold"
        return summary

    summary.skipped = False
    text_body = _plaintext_body(built, items, source)
    digest_id_str = str(built.digest.id)
    jobs_preview = [
        {
            "company": it.job.company_name,
            "title": it.job.title,
            "score": float(it.job.ranking_score or 0),
            "lane": it.lane,
            "apply_url": it.job.apply_url,
        }
        for it in items[:12]
    ]
    webhook_payload: dict[str, Any] = {
        "text": text_body[:15_000],
        "atlas_digest_alert": True,
        "digest_id": digest_id_str,
        "source": source,
        "threshold": summary.threshold,
        "jobs": jobs_preview,
    }

    # --- webhook ---------------------------------------------------------
    if url:
        summary.webhook_attempted = True
        try:
            resp = requests.post(url, json=webhook_payload, timeout=15.0)
            summary.webhook_ok = 200 <= resp.status_code < 300
            if not summary.webhook_ok:
                summary.detail = f"webhook HTTP {resp.status_code}: {(resp.text or '')[:200]}"
        except requests.RequestException as e:
            summary.webhook_ok = False
            summary.detail = f"webhook error: {e}"

    # --- email -----------------------------------------------------------
    if recipients:
        summary.email_attempted = True
        cfg = SmtpConfig.from_env()
        if cfg is None:
            summary.email_ok = False
            suffix = "SMTP not configured"
            summary.detail = (
                f"{summary.detail}; {suffix}" if summary.detail else suffix
            )
        else:
            ok, err = _send_plain_email(
                cfg,
                recipients=recipients,
                subject=(
                    f"[Atlas] Digest alert — scores ≥ {summary.threshold:g} ({len(items)} job(s))"
                ),
                body=text_body,
            )
            summary.email_ok = ok
            if not ok and err:
                summary.detail = (
                    summary.detail + "; " + err if summary.detail else err
                )[:1500]

    # --- audit (best-effort) --------------------------------------
    fired = summary.webhook_ok is True or summary.email_ok is True
    if fired:
        try:
            db.add(
                PipelineEvent(
                    entity_type="digest",
                    entity_id=built.digest.id,
                    event_name="digest_top_jobs_alert",
                    details={
                        "source": source,
                        "digest_type": built.digest.digest_type,
                        **summary.to_details(),
                    },
                )
            )
            db.flush()
        except Exception:  # noqa: BLE001
            logger.exception("could not persist digest_top_jobs_alert pipeline_event")

    return summary


def _send_plain_email(
    cfg: SmtpConfig,
    *,
    recipients: list[str],
    subject: str,
    body: str,
) -> tuple[bool, str]:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    try:
        if cfg.use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(cfg.host, cfg.port, timeout=45) as s:
                s.ehlo()
                s.starttls(context=context)
                s.ehlo()
                if cfg.username and cfg.password:
                    s.login(cfg.username, cfg.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=45) as s:
                if cfg.username and cfg.password:
                    s.login(cfg.username, cfg.password)
                s.send_message(msg)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:800]
