"""Phase B: career-memory router wiring."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.api.career_memory import document_to_detail, document_to_list_item
from app.services.career_memory import (
    CAREER_MEMORY_UPLOAD_HINT,
    _parse_llm_facts_response,
    prepare_upload_bytes_as_text,
)


def _fake_doc(
    *,
    doc_id: int = 1,
    name: str = "resume.txt",
    content_type: str | None = "text/plain",
    raw: str = "hello world",
):
    m = MagicMock()
    m.id = doc_id
    m.name = name
    m.content_type = content_type
    m.ingested_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    m.raw_text = raw
    return m


def test_document_to_list_item_preview() -> None:
    doc = _fake_doc(raw="alpha " * 100)
    row = document_to_list_item(doc, preview_chars=20)
    assert row.id == 1
    assert row.preview is not None
    assert row.preview.endswith("…")
    assert row.ingested_at is not None


def test_document_to_list_item_preview_disabled() -> None:
    doc = _fake_doc()
    row = document_to_list_item(doc, preview_chars=0)
    assert row.preview is None


def test_document_to_detail_truncates() -> None:
    doc = _fake_doc(raw="abcdefghij")
    out = document_to_detail(doc, max_chars=4)
    assert out.raw_text == "abcd"
    assert out.truncated is True


def test_document_to_detail_full_when_no_max() -> None:
    doc = _fake_doc(raw="abcdefghij")
    out = document_to_detail(doc, max_chars=None)
    assert out.raw_text == "abcdefghij"
    assert out.truncated is False


def test_prepare_upload_bytes_strips_nul_for_plain_text() -> None:
    data = b"hello\x00world"
    out = prepare_upload_bytes_as_text("notes.txt", "text/plain", data)
    assert "\x00" not in out
    assert "hello" in out and "world" in out


def test_prepare_upload_rejects_unlabeled_binary() -> None:
    junk = (bytes(range(256)) + b"\x00" * 200) * 30
    with pytest.raises(ValueError) as err:
        prepare_upload_bytes_as_text("upload", "application/octet-stream", junk)
    assert CAREER_MEMORY_UPLOAD_HINT in str(err.value)


def test_career_memory_router_mounted_under_prefix() -> None:
    from app.api.career_memory import router

    assert router.prefix == "/career-memory"


def test_parse_llm_facts_json_object() -> None:
    raw = '{"facts": ["too short", "This is a valid career fact with enough tokens."]}'
    out = _parse_llm_facts_response(raw, max_items=10)
    assert len(out) == 1
    assert "valid career fact" in out[0]


def test_parse_llm_facts_markdown_fence() -> None:
    raw = (
        '```json\n{"facts": ["Another valid career accomplishment stated clearly here."]}\n```'
    )
    out = _parse_llm_facts_response(raw, max_items=10)
    assert len(out) == 1


def test_parse_llm_facts_top_level_list() -> None:
    raw = (
        '["First long enough fact about work experience here.", '
        '"Second long enough fact about the same person here."]'
    )
    out = _parse_llm_facts_response(raw, max_items=10)
    assert len(out) == 2


def test_parse_llm_facts_dedup_case_insensitive() -> None:
    raw = (
        '{"facts": ["Led a team of engineers to ship the product.", '
        '"led a team of engineers to ship the product."]}'
    )
    out = _parse_llm_facts_response(raw, max_items=10)
    assert len(out) == 1


def test_parse_llm_facts_respects_max_items() -> None:
    raw = (
        '{"facts": '
        + '["Fact number zero padded to twelve.", '
        '"Fact number one padded to twelve.", '
        '"Fact number two padded to twelve."'
        "]}"
    )
    out = _parse_llm_facts_response(raw, max_items=2)
    assert len(out) == 2

