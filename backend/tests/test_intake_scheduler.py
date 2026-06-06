"""intake_scheduler.tick smoke (mocked Session)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.intake_scheduler import tick


def test_tick_no_users_short_circuits_discovery_and_email():
    db = MagicMock()
    sr = MagicMock()
    sr.all.return_value = []
    db.scalars.return_value = sr

    out = tick(
        db,
        max_discovery_runs_per_tick=5,
        max_email_syncs_per_tick=3,
    )

    assert out["users_seen"] == 0
    assert out["discovery_runs"] == 0
    assert out["email_syncs"] == 0
    assert db.scalars.call_count == 1
