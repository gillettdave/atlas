"""Phase A: deterministic tenant id + AI facade wiring (no network)."""
from __future__ import annotations

import uuid

import pytest

from app.constants import SEEDED_LOCAL_USER_ID
from app.config import Settings
from app.services.ai import AIProviderMisconfigured, get_chat_completer


def test_seeded_local_user_id_is_deterministic() -> None:
    expected = uuid.uuid5(
        uuid.NAMESPACE_DNS, "project-atlas.seeded-local-user"
    )
    assert SEEDED_LOCAL_USER_ID == expected


def test_chat_completer_stub_without_api_key() -> None:
    s = Settings(openai_api_key=None)
    comp = get_chat_completer(s)
    with pytest.raises(AIProviderMisconfigured):
        comp.complete([{"role": "user", "content": "ping"}])
