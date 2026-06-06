"""Unit tests for pipeline_operator helpers."""

from __future__ import annotations

from app.services.pipeline_operator import title_hint


def test_title_hint_plain_keys():
    assert title_hint({"job_title": "Senior Dev"}) == "Senior Dev"
    assert title_hint({"normalized_title": "PM"}) == "PM"


def test_title_hint_nested_extracted():
    assert title_hint({"extracted": {"title": "Analyst"}}) == "Analyst"
