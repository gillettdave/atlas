"""Unit tests for Atlas JWT helpers (OAuth state + access tokens)."""

from __future__ import annotations

import uuid

import jwt
import pytest

from app.services.auth_jwt import (
    decode_access_token,
    mint_access_token,
    mint_oauth_state,
    verify_oauth_state,
)


SECRET = "x" * 32  # satisfies PyJWT HMAC minimum length hints in tests


def test_mint_verify_oauth_state_roundtrip() -> None:
    tok = mint_oauth_state(SECRET)
    payload = verify_oauth_state(tok, SECRET)
    assert payload["purpose"] == "google_oauth_state"


def test_oauth_state_rejects_wrong_secret() -> None:
    tok = mint_oauth_state(SECRET)
    with pytest.raises(jwt.PyJWTError):
        verify_oauth_state(tok, "z" * 32)


def test_access_token_roundtrip() -> None:
    uid = uuid.uuid4()
    raw = mint_access_token(
        jwt_secret=SECRET,
        user_id=uid,
        email="a@example.com",
        expires_seconds=3600,
    )
    payload = decode_access_token(raw, SECRET)
    assert uuid.UUID(payload["sub"]) == uid
    assert payload["email"] == "a@example.com"
