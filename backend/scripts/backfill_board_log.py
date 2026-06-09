"""Backfill board_collection_log from raw_job_events.

Reads the most recent ingestion timestamp per source_url from raw_job_events,
then inserts or updates board_collection_log so the skip-if-fresh logic knows
which boards have already been collected.

Run once after deploying the board_collection_log migration.

Usage:
    python scripts/backfill_board_log.py
    python scripts/backfill_board_log.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ATS types we want to track freshness for
TRACKED_PROVIDERS = {"greenhouse", "lever", "ashby"}


def main(dry_run: bool = False) -> None:
    from sqlalchemy import text
    from app.db import SessionLocal
    from app.models.board_collection_log import BoardCollectionLog

    with SessionLocal() as db:
        # Get max ingested_at per source_url for tracked providers
        rows = db.execute(text("""
            SELECT
                source_url,
                provider,
                MAX(created_at) AS last_seen
            FROM raw_job_events
            WHERE provider IN ('greenhouse', 'lever', 'ashby')
              AND source_url IS NOT NULL
              AND source_url != ''
            GROUP BY source_url, provider
            ORDER BY source_url
        """)).fetchall()

        log.info("Found %d distinct boards in raw_job_events", len(rows))

        inserted = 0
        updated = 0

        for row in rows:
            source_url: str = row.source_url
            provider: str = row.provider
            last_seen = row.last_seen

            existing = db.query(BoardCollectionLog).filter_by(
                ats_board_url=source_url
            ).first()

            if existing is None:
                if not dry_run:
                    db.add(BoardCollectionLog(
                        ats_board_url=source_url,
                        ats_type=provider,
                        last_collected_at=last_seen,
                        consecutive_timeouts=0,
                        total_runs=1,
                        total_records=0,  # we don't know historic count
                    ))
                inserted += 1
                log.debug("INSERT %s (%s) last=%s", source_url, provider, last_seen)
            else:
                # Only update if we have a newer timestamp
                existing_lc = existing.last_collected_at
                if existing_lc is None or (last_seen and last_seen > existing_lc):
                    if not dry_run:
                        existing.last_collected_at = last_seen
                        existing.ats_type = provider
                    updated += 1
                    log.debug("UPDATE %s last=%s", source_url, last_seen)

        if not dry_run:
            db.commit()

        log.info(
            "%s board_collection_log: inserted=%d  updated=%d  total=%d",
            "DRY RUN —" if dry_run else "Done —",
            inserted, updated, inserted + updated,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
