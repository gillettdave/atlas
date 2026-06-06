"""DOCX/ZIP helpers for application packages."""

from __future__ import annotations

import pytest

# `python-docx` provides the `docx` package; skip this file if not installed
# (avoid collection error when deps are incomplete or a different interpreter runs pytest).
pytest.importorskip("docx")

import uuid
import zipfile
from io import BytesIO

from app.services.application_package_docx import (
    markdown_to_docx_bytes,
    single_application_package_docx,
    zip_application_package_docx,
)


def test_markdown_to_docx_produces_zip_container() -> None:
    b = markdown_to_docx_bytes("# Title\n\n- Item one\nBody.\n")
    assert b.startswith(b"PK")
    assert len(b) > 120


def test_zip_application_package_docx_contains_three_docx_files() -> None:
    pkg = type(
        "Pkg",
        (),
        {
            "resume_markdown": "# Resume\nHi",
            "cover_letter_markdown": "# Letter\nYo",
            "strategy_notes": "# Notes\nOk",
            "job_id": uuid.UUID("00000000-0000-4000-8000-000000000001"),
            "version": 3,
        },
    )
    blob, fname = zip_application_package_docx(pkg)
    assert fname.endswith("_docx.zip")
    buf = BytesIO(blob)
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert {"resume_draft.docx", "cover_letter_draft.docx", "strategy_notes.docx"} <= names


def test_single_application_package_docx_resume_starts_with_pk_zip() -> None:
    pkg = type(
        "Pkg",
        (),
        {
            "resume_markdown": "# R\nHello",
            "cover_letter_markdown": "# C\nYo",
            "strategy_notes": "# S\nPlan",
            "job_id": uuid.UUID("00000000-0000-4000-8000-000000000001"),
            "version": 2,
        },
    )
    blob, fname = single_application_package_docx(pkg, "resume")  # type: ignore[arg-type]
    assert blob.startswith(b"PK")
    assert fname.endswith("resume_draft.docx")
