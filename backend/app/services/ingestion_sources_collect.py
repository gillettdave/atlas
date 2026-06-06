"""Bulk sync of resolver CSV rows into ingestion_sources.

Supports **jobs_targets** (full SourceRow columns) and **ats_targets**
(narrow ATS export). Collector pipeline reads back via ``load_source_rows_from_db``.
"""
from __future__ import annotations

import csv
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collectors.base import SourceRow
from ..models.ingestion_source import IngestionSource


CsvSyncFormat = Literal["auto", "jobs_targets", "ats_targets"]


def _collector_snapshot(sr: SourceRow) -> dict[str, str]:
    return {k: str(v or "") for k, v in asdict(sr).items()}


def _norm_headers(row: dict[str, Any]) -> dict[str, str]:
    """Lowercase CSV header keys."""
    out: dict[str, str] = {}
    for k, v in row.items():
        key = (k or "").strip().lower()
        out[key] = str(v if v is not None else "").strip()
    return out


def infer_ingestion_csv_format(fieldnames: list[str] | None) -> str | None:
    """Return ``jobs_targets`` or ``ats_targets`` from headers, or None if unusable."""
    keys = {(x or "").strip().lower() for x in (fieldnames or [])}
    if not keys or "company_name" not in keys:
        return None
    if (
        "profile_url" in keys
        or "cryptojobslist_fallback_jobs_page" in keys
        or "source" in keys
    ):
        return "jobs_targets"
    if "ats_slug" in keys and "ats_board_url" in keys:
        return "ats_targets"
    return None


def _row_dict_to_source_row(d: dict[str, str]) -> SourceRow | None:
    name = (d.get("company_name") or "").strip()
    if not name:
        return None
    return SourceRow(
        company_name=name,
        source=(d.get("source") or "").strip(),
        profile_url=(d.get("profile_url") or "").strip(),
        official_site=(d.get("official_site") or "").strip(),
        jobs_page=(d.get("jobs_page") or "").strip(),
        ats_type=(d.get("ats_type") or "").strip(),
        ats_board_url=(d.get("ats_board_url") or "").strip(),
        ats_slug=(d.get("ats_slug") or "").strip(),
        cryptojobslist_fallback_jobs_page=(
            d.get("cryptojobslist_fallback_jobs_page") or ""
        ).strip(),
        resolution_type=(d.get("resolution_type") or "").strip(),
        notes=(d.get("notes") or "").strip(),
    )


def _row_dict_from_ats_targets(nk: dict[str, str]) -> SourceRow | None:
    """Map ``ats_targets.csv`` (company_name, ats_type, ats_slug, ...)."""
    name = (nk.get("company_name") or "").strip()
    if not name:
        return None
    return SourceRow(
        company_name=name,
        source="ats_targets_csv",
        profile_url="",
        official_site=(nk.get("official_site") or "").strip(),
        jobs_page=(nk.get("jobs_page") or "").strip(),
        ats_type=(nk.get("ats_type") or "").strip(),
        ats_board_url=(nk.get("ats_board_url") or "").strip(),
        ats_slug=(nk.get("ats_slug") or "").strip(),
        cryptojobslist_fallback_jobs_page="",
        resolution_type=("ats_targets_export"),
        notes="ats_targets_csv_sync",
    )


def ingestion_source_model_to_row(isrc: IngestionSource) -> SourceRow | None:
    """Rebuild a collector SourceRow from a DB row."""
    md: dict[str, Any] = isrc.extra_metadata or {}
    snap = md.get("collector")
    if isinstance(snap, dict) and isinstance(snap.get("company_name"), str):
        sr = _row_dict_to_source_row({str(k): str(v or "") for k, v in snap.items()})
        if sr:
            return sr
    jp = (isrc.jobs_page_url or "").strip()
    ab = (isrc.ats_board_url or "").strip()
    careers = (isrc.careers_site_url or "").strip()
    if not jp and not ab and not careers:
        return None
    return SourceRow(
        company_name=isrc.label,
        source=str(md.get("source") or "manual"),
        profile_url=str(md.get("profile_url") or ""),
        official_site=careers,
        jobs_page=jp,
        ats_type=(isrc.ats_type or ""),
        ats_board_url=ab,
        ats_slug=str(md.get("ats_slug") or ""),
        cryptojobslist_fallback_jobs_page=str(
            md.get("cryptojobslist_fallback_jobs_page") or ""
        ),
        resolution_type=(isrc.resolution_type or ""),
        notes=(isrc.notes or ""),
    )


def load_source_rows_from_db(
    db: Session, user_id: uuid.UUID, *, limit: int | None = None
) -> list[SourceRow]:
    stmt = (
        select(IngestionSource)
        .where(IngestionSource.user_id == user_id)
        .order_by(IngestionSource.label.asc())
    )
    rows = list(db.scalars(stmt).all())
    if limit is not None:
        rows = rows[:limit]
    out: list[SourceRow] = []
    for r in rows:
        sr = ingestion_source_model_to_row(r)
        if sr is not None:
            out.append(sr)
    return out


def _bulk_upsert_ingestion_pairs(
    db: Session,
    user_id: uuid.UUID,
    parsed: list[tuple[str, SourceRow]],
    *,
    stats: dict[str, Any],
    dry_run: bool,
) -> None:
    existing: dict[str, IngestionSource] = {}
    stmt = select(IngestionSource).where(IngestionSource.user_id == user_id)
    for er in db.scalars(stmt):
        existing[er.label] = er

    for lbl, sr in parsed:
        snap = _collector_snapshot(sr)
        meta_src = sr.source.strip() if (sr.source or "").strip() else "resolver"
        md: dict[str, Any] = {"source": meta_src, "collector": snap}

        jp = sr.jobs_page or ""
        fb = sr.cryptojobslist_fallback_jobs_page or ""

        if lbl in existing:
            e = existing[lbl]
            e.jobs_page_url = jp or fb or None
            e.careers_site_url = sr.official_site or None
            e.ats_board_url = sr.ats_board_url or None
            e.ats_type = sr.ats_type or None
            e.resolution_type = sr.resolution_type or None
            if sr.notes:
                e.notes = sr.notes
            e.extra_metadata = md
            stats["updated"] += 1
        else:
            e = IngestionSource(
                user_id=user_id,
                label=lbl,
                notes=sr.notes or None,
                jobs_page_url=jp or fb or None,
                careers_site_url=sr.official_site or None,
                ats_board_url=sr.ats_board_url or None,
                ats_type=sr.ats_type or None,
                resolution_type=sr.resolution_type or None,
                extra_metadata=md,
            )
            db.add(e)
            existing[lbl] = e
            stats["created"] += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()


def sync_jobs_targets_csv(
    *,
    db: Session,
    user_id: uuid.UUID,
    csv_path: Path,
    limit: int | None = None,
    dry_run: bool = False,
    csv_format: CsvSyncFormat = "auto",
) -> dict[str, Any]:
    """Parse CSV and upsert ``ingestion_sources`` for this user.

    When ``csv_format`` is ``"auto"``, headers choose between **jobs_targets**
    (full resolver) and **ats_targets** (narrow board export).
    """
    if not csv_path.is_file():
        raise FileNotFoundError(str(csv_path))

    stats: dict[str, Any] = {
        "total_rows_read": 0,
        "created": 0,
        "updated": 0,
        "skipped_empty_label": 0,
        "skipped_unrecognized_csv": False,
        "dry_run": dry_run,
        "csv_format_used": csv_format,
    }

    parsed: list[tuple[str, SourceRow]] = []

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if csv_format != "auto":
            inferred: str = csv_format
        else:
            inferred_o = infer_ingestion_csv_format(reader.fieldnames)
            if inferred_o is None:
                stats["skipped_unrecognized_csv"] = True
                return stats
            inferred = inferred_o
        stats["csv_format_used"] = inferred

        for row in reader:
            stats["total_rows_read"] += 1
            if limit is not None and len(parsed) >= limit:
                break
            nk = _norm_headers(row)
            if inferred == "ats_targets":
                sr = _row_dict_from_ats_targets(nk)
            else:
                sr = _row_dict_to_source_row(nk)

            if sr is None:
                stats["skipped_empty_label"] += 1
                continue
            lbl = sr.company_name.strip()[:200]
            parsed.append((lbl, sr))

    _bulk_upsert_ingestion_pairs(db, user_id, parsed, stats=stats, dry_run=dry_run)
    return stats
