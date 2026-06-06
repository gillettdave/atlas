"""Jobstash public-mode date window logic (Sprint M.3 tuning)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.collectors import jobstash


@pytest.mark.parametrize(
    ("delta", "profile", "incremental_hours", "expect"),
    [
        (timedelta(hours=12), "incremental", 24.0, True),
        (timedelta(days=2), "incremental", 24.0, False),
        (timedelta(days=5), "initial", 24.0, True),
        (timedelta(days=30), "initial", 24.0, False),
        (None, "initial", 24.0, True),
        (None, "incremental", 48.0, False),
    ],
)
def test_include_listing_by_pull_profile(
    delta: timedelta | None,
    profile: str,
    incremental_hours: float,
    expect: bool,
) -> None:
    posted = None if delta is None else datetime.now(timezone.utc) - delta
    out = jobstash._include_listing_by_pull_profile(
        posted,
        profile,  # type: ignore[arg-type]
        initial_max_days=14,
        incremental_max_hours=incremental_hours,
    )
    assert out is expect


def test_incremental_wider_window_hours() -> None:
    """Raise ATLAS_JOBSTASH_INCREMENTAL_MAX_AGE_HOURS to admit older rows."""
    posted = datetime.now(timezone.utc) - timedelta(hours=36)
    assert (
        jobstash._include_listing_by_pull_profile(
            posted,
            "incremental",
            initial_max_days=14,
            incremental_max_hours=24.0,
        )
        is False
    )
    assert (
        jobstash._include_listing_by_pull_profile(
            posted,
            "incremental",
            initial_max_days=14,
            incremental_max_hours=48.0,
        )
        is True
    )
