"""Cron cadence + early next_run_at after transient failures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from app.services import scheduler as sched


def _schedule_cron(expr: str = "0 9 * * *") -> Mock:
    s = Mock()
    s.cadence = "cron"
    s.cron_expression = expr
    s.hour_utc = None
    s.minute_utc = None
    s.interval_minutes = None
    s.last_run_at = None
    return s


def test_compute_next_run_cron_later_same_day() -> None:
    s = _schedule_cron()
    now = datetime(2026, 4, 27, 8, 0, tzinfo=timezone.utc)
    nxt = sched.compute_next_run(s, now=now)
    assert nxt == datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc)


def test_compute_next_run_cron_next_day() -> None:
    s = _schedule_cron()
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)
    nxt = sched.compute_next_run(s, now=now)
    assert nxt == datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)


def test_next_run_after_failed_transient_uses_min_of_cadence_and_backoff() -> None:
    s = _schedule_cron()
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)
    settings = SimpleNamespace(delivery_schedule_error_retry_seconds=300.0)
    nxt = sched.next_run_after_failed_attempt(
        s, TimeoutError(), now=now, settings=settings
    )
    regular = sched.compute_next_run(s, now=now)
    early = now + timedelta(seconds=300)
    assert nxt == min(regular, early) == early


def test_next_run_after_failed_nontransient_uses_cadence_only() -> None:
    s = _schedule_cron()
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)
    settings = SimpleNamespace(delivery_schedule_error_retry_seconds=300.0)
    nxt = sched.next_run_after_failed_attempt(
        s, ValueError("nope"), now=now, settings=settings
    )
    assert nxt == sched.compute_next_run(s, now=now)


def test_next_run_after_failed_zero_retry_seconds_uses_cadence_only() -> None:
    s = _schedule_cron()
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)
    settings = SimpleNamespace(delivery_schedule_error_retry_seconds=0.0)
    nxt = sched.next_run_after_failed_attempt(
        s, TimeoutError(), now=now, settings=settings
    )
    assert nxt == sched.compute_next_run(s, now=now)
