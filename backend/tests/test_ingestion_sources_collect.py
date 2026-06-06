"""ingestion_sources_collect — pure unit tests (no DB)."""

from __future__ import annotations

import uuid

from app.collectors.base import SourceRow
from app.models.ingestion_source import IngestionSource
from app.services.ingestion_sources_collect import (
    _collector_snapshot,
    _row_dict_from_ats_targets,
    _row_dict_to_source_row,
    infer_ingestion_csv_format,
    ingestion_source_model_to_row,
)


def test_row_dict_roundtrip() -> None:
    sr = SourceRow(
        company_name="Acme Lab",
        source="cryptojobslist",
        profile_url="https://cryptojobslist.com/companies/acme",
        official_site="https://acme.xyz",
        jobs_page="https://acme.xyz/jobs",
        ats_type="greenhouse",
        ats_board_url="https://boards.greenhouse.io/acme",
        ats_slug="acme",
        cryptojobslist_fallback_jobs_page="https://cryptojobslist.com/companies/acme/jobs",
        resolution_type="validated_native_jobs_page",
        notes="test",
    )
    snap = _collector_snapshot(sr)
    back = _row_dict_to_source_row(snap)
    assert back is not None
    assert back.company_name == "Acme Lab"
    assert back.ats_slug == "acme"
    assert back.cryptojobslist_fallback_jobs_page.endswith("/jobs")


def test_infer_csv_format_jobs_vs_ats_from_headers() -> None:
    assert (
        infer_ingestion_csv_format(
            ["company_name", "source", "profile_url", "official_site"],
        )
        == "jobs_targets"
    )
    assert (
        infer_ingestion_csv_format(
            [
                "company_name",
                "ats_type",
                "ats_slug",
                "ats_board_url",
                "official_site",
                "jobs_page",
            ],
        )
        == "ats_targets"
    )
    assert infer_ingestion_csv_format(["bogus"]) is None


def test_ats_targets_row_maps_to_source_row() -> None:
    nk = {
        "company_name": "Paradex",
        "ats_type": "kula",
        "ats_slug": "paradigm",
        "ats_board_url": "https://careers.kula.ai/paradigm",
        "official_site": "https://paradex.trade",
        "jobs_page": "",
    }
    sr = _row_dict_from_ats_targets(nk)
    assert sr is not None
    assert sr.company_name == "Paradex"
    assert sr.ats_type == "kula"
    assert "kula" in sr.ats_board_url


def test_ingestion_model_collector_metadata() -> None:
    uid = uuid.UUID("00000000-0000-4000-8000-000000000001")
    sr = SourceRow(
        company_name="Ledger Co",
        jobs_page="https://ledger.com/careers",
        ats_board_url="https://jobs.lever.co/ledger",
        ats_type="lever",
    )
    row = IngestionSource(
        id=uuid.uuid4(),
        user_id=uid,
        label="Ledger Co",
        jobs_page_url=sr.jobs_page,
        careers_site_url=None,
        ats_board_url=sr.ats_board_url,
        ats_type=sr.ats_type,
        resolution_type=None,
        extra_metadata={"collector": _collector_snapshot(sr)},
    )
    out = ingestion_source_model_to_row(row)
    assert out is not None
    assert out.company_name == "Ledger Co"
    assert out.ats_type == "lever"
