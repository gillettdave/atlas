"""Shared FastAPI dependencies."""
from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..constants import SEEDED_LOCAL_USER_ID
from ..config import Settings, get_settings
from ..db import get_db
from ..services.auth_jwt import decode_access_token

DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def current_tenant_user_id(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> uuid.UUID:
    """Resolve tenant user id from Bearer JWT, or seeded user when configured."""
    if authorization:
        prefix = "bearer "
        if authorization.lower().startswith(prefix):
            raw = authorization[len(prefix) :].strip()
            if not raw:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    detail="Empty Authorization bearer token.",
                )
            if not settings.jwt_secret or len(settings.jwt_secret.strip()) < 16:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Bearer authentication is not configured (ATLAS_JWT_SECRET).",
                )
            try:
                payload = decode_access_token(raw, settings.jwt_secret)
                sub = payload["sub"]
                return uuid.UUID(str(sub))
            except jwt.PyJWTError as e:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired bearer token.",
                ) from e
            except ValueError as e:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    detail="Malformed bearer token subject.",
                ) from e
    if settings.auth_allow_seeded_without_bearer:
        return SEEDED_LOCAL_USER_ID
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing Authorization: Bearer token.",
    )


TenantUserId = Annotated[uuid.UUID, Depends(current_tenant_user_id)]


def require_admin_token(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    settings: SettingsDep = None,  # type: ignore[assignment]
) -> None:
    """Very light gate for write endpoints.

    MVP is effectively single-user; this just keeps random callers from
    posting to the ingestion endpoints. Replace with real auth later.
    """
    expected = (settings.admin_token if settings else "").strip()
    # In dev, allow wide-open if the token is the default. Prod must override.
    if settings and settings.env != "dev":
        if not x_admin_token or x_admin_token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid X-Admin-Token",
            )
