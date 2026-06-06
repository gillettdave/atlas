"""Time-decayed weighting helpers for Sprint I.2 learn_from_feedback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.learning import (
    LearningConfig,
    _effective_decay_half_life_days,
    _weighted_mean,
    decay_weight_for_feedback_age,
)


def test_decay_uniform_when_half_life_zero() -> None:
    now = datetime.now(timezone.utc)
    anchor = now - timedelta(days=400)
    assert (
        decay_weight_for_feedback_age(anchor, now=now, half_life_days=0.0) == 1.0
    )


def test_decay_exactly_one_half_life() -> None:
    now = datetime(2026, 4, 27, 12, tzinfo=timezone.utc)
    anchor = now - timedelta(days=14)
    w = decay_weight_for_feedback_age(anchor, now=now, half_life_days=14.0)
    assert abs(w - 0.5) < 1e-9


def test_weighted_mean_two_equal_weights() -> None:
    m, tw = _weighted_mean([(10.0, 1.0), (20.0, 1.0)])
    assert abs(m - 15.0) < 1e-9
    assert tw == 2.0


def test_effective_decay_uses_explicit_config() -> None:
    cfg = LearningConfig(feedback_decay_half_life_days=21.5)
    assert abs(_effective_decay_half_life_days(cfg) - 21.5) < 1e-9


def test_effective_decay_fallback_to_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.learning.get_settings",
        lambda: SimpleNamespace(
            learning_feedback_decay_half_life_days=42.0,
        ),
    )
    cfg = LearningConfig(feedback_decay_half_life_days=None)
    assert _effective_decay_half_life_days(cfg) == 42.0
