"""Run the ATS board collector against company_ats_sources.csv.

Collects all Greenhouse / Ashby / Lever boards, imports raw events,
and rescores jobs. Does NOT generate a digest.

Usage:
    python scripts/run_ats_collection.py
    python scripts/run_ats_collection.py --limit 50   # test with first 50 boards
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

from app.services.collector_pipeline import run_collector_pipeline

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap number of boards (for testing)")
    args = parser.parse_args()

    csv_path = Path(__file__).parent / "company_ats_sources.csv"

    print(f"Starting ATS collection from {csv_path}")
    print(f"Board limit: {args.limit or 'all'}")

    result = run_collector_pipeline(
        input_csv=csv_path,
        source_limit=args.limit,
        then_import=True,
        then_rank=True,
        rank_only_unscored=True,   # only score new jobs
        then_digest=False,
        progress_log=True,
    )

    print(f"\n{'='*50}")
    print(f"Done in {result.duration_sec:.0f}s")
    print(f"  Sources attempted : {result.sources_attempted}")
    print(f"  Records inserted  : {result.records_inserted}")
    print(f"  Import run ID     : {result.ingestion_run_id}")
    print(f"  OK                : {result.ok}")
    if result.error:
        print(f"  Error             : {result.error}")
