"""Tenant user rows (`users`). Seeded single-user bootstrap until auth."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constants import SEEDED_LOCAL_USER_ID
from ..models.user import User


def get_seeded_user_id() -> uuid.UUID:
    return SEEDED_LOCAL_USER_ID


def ensure_seeded_local_user(db: Session) -> User:
    """Upsert-style ensure the deterministic local tenant exists."""
    uid = SEEDED_LOCAL_USER_ID
    row = db.get(User, uid)
    if row is not None:
        return row
    u = User(
        id=uid,
        email=None,
        display_name="Local (seeded)",
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.get(User, uid)
        if row is not None:
            return row
        raise
    db.refresh(u)
    return u


def upsert_from_google_profile(
    db: Session,
    *,
    email: str,
    display_name: str | None,
) -> User:
    """Create or update a ``users`` row keyed by email (verified via Google OAuth)."""
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("email required from OAuth profile")
    row = db.scalar(select(User).where(User.email == email))
    if row is not None:
        if display_name and (row.display_name or "") != display_name:
            row.display_name = display_name
            db.commit()
            db.refresh(row)
        return row
    u = User(
        id=uuid.uuid4(),
        email=email,
        display_name=display_name or email.split("@", 1)[0],
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.scalar(select(User).where(User.email == email))
        if row is not None:
            return row
        raise
    db.refresh(u)
    return u
