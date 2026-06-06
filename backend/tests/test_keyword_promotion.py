"""keyword_promotion — guarded promotion of suggested_keywords."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import keyword_promotion as kp


def _profile(**kwargs):
    defaults = dict(
        slug="demo",
        id=uuid.uuid4(),
        strong_keywords=[],
        weak_keywords=[],
        negative_keywords=[],
        ranker_text_signals={
            "suggested_keywords": ["solidity", "typescript"],
        },
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_explicit_promote_weak_dry_run() -> None:
    db = MagicMock()
    p = _profile()
    r = kp.promote_suggested_keywords(
        db,
        p,
        dry_run=True,
        target="weak",
        terms=["solidity"],
        auto=False,
    )
    assert r.added == ["solidity"]
    assert not r.applied
    db.commit.assert_not_called()


def test_explicit_not_in_suggestions_rejected() -> None:
    db = MagicMock()
    p = _profile()
    r = kp.promote_suggested_keywords(
        db,
        p,
        dry_run=True,
        target="weak",
        terms=["rust"],
        auto=False,
    )
    assert r.added == []
    assert r.rejected_not_in_suggestions == ["rust"]


def test_auto_respects_max_and_order() -> None:
    db = MagicMock()
    p = _profile(
        ranker_text_signals={
            "suggested_keywords": ["aaa", "bbb", "ccc", "ddd"],
        }
    )
    r = kp.promote_suggested_keywords(
        db,
        p,
        dry_run=True,
        target="weak",
        auto=True,
        max_terms=2,
    )
    assert r.added == ["aaa", "bbb"]


def test_skip_already_on_profile() -> None:
    db = MagicMock()
    p = _profile(weak_keywords=["solidity"])
    r = kp.promote_suggested_keywords(
        db,
        p,
        dry_run=True,
        target="weak",
        terms=["solidity"],
        auto=False,
    )
    assert r.added == []
    assert r.reason_skipped and "nothing eligible" in r.reason_skipped.lower()


def test_apply_persists_weak_keyword_and_trims_suggestions() -> None:
    db = MagicMock()
    p = _profile()
    r = kp.promote_suggested_keywords(
        db,
        p,
        dry_run=False,
        target="weak",
        terms=["solidity"],
        auto=False,
        remove_from_suggestions=True,
    )
    assert r.applied
    assert p.weak_keywords == ["solidity"]
    assert p.ranker_text_signals["suggested_keywords"] == ["typescript"]
    db.commit.assert_called_once()
