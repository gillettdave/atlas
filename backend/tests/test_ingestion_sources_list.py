"""ingestion_sources_list — LIKE escape helper (no DB)."""

from __future__ import annotations

from app.services.ingestion_sources_list import escape_ilike_pattern


def test_escape_ilike_pattern_percent_and_wildcards() -> None:
    raw = r"earn_100%"
    escaped = escape_ilike_pattern(raw)
    assert "\\%" in escaped
    assert "\\_" in escaped
    assert escape_ilike_pattern("plain") == "plain"


def test_escape_ilike_pattern_backslash() -> None:
    raw = r"path\to\blob"
    out = escape_ilike_pattern(raw)
    assert out.count("\\") >= 4

