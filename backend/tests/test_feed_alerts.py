"""feed_alerts — optional digest top-job pings (W5)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services import feed_alerts as fa
from app.services.digest_builder import BuiltDigest, BuiltDigestItem, DigestStats


class _JobStub:
    def __init__(
        self,
        *,
        score: Decimal,
        company: str,
        title: str,
        apply_url: str = "https://example.com/job",
        lane: str = "fresh",
    ) -> None:
        self.company_name = company
        self.title = title
        self.apply_url = apply_url
        self.ranking_score = score
        self.last_seen_at = None


class _DigestStub:
    def __init__(self) -> None:
        import uuid
        from datetime import datetime, timezone

        self.id = uuid.uuid4()
        self.digest_type = "daily"
        self.generated_at = datetime.now(timezone.utc)


def _built(scores: list[float]) -> BuiltDigest:
    d = _DigestStub()
    items = [
        BuiltDigestItem(
            job=_JobStub(score=Decimal(str(s)), company="Co", title=f"T{i}", lane="fresh"),
            lane="fresh",
            reason="r",
            rank_position=i + 1,
        )
        for i, s in enumerate(scores)
    ]
    return BuiltDigest(digest=d, items=items, stats=DigestStats())


@patch("app.services.feed_alerts.get_settings")
def test_alert_skipped_when_disabled(mock_gs: MagicMock) -> None:
    s = MagicMock()
    s.digest_alert_enabled = False
    mock_gs.return_value = s
    db = MagicMock()
    out = fa.maybe_digest_top_jobs_alert(db, _built([90.0, 92.0]), source="unit")
    assert out.reason == "disabled"
    db.add.assert_not_called()


@patch("app.services.feed_alerts.requests.post")
@patch("app.services.feed_alerts.get_settings")
def test_webhook_posts_when_matches(mock_gs: MagicMock, mock_post: MagicMock) -> None:
    s = MagicMock()
    s.digest_alert_enabled = True
    s.digest_alert_min_ranking_score = 80.0
    s.digest_alert_webhook_url = "https://hooks.example.invalid/x"
    s.digest_alert_email_to = ""
    s.digest_alert_top_jobs = 5
    mock_gs.return_value = s

    resp = MagicMock()
    resp.status_code = 200
    resp.text = "ok"
    mock_post.return_value = resp

    db = MagicMock()
    fa.maybe_digest_top_jobs_alert(db, _built([50.0, 85.0, 92.0]), source="unit")
    mock_post.assert_called_once()
    db.add.assert_called_once()
    call_kw = mock_post.call_args.kwargs["json"]
    assert call_kw.get("atlas_digest_alert") is True
    assert len(call_kw.get("jobs") or []) >= 2
