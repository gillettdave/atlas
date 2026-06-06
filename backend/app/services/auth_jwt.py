"""JWT helpers for OAuth-issued Atlas API bearer tokens."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt


def mint_oauth_state(jwt_secret: str) -> str:
    """Opaque signed state parameter for OAuth redirect CSRF mitigation."""
    if not jwt_secret or len(jwt_secret) < 16:
        raise ValueError("ATLAS_JWT_SECRET must be set (min 16 chars) for OAuth flows.")
    return jwt.encode(
        {
            "purpose": "google_oauth_state",
            "jti": secrets.token_urlsafe(16),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        jwt_secret,
        algorithm="HS256",
    )


def verify_oauth_state(token: str, jwt_secret: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        jwt_secret,
        algorithms=["HS256"],
        options={"require": ["exp"]},
    )
    if payload.get("purpose") != "google_oauth_state":
        raise jwt.InvalidTokenError("wrong purpose")
    return payload


def mint_access_token(
    *,
    jwt_secret: str,
    user_id: Any,
    email: str | None,
    expires_seconds: int,
) -> str:
    if not jwt_secret or len(jwt_secret) < 16:
        raise ValueError("ATLAS_JWT_SECRET must be set (min 16 chars).")
    now = datetime.now(timezone.utc)
    uid = str(user_id)
    return jwt.encode(
        {
            "sub": uid,
            "email": email,
            "iat": now,
            "exp": now + timedelta(seconds=max(60, int(expires_seconds))),
        },
        jwt_secret,
        algorithm="HS256",
    )


def decode_access_token(token: str, jwt_secret: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        jwt_secret,
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
