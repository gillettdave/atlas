"""Optional global intake max listing age (cleaner_v2 NEW_CANONICAL gate)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services import cleaner_v2
from app.services.cleaner_v2 import (
    CleanerDecisionType,
    listing_reference_datetime,
)
from app.models.raw_job_event import RawJobEvent


def _minimal_raw(*, payload: dict) -> RawJobEvent:
    return RawJobEvent(
        id=uuid.uuid4(),
        ingestion_run_id=uuid.uuid4(),
        provider="greenhouse",
        source_url="https://boards.greenhouse.io/acme/jobs/1",
        raw_payload=payload,
    )


def test_listing_reference_datetime_jobstash_iso() -> None:
    dt = listing_reference_datetime(
        {"jobstash_date_posted_utc": "2026-03-01T12:00:00+00:00"}
    )
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 3


def test_listing_reference_nested_native_api_item() -> None:
    dt = listing_reference_datetime(
        {
            "company_name": "x",
            "native_api_item": {"updated_at": "2026-02-01T00:00:00Z"},
        }
    )
    assert dt is not None


def _empty_match_db() -> MagicMock:
    ex = MagicMock()
    ex.scalar_one_or_none.return_value = None
    ex.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute.return_value = ex
    return db


@patch.object(cleaner_v2, "_tier1_strong_match", return_value=None)
@patch.object(cleaner_v2, "_tier2_medium_match", return_value=[])
@patch.object(cleaner_v2, "_tier3_weak_match", return_value=[])
@patch("app.services.cleaner_v2.get_settings")
def test_reject_new_canonical_when_listing_too_old(gs, _t3, _t2, _t1) -> None:
    gs.return_value.intake_max_listing_age_days = 30
    posted = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    raw = _minimal_raw(
        payload={
            "company_name": "Acme Corp",
            "job_title": "Software Engineer",
            "job_url": "https://example.com/apply/abc",
            "updated_at": posted,
        }
    )
    d = cleaner_v2.decide(_empty_match_db(), raw)
    assert d.decision == CleanerDecisionType.REJECTED_LOW_QUALITY
    assert d.reason == "listing_exceeds_max_age_days"


@patch.object(cleaner_v2, "_tier1_strong_match", return_value=None)
@patch.object(cleaner_v2, "_tier2_medium_match", return_value=[])
@patch.object(cleaner_v2, "_tier3_weak_match", return_value=[])
@patch("app.services.cleaner_v2.get_settings")
def test_allow_new_canonical_when_listing_recent(gs, _t3, _t2, _t1) -> None:
    gs.return_value.intake_max_listing_age_days = 30
    posted = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    raw = _minimal_raw(
        payload={
            "company_name": "Acme Corp",
            "job_title": "Software Engineer",
            "job_url": "https://example.com/apply/def",
            "updated_at": posted,
        }
    )
    d = cleaner_v2.decide(_empty_match_db(), raw)
    assert d.decision == CleanerDecisionType.NEW_CANONICAL


@patch.object(cleaner_v2, "_tier1_strong_match", return_value=None)
@patch.object(cleaner_v2, "_tier2_medium_match", return_value=[])
@patch.object(cleaner_v2, "_tier3_weak_match", return_value=[])
@patch("app.services.cleaner_v2.get_settings")
def test_allow_when_no_parsable_date_even_if_gate_on(gs, _t3, _t2, _t1) -> None:
    gs.return_value.intake_max_listing_age_days = 30
    raw = _minimal_raw(
        payload={
            "company_name": "Acme Corp",
            "job_title": "Software Engineer",
            "job_url": "https://example.com/apply/ghi",
        }
    )
    d = cleaner_v2.decide(_empty_match_db(), raw)
    assert d.decision == CleanerDecisionType.NEW_CANONICAL


@patch.object(cleaner_v2, "_tier1_strong_match", return_value=None)
@patch.object(cleaner_v2, "_tier2_medium_match", return_value=[])
@patch.object(cleaner_v2, "_tier3_weak_match", return_value=[])
@patch("app.services.cleaner_v2.get_settings")
def test_run_override_stricter_than_settings(gs, _t3, _t2, _t1) -> None:
    gs.return_value.intake_max_listing_age_days = None
    posted = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    raw = _minimal_raw(
        payload={
            "company_name": "Acme Corp",
            "job_title": "Software Engineer",
            "job_url": "https://example.com/apply/ov1",
            "updated_at": posted,
        }
    )
    with cleaner_v2.intake_max_listing_age_run_override(30):
        d = cleaner_v2.decide(_empty_match_db(), raw)
    assert d.decision == CleanerDecisionType.REJECTED_LOW_QUALITY
    assert d.reason == "listing_exceeds_max_age_days"


@patch.object(cleaner_v2, "_tier1_strong_match", return_value=None)
@patch.object(cleaner_v2, "_tier2_medium_match", return_value=[])
@patch.object(cleaner_v2, "_tier3_weak_match", return_value=[])
@patch("app.services.cleaner_v2.get_settings")
def test_run_override_disables_gate(gs, _t3, _t2, _t1) -> None:
    gs.return_value.intake_max_listing_age_days = 30
    posted = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    raw = _minimal_raw(
        payload={
            "company_name": "Acme Corp",
            "job_title": "Software Engineer",
            "job_url": "https://example.com/apply/ov2",
            "updated_at": posted,
        }
    )
    with cleaner_v2.intake_max_listing_age_run_override(None):
        d = cleaner_v2.decide(_empty_match_db(), raw)
    assert d.decision == CleanerDecisionType.NEW_CANONICAL
