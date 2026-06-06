"""Search + pagination for tenant ingestion_sources (GET /imports/sources)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models.ingestion_source import IngestionSource


def escape_ilike_pattern(term: str) -> str:
    """Escape `%`, `_`, and `\\` for use in Postgres ILIKE with ``ESCAPE '\\'``."""
    return (
        term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def list_ingestion_sources(
    db: Session,
    user_id: uuid.UUID,
    *,
    q: str | None,
    limit: int | None,
    offset: int,
) -> tuple[int, list[IngestionSource]]:
    stmt = (
        select(IngestionSource)
        .where(IngestionSource.user_id == user_id)
        .order_by(IngestionSource.created_at.desc())
    )
    count_stmt = select(func.count(IngestionSource.id)).where(
        IngestionSource.user_id == user_id,
    )

    qt = (q or "").strip()
    if qt:
        pat = f"%{escape_ilike_pattern(qt)}%"
        esc = "\\"
        match = or_(
            IngestionSource.label.ilike(pat, escape=esc),
            func.coalesce(IngestionSource.notes, "").ilike(pat, escape=esc),
            func.coalesce(IngestionSource.jobs_page_url, "").ilike(pat, escape=esc),
            func.coalesce(IngestionSource.careers_site_url, "").ilike(pat, escape=esc),
            func.coalesce(IngestionSource.ats_board_url, "").ilike(pat, escape=esc),
            func.coalesce(IngestionSource.ats_type, "").ilike(pat, escape=esc),
            func.coalesce(IngestionSource.resolution_type, "").ilike(pat, escape=esc),
        )
        stmt = stmt.where(match)
        count_stmt = count_stmt.where(match)

    total = int(db.scalar(count_stmt) or 0)

    eff_offset = offset if offset > 0 else 0
    if limit is not None:
        stmt = stmt.offset(eff_offset).limit(limit)
    elif eff_offset > 0:
        stmt = stmt.offset(eff_offset)

    rows = list(db.scalars(stmt).all())
    return total, rows
