"""Unit tests for `job_discovery.looks_like_job_posting_url` (pure, no DB)."""

from __future__ import annotations

from app.services.job_discovery import looks_like_job_posting_url


def test_lever_uuid_path():
    url = (
        "https://jobs.lever.co/acme/"
        "123e4567-e89b-12d3-a456-426614174000/"
    )
    assert looks_like_job_posting_url(url) is True


def test_greenhouse_job_id():
    url = "https://boards.greenhouse.io/acme/jobs/12345"
    assert looks_like_job_posting_url(url) is True


def test_ashby_uuid_path():
    url = (
        "https://jobs.ashbyhq.com/foo/"
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/"
    )
    assert looks_like_job_posting_url(url) is True


def test_job_path_hints():
    assert looks_like_job_posting_url("https://example.com/careers/listing?id=1") is True


def test_non_job_generic():
    assert looks_like_job_posting_url("https://example.com/about") is False
