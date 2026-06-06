"""Background tick for discovery + email-intake dues (same lifespan pattern as delivery/collector loops)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.user import User
from ..services import email_intake_svc as email_svc
from ..services import job_discovery as disc_svc

logger = logging.getLogger("atlas.intake_scheduler")


def tick(
    db: Session,
    *,
    max_discovery_runs_per_tick: int = 10,
    max_email_syncs_per_tick: int = 5,
) -> dict[str, Any]:
    """Run due discovery crawls + due Gmail syncs, capped per tick across all tenants.

    Each cap is enforced globally for this tick (not per user). Processes every
    row in ``users`` until caps are exhausted.
    """
    user_ids: list[uuid.UUID] = list(db.scalars(select(User.id)).all())
    out: dict[str, Any] = {
        "users_seen": len(user_ids),
        "discovery_runs": 0,
        "email_syncs": 0,
        "discovery_errors": 0,
        "email_errors": 0,
    }
    disc_left = max(0, int(max_discovery_runs_per_tick))
    email_left = max(0, int(max_email_syncs_per_tick))

    for uid in user_ids:
        if disc_left <= 0:
            break
        due_s = disc_svc.list_due_seed_ids(db, user_id=uid, limit=disc_left)
        for sid in due_s:
            try:
                disc_svc.run_seed_discovery(
                    db, seed_id=sid, user_id=uid, profile_slug=None
                )
                out["discovery_runs"] += 1
            except Exception:  # noqa: BLE001
                out["discovery_errors"] += 1
                logger.exception(
                    "intake scheduler: discovery seed_id=%s user_id=%s",
                    sid,
                    uid,
                )
            disc_left -= 1
            if disc_left <= 0:
                break

    for uid in user_ids:
        if email_left <= 0:
            break
        due_e = email_svc.list_due_email_source_ids(db, user_id=uid, limit=email_left)
        for eid in due_e:
            try:
                email_svc.run_email_sync(db, source_id=eid, user_id=uid)
                out["email_syncs"] += 1
            except Exception:  # noqa: BLE001
                out["email_errors"] += 1
                logger.exception(
                    "intake scheduler: email source_id=%s user_id=%s",
                    eid,
                    uid,
                )
            email_left -= 1
            if email_left <= 0:
                break

    return out
