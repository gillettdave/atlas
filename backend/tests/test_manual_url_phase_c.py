"""Unit tests for manual URL HTML extraction (Phase C)."""
from __future__ import annotations

from app.services.manual_job_url import payload_from_job_page_html


def test_payload_extracts_og_tags() -> None:
    html = """<!DOCTYPE html><html><head>
    <meta property="og:title" content="Senior PM — Acme Corp" />
    <meta property="og:site_name" content="Acme Careers" />
    <meta property="og:description" content="Lead product." />
    </head><body></body></html>
    """
    payload, html_store = payload_from_job_page_html(html, "https://jobs.acme.example/pm")
    assert "Senior PM" in payload["job_title"]
    assert payload["company_name"]
    assert payload["apply_url"]
    assert html_store is not None
