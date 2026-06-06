"""CRM dashboard grouping (deterministic helpers)."""

from __future__ import annotations

import pytest

from app.services import application_dashboard as dash


def test_pipeline_lane_buckets() -> None:
    assert dash.pipeline_lane("Interested") == "active"
    assert dash.pipeline_lane("SHORTLISTED") == "active"
    assert dash.pipeline_lane("applied") == "post_apply"
    assert dash.pipeline_lane("Interviewing") == "post_apply"
    assert dash.pipeline_lane("rejected") == "closed"
    assert dash.pipeline_lane("Archived") == "closed"
    assert dash.pipeline_lane("") == "needs_attention"


def test_effective_lane_outcome_overrides_free_text_stage() -> None:
    assert dash.effective_pipeline_lane("Interested", None) == "active"
    assert dash.effective_pipeline_lane("Interested", "rejected") == "closed"
    assert dash.effective_pipeline_lane("Interested", "hired") == "closed"
    assert dash.effective_pipeline_lane("drafting", "interviewing") == "post_apply"
    assert dash.effective_pipeline_lane("drafting", "offered") == "post_apply"
    assert dash.effective_pipeline_lane("applied", "withdrawn") == "closed"


def test_parse_dashboard_outcome_filter() -> None:
    assert dash.parse_dashboard_outcome_filter(None) == frozenset()
    assert dash.parse_dashboard_outcome_filter("  ") == frozenset()
    assert dash.parse_dashboard_outcome_filter("rejected,Hired ") == frozenset(
        {"rejected", "hired"}
    )


def test_parse_dashboard_outcome_filter_errors() -> None:
    with pytest.raises(ValueError, match="bogus"):
        dash.parse_dashboard_outcome_filter("rejected,bogus")
