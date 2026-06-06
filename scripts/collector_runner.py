#!/usr/bin/env python3
"""Collector runner — drives a collector and streams raw records into the Atlas API.

Usage (from repo root, with backend/.venv active):

    python scripts\\collector_runner.py --input-csv path\\to\\sources.csv
    python scripts\\collector_runner.py --input-csv path\\to\\sources.csv --limit 20
    python scripts\\collector_runner.py --input-csv path\\to\\sources.csv --then-import
    python scripts\\collector_runner.py --input-csv path\\to\\sources.csv --then-import --then-rank
    python scripts\\collector_runner.py --input-csv path\\to\\sources.csv --then-import --then-rank --then-digest
    python scripts\\collector_runner.py --input-csv path\\to\\sources.csv --dry-run

Design:
- Opens an ingestion_run via POST /collectors/run.
- Iterates SourceRows, calls the collector, buffers raw records.
- Posts batches to POST /collectors/raw-events.
- Finalizes the run.
- Optionally triggers POST /imports/process-pending to run cleaner_v2
  immediately so canonical jobs are visible when the run completes.

No business logic lives here. Runner only orchestrates HTTP + progress.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

# Make `app` importable when running from repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.collectors.base import CollectionStats, RawCollectedRecord, SourceRow  # noqa: E402
from app.collectors.web3_ats import collect_all, load_sources  # noqa: E402
from app.config import get_settings  # noqa: E402


def _default_api_base() -> str:
    s = get_settings()
    return f"http://{s.api_host}:{s.api_port}"


def _log(msg: str) -> None:
    print(msg, flush=True)


async def _open_run(
    client: httpx.AsyncClient, source_name: str, source_type: str, metadata: dict
) -> str:
    resp = await client.post(
        "/collectors/run",
        json={
            "source_name": source_name,
            "source_type": source_type,
            "metadata": metadata,
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


async def _submit_batch(
    client: httpx.AsyncClient,
    ingestion_run_id: str,
    records: list[RawCollectedRecord],
) -> dict:
    payload = {
        "ingestion_run_id": ingestion_run_id,
        "events": [r.to_api_payload() for r in records],
    }
    resp = await client.post("/collectors/raw-events", json=payload)
    resp.raise_for_status()
    return resp.json()


async def _finalize_run(client: httpx.AsyncClient, ingestion_run_id: str) -> dict:
    resp = await client.post(f"/collectors/run/{ingestion_run_id}/finalize")
    resp.raise_for_status()
    return resp.json()


async def _process_pending(
    client: httpx.AsyncClient, ingestion_run_id: str, limit: int = 5000
) -> dict:
    resp = await client.post(
        "/imports/process-pending",
        json={"ingestion_run_id": ingestion_run_id, "limit": limit},
    )
    resp.raise_for_status()
    return resp.json()


async def _rescore(
    client: httpx.AsyncClient,
    *,
    provider: str | None = None,
    only_active: bool = True,
    only_unscored: bool = False,
    limit: int | None = None,
) -> dict:
    payload: dict = {"only_active": only_active, "only_unscored": only_unscored}
    if provider:
        payload["provider"] = provider
    if limit is not None:
        payload["limit"] = limit
    resp = await client.post("/imports/rescore", json=payload)
    resp.raise_for_status()
    return resp.json()


async def _build_digest(
    client: httpx.AsyncClient,
    *,
    digest_type: str,
    fresh_hours: int,
    fresh_limit: int,
    gem_limit: int,
    per_company_cap: int,
) -> dict:
    payload = {
        "digest_type": digest_type,
        "fresh_hours": fresh_hours,
        "fresh_limit": fresh_limit,
        "gem_limit": gem_limit,
        "per_company_cap": per_company_cap,
    }
    resp = await client.post("/digests/generate", json=payload)
    resp.raise_for_status()
    return resp.json()


def _progress_line(idx: int, total: int, row: SourceRow) -> None:
    _log(f"[collect] {idx}/{total}  {row.company_name}  ({row.ats_type or row.resolution_type or 'auto'})")


async def run_async(args: argparse.Namespace) -> int:
    sources = load_sources(Path(args.input_csv), limit=args.limit)
    if not sources:
        _log("no sources loaded — nothing to do")
        return 2

    _log(f"[runner] loaded {len(sources)} sources from {args.input_csv}")
    _log(f"[runner] api base: {args.api_base}")
    _log(f"[runner] batch size: {args.batch_size}  headless: {not args.show_browser}  dry-run: {args.dry_run}")

    stats = CollectionStats(sources_attempted=len(sources))
    started = time.time()

    headers = {}
    if args.admin_token:
        headers["X-Admin-Token"] = args.admin_token

    # ---- dry run short-circuit --------------------------------------------
    if args.dry_run:
        async for row, records, reason in collect_all(
            sources, headless=not args.show_browser, progress_cb=_progress_line,
        ):
            if records:
                stats.sources_with_records += 1
                for r in records:
                    stats.record(r.provider)
                _log(f"  -> {len(records)} records, first: {records[0].raw_payload.get('job_title', '')[:80]}")
            else:
                stats.fail(row.company_name, row.jobs_page or row.ats_board_url or "", reason or "empty")
                _log(f"  -> 0 records  reason={reason}")
        _print_summary(stats, started, ingestion_run_id=None, import_result=None)
        return 0

    # ---- live run ---------------------------------------------------------
    async with httpx.AsyncClient(base_url=args.api_base, headers=headers, timeout=60.0) as client:
        # Health check first — fail fast if the API isn't where we think.
        try:
            health = await client.get("/health")
            health.raise_for_status()
        except Exception as e:
            _log(f"[runner] FATAL: API not reachable at {args.api_base}: {e}")
            return 3

        ingestion_run_id = await _open_run(
            client,
            source_name=args.source_name,
            source_type=args.source_type,
            metadata={
                "input_csv": str(Path(args.input_csv).resolve()),
                "sources_total": len(sources),
                "limit": args.limit,
            },
        )
        _log(f"[runner] opened ingestion_run {ingestion_run_id}")

        buffer: list[RawCollectedRecord] = []
        total_inserted = 0
        total_failed = 0

        async def flush() -> None:
            nonlocal total_inserted, total_failed, buffer
            if not buffer:
                return
            try:
                result = await _submit_batch(client, ingestion_run_id, buffer)
                total_inserted += result.get("inserted", 0)
                total_failed += result.get("failed", 0)
                _log(
                    f"[runner] flushed batch: inserted={result.get('inserted')}"
                    f" failed={result.get('failed')} (cumulative inserted={total_inserted})"
                )
            except httpx.HTTPStatusError as e:
                _log(f"[runner] batch submit HTTP {e.response.status_code}: {e.response.text[:300]}")
                total_failed += len(buffer)
            except Exception as e:  # noqa: BLE001
                _log(f"[runner] batch submit error: {type(e).__name__}: {e}")
                total_failed += len(buffer)
            finally:
                buffer = []

        async for row, records, reason in collect_all(
            sources, headless=not args.show_browser, progress_cb=_progress_line,
        ):
            if records:
                stats.sources_with_records += 1
                for r in records:
                    stats.record(r.provider)
                buffer.extend(records)
                if len(buffer) >= args.batch_size:
                    await flush()
                _log(f"  -> {len(records)} records collected")
            else:
                stats.fail(row.company_name, row.jobs_page or row.ats_board_url or "", reason or "empty")
                _log(f"  -> 0 records  reason={reason}")

        await flush()

        final = await _finalize_run(client, ingestion_run_id)
        _log(f"[runner] finalized run: status={final.get('status')} rows_seen={final.get('rows_seen')}")

        import_result = None
        if args.then_import:
            _log("[runner] running cleaner (process-pending) against this run ...")
            import_result = await _process_pending(client, ingestion_run_id)
            _log(f"[runner] cleaner result: {import_result}")

        rank_result = None
        if args.then_rank:
            if not args.then_import:
                _log(
                    "[runner] NOTE: --then-rank without --then-import will "
                    "rescore any previously imported jobs (no new jobs from this run yet)."
                )
            _log("[runner] running ranker (rescore) ...")
            rank_result = await _rescore(
                client,
                only_active=True,
                only_unscored=args.rank_only_unscored,
                limit=args.rank_limit,
            )
            _log(f"[runner] ranker result: {rank_result}")

        digest_result = None
        if args.then_digest:
            _log("[runner] building digest ...")
            digest_result = await _build_digest(
                client,
                digest_type=args.digest_type,
                fresh_hours=args.digest_fresh_hours,
                fresh_limit=args.digest_fresh_limit,
                gem_limit=args.digest_gem_limit,
                per_company_cap=args.digest_per_company_cap,
            )
            _log(
                f"[runner] digest {digest_result.get('id')}: "
                f"fresh={len(digest_result.get('fresh') or [])} "
                f"gems={len(digest_result.get('hidden_gems') or [])}"
            )

        _print_summary(
            stats, started, ingestion_run_id, import_result, rank_result, digest_result
        )

    return 0


def _print_summary(
    stats: CollectionStats,
    started: float,
    ingestion_run_id: str | None,
    import_result: dict | None,
    rank_result: dict | None = None,
    digest_result: dict | None = None,
) -> None:
    elapsed = time.time() - started
    _log("")
    _log("==================== summary ====================")
    if ingestion_run_id:
        _log(f"ingestion_run_id         : {ingestion_run_id}")
    _log(f"sources_attempted        : {stats.sources_attempted}")
    _log(f"sources_with_records     : {stats.sources_with_records}")
    _log(f"sources_failed           : {stats.sources_failed}")
    _log(f"records_collected        : {stats.records_collected}")
    _log(f"by_provider              : {json.dumps(stats.by_provider, sort_keys=True)}")
    if import_result:
        _log(f"cleaner.processed        : {import_result.get('processed')}")
        _log(f"cleaner.new_canonical    : {import_result.get('new_canonical')}")
        _log(f"cleaner.matched_existing : {import_result.get('matched_existing')}")
        _log(f"cleaner.needs_review     : {import_result.get('possible_duplicate_review')}")
        _log(f"cleaner.rejected         : {import_result.get('rejected_low_quality')}")
        _log(f"cleaner.failed           : {import_result.get('failed')}")
    if rank_result:
        _log(f"ranker.scored            : {rank_result.get('scored')}")
        _log(f"ranker.failed            : {rank_result.get('failed')}")
        _log(f"ranker.hidden_gems       : {rank_result.get('hidden_gems')}")
        _log(f"ranker.by_bucket         : {json.dumps(rank_result.get('by_bucket') or {}, sort_keys=True)}")
    if digest_result:
        ds = digest_result.get("stats") or {}
        _log(f"digest.id                : {digest_result.get('id')}")
        _log(f"digest.type              : {digest_result.get('digest_type')}")
        _log(f"digest.fresh             : {ds.get('fresh_selected')}"
             f" (from {ds.get('fresh_candidates')} candidates)")
        _log(f"digest.hidden_gems       : {ds.get('gem_selected')}"
             f" (from {ds.get('gem_candidates')} candidates)")
        _log(f"digest.dropped_by_cap    : {ds.get('dropped_by_cap')}")
    _log(f"elapsed                  : {elapsed:.1f}s")
    _log("==================================================")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Drive the Web3 ATS collector and stream raw records into the Atlas API.",
    )
    p.add_argument("--input-csv", required=True, help="CSV of SourceRow entries to collect from.")
    p.add_argument("--limit", type=int, default=None, help="Process at most N sources.")
    p.add_argument(
        "--api-base", default=None,
        help="Atlas API base URL. Defaults to http://{api_host}:{api_port} from backend/.env.",
    )
    p.add_argument(
        "--admin-token", default=None,
        help="X-Admin-Token for the API. Not required when ATLAS_ENV=dev.",
    )
    p.add_argument(
        "--source-name", default="web3_ats_collector_v5",
        help="ingestion_run.source_name.",
    )
    p.add_argument(
        "--source-type", default="ats",
        help="ingestion_run.source_type.",
    )
    p.add_argument(
        "--batch-size", type=int, default=50,
        help="How many raw records to POST per batch.",
    )
    p.add_argument(
        "--show-browser", action="store_true",
        help="Run Playwright with a visible browser window.",
    )
    p.add_argument(
        "--then-import", action="store_true",
        help="After finalizing, run /imports/process-pending for this run.",
    )
    p.add_argument(
        "--then-rank", action="store_true",
        help="After import, run /imports/rescore (ranker v1) to update ranking_score/quality_score.",
    )
    p.add_argument(
        "--rank-only-unscored", action="store_true",
        help="With --then-rank: only score jobs that have never been scored.",
    )
    p.add_argument(
        "--rank-limit", type=int, default=None,
        help="With --then-rank: cap rows processed by the ranker.",
    )
    p.add_argument(
        "--then-digest", action="store_true",
        help="After ranking, build and persist a daily digest via /digests/generate.",
    )
    p.add_argument(
        "--digest-type", default="daily",
        help="Digest type tag: daily | weekly | hidden_gems | custom.",
    )
    p.add_argument(
        "--digest-fresh-hours", type=int, default=48,
        help="Fresh-lane window in hours.",
    )
    p.add_argument(
        "--digest-fresh-limit", type=int, default=15,
        help="Max items in the fresh lane.",
    )
    p.add_argument(
        "--digest-gem-limit", type=int, default=10,
        help="Max items in the hidden-gem lane.",
    )
    p.add_argument(
        "--digest-per-company-cap", type=int, default=3,
        help="Max items from any single company across the whole digest.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Collect only; do not open a run or POST anything.",
    )

    args = p.parse_args()
    if args.api_base is None:
        args.api_base = _default_api_base()
    return args


def main() -> int:
    args = parse_args()
    return asyncio.run(run_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
