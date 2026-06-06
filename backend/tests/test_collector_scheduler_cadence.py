"""collector_scheduler cadence (cron UTC) + early next_run_at after transient errors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import uuid

from app.services.collector_pipeline import CollectorPipelineResult
from app.services import collector_scheduler as cs


def _sched_cron(expr: str = "30 9 * * 1-5") -> SimpleNamespace:
    return SimpleNamespace(
        cadence="cron",
        cron_expression=expr,
        hour_utc=None,
        minute_utc=None,
        interval_minutes=None,
        last_run_at=None,
    )


def test_compute_next_run_cron_weekday_morning() -> None:
    s = _sched_cron()
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)  # Mon
    nxt = cs.compute_next_run(s, now=now)
    assert nxt == datetime(2026, 4, 28, 9, 30, tzinfo=timezone.utc)


def test_next_run_after_transient_error_uses_min_of_cadence_and_retry() -> None:
    s = _sched_cron()
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)
    regular = cs.compute_next_run(s, now=now)
    res = CollectorPipelineResult(ok=False, error="connection timeout to api")
    settings = SimpleNamespace(collector_schedule_error_retry_seconds=300.0)
    nxt = cs.next_run_after_collector_error(s, res, now=now, settings=settings)
    assert nxt == min(regular, now + timedelta(seconds=300))


def test_next_run_after_error_non_retryable_uses_cadence_only() -> None:
    s = _sched_cron()
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)
    regular = cs.compute_next_run(s, now=now)
    res = CollectorPipelineResult(ok=False, error="fatal_parse_xyz")
    settings = SimpleNamespace(collector_schedule_error_retry_seconds=300.0)
    nxt = cs.next_run_after_collector_error(s, res, now=now, settings=settings)
    assert nxt == regular


def test_next_run_after_error_with_ingestion_id_skips_early_retry() -> None:
    s = _sched_cron()
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)
    regular = cs.compute_next_run(s, now=now)
    res = CollectorPipelineResult(
        ok=False,
        error="timeout",
        ingestion_run_id=uuid.uuid4(),
    )
    settings = SimpleNamespace(collector_schedule_error_retry_seconds=300.0)
    nxt = cs.next_run_after_collector_error(s, res, now=now, settings=settings)
    assert nxt == regular
