"""Google OAuth redirect flow and optional auth-debug endpoints."""

from __future__ import annotations

import urllib.parse

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from ..config import Settings, get_settings
from ..models.user import User
from ..services.auth_jwt import mint_access_token, mint_oauth_state, verify_oauth_state
from ..services.oauth_google import (
    build_authorize_url,
    exchange_code_for_tokens,
    fetch_google_profile,
)
from ..services.users import upsert_from_google_profile
from .deps import DbSession, TenantUserId

router = APIRouter()


def _require_oauth_env(settings: Settings) -> tuple[str, str, str, str]:
    cid = (settings.google_oauth_client_id or "").strip()
    csec = (settings.google_oauth_client_secret or "").strip()
    redir = (settings.google_oauth_redirect_uri or "").strip()
    jwt_sec = settings.jwt_secret or ""
    if not cid or not csec or not redir:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured (client id / secret / redirect URI).",
        )
    if not jwt_sec or len(jwt_sec) < 16:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT not configured — set ATLAS_JWT_SECRET (min 16 characters).",
        )
    return cid, csec, redir, jwt_sec


@router.get("/oauth/google/start")
def oauth_google_start(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    client_id, _, redirect_uri, jwt_sec = _require_oauth_env(settings)
    state = mint_oauth_state(jwt_sec)
    url = build_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
    )
    return RedirectResponse(url, status_code=302)


@router.get("/oauth/google/callback")
def oauth_google_callback(
    db: DbSession,
    settings: Settings = Depends(get_settings),
    *,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Google OAuth error: {error}",
        )
    if not code or not state:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state.",
        )

    _, client_secret, redirect_uri, jwt_sec = _require_oauth_env(settings)
    client_id = (settings.google_oauth_client_id or "").strip()

    try:
        verify_oauth_state(state, jwt_sec)
    except jwt.PyJWTError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OAuth state: {e}",
        ) from e

    tokens = exchange_code_for_tokens(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        code=code,
    )
    gat = tokens.get("access_token")
    if not gat:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Google token response missing access_token.",
        )

    profile = fetch_google_profile(gat)
    email = profile.get("email")
    name = profile.get("name")
    if not email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Google profile did not return email (required).",
        )

    user = upsert_from_google_profile(db, email=email, display_name=name)
    atlas_jwt = mint_access_token(
        jwt_secret=jwt_sec,
        user_id=user.id,
        email=user.email,
        expires_seconds=settings.jwt_access_token_expires_seconds,
    )

    base = (settings.frontend_oauth_success_url or "http://127.0.0.1:8501/").rstrip("/") + "/"
    token_q = urllib.parse.quote(atlas_jwt, safe="")
    target = f"{base}?atlas_token={token_q}"
    return RedirectResponse(target, status_code=302)


@router.get("/me")
def auth_me(db: DbSession, tenant_id: TenantUserId) -> dict:
    row = db.get(User, tenant_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return {
        "user_id": str(row.id),
        "email": row.email,
        "display_name": row.display_name,
    }
