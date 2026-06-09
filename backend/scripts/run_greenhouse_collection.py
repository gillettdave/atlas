"""Collect from remaining Greenhouse boards using subprocess-per-board isolation.

Each board runs in a fresh subprocess with a hard timeout. If it hangs,
the OS kills it — guaranteed, even on Windows. No more silent stalls.

Progress is persisted to greenhouse_done_slugs.txt after every board so
restarts skip already-completed slugs automatically.

Usage:
    python scripts/run_greenhouse_collection.py
    python scripts/run_greenhouse_collection.py --timeout 90
    python scripts/run_greenhouse_collection.py --limit 50
    python scripts/run_greenhouse_collection.py --ats-type ashby --csv scripts/company_ats_sources.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
WORKER = SCRIPT_DIR / "collect_one_board.py"
PYTHON = Path(sys.executable)
DEFAULT_DONE_FILE = SCRIPT_DIR / "greenhouse_done_slugs.txt"


# ─── persistence ─────────────────────────────────────────────────────────────

def load_done_slugs(done_file: Path) -> set[str]:
    if done_file.exists():
        return set(l.strip() for l in done_file.read_text().splitlines() if l.strip())
    return set()


def save_done_slug(slug: str, done_file: Path) -> None:
    with done_file.open("a") as fh:
        fh.write(slug + "\n")


# ─── subprocess collection ────────────────────────────────────────────────────

def collect_one(ats_type: str, board_url: str, company_name: str,
                slug: str, timeout_secs: int) -> tuple[list, str]:
    """Run collect_one_board.py in a subprocess with a hard timeout.

    Returns (records_as_dicts, reason). On timeout or crash → ([], reason).
    """
    try:
        result = subprocess.run(
            [str(PYTHON), str(WORKER), ats_type, board_url, company_name, slug],
            capture_output=True,
            text=True,
            timeout=timeout_secs,
        )
        if result.stderr.strip():
            log.debug("  worker stderr: %s", result.stderr.strip()[:300])

        if result.returncode != 0 and not result.stdout.strip():
            return [], f"worker_exit_{result.returncode}"

        data = json.loads(result.stdout.strip())
        return data.get("records", []), data.get("reason", "ok")

    except subprocess.TimeoutExpired:
        return [], f"timeout_{timeout_secs}s"
    except json.JSONDecodeError as e:
        return [], f"bad_json:{str(e)[:80]}"
    except Exception as exc:  # noqa: BLE001
        return [], f"error:{type(exc).__name__}:{str(exc)[:120]}"


# ─── API helpers ──────────────────────────────────────────────────────────────

def open_ingestion_run(api_base: str) -> str:
    import httpx
    resp = httpx.post(
        f"{api_base}/collectors/run",
        json={"source_name": "greenhouse_batch", "source_type": "ats_greenhouse"},
        headers={"Authorization": "Bearer dev-admin-token"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def submit_records(records: list, api_base: str, run_id: str) -> int:
    if not records:
        return 0
    import httpx
    resp = httpx.post(
        f"{api_base}/collectors/raw-events",
        json={
            "ingestion_run_id": run_id,
            "events": records,
            "finalize": False,
        },
        headers={"Authorization": "Bearer dev-admin-token"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("inserted", 0)


def trigger_import(api_base: str) -> dict:
    import httpx
    resp = httpx.post(
        f"{api_base}/imports/process-pending",
        json={"limit": 10000, "then_rank": True, "rank_only_unscored": True},
        headers={"Authorization": "Bearer dev-admin-token"},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()


def finalize_run(api_base: str, run_id: str) -> None:
    import httpx
    try:
        httpx.post(
            f"{api_base}/collectors/run/{run_id}/finalize",
            headers={"Authorization": "Bearer dev-admin-token"},
            timeout=15,
        )
    except Exception:
        pass


# ─── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(SCRIPT_DIR / "greenhouse_remaining.csv"))
    parser.add_argument("--ats-type", default=None,
                        help="Filter to this ATS type only (e.g. greenhouse, lever, ashby)")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--done-file", default=None,
                        help="Path to done-slugs file (default: greenhouse_done_slugs.txt)")
    args = parser.parse_args()

    done_file = Path(args.done_file) if args.done_file else DEFAULT_DONE_FILE

    csv_path = Path(args.csv)
    all_boards = list(csv.DictReader(csv_path.open(encoding="utf-8")))

    # Filter by ATS type if requested
    if args.ats_type:
        all_boards = [b for b in all_boards if b.get("ats_type", "").lower() == args.ats_type.lower()]

    if args.limit:
        all_boards = all_boards[:args.limit]

    done_slugs = load_done_slugs(done_file)
    pending = [b for b in all_boards if b.get("ats_slug", "").strip() not in done_slugs]

    log.info("CSV: %d boards | filtered_type: %s | done: %d | pending: %d | done_file: %s",
             len(all_boards), args.ats_type or "all", len(done_slugs), len(pending), done_file.name)

    if not pending:
        log.info("Nothing to do — all boards already collected.")
        sys.exit(0)

    api_base = args.api_base.rstrip("/")
    run_id = open_ingestion_run(api_base)
    log.info("Ingestion run: %s", run_id)

    total_submitted = 0
    total_new_jobs = 0
    timed_out = 0
    errored = 0
    start = time.monotonic()

    for i, board in enumerate(pending, 1):
        slug = board.get("ats_slug", "").strip()
        url = board.get("ats_board_url", "").strip()
        name = board.get("company_name", slug).strip()
        ats_type = board.get("ats_type", "greenhouse").strip()

        log.info("[%d/%d]  %-40s (%s)", i, len(pending), name, slug)

        records, reason = collect_one(ats_type, url, name, slug, args.timeout)

        if records:
            inserted = submit_records(records, api_base, run_id)
            total_submitted += inserted
            log.info("  → %d records (reason: %s)", len(records), reason)
        else:
            if "timeout" in reason:
                timed_out += 1
                log.warning("  → TIMEOUT after %ds — board skipped", args.timeout)
            elif "error" in reason:
                errored += 1
                log.warning("  → error: %s", reason)
            else:
                log.info("  → 0 records (%s)", reason)

        save_done_slug(slug, done_file)

        if i % args.batch_size == 0:
            elapsed = time.monotonic() - start
            log.info("--- batch import (%d done, %.0fm elapsed) ---", i, elapsed / 60)
            try:
                result = trigger_import(api_base)
                new = result.get("new_canonical", 0)
                total_new_jobs += new
                log.info("  → %d new jobs (total: %d)", new, total_new_jobs)
            except Exception as exc:
                log.warning("  import failed: %s", exc)

    # Final import
    log.info("--- final import ---")
    try:
        result = trigger_import(api_base)
        new = result.get("new_canonical", 0)
        total_new_jobs += new
        log.info("Final import: %d new jobs", new)
    except Exception as exc:
        log.warning("Final import failed: %s", exc)

    finalize_run(api_base, run_id)

    elapsed = time.monotonic() - start
    log.info("=" * 60)
    log.info(
        "COMPLETE  boards=%d  timed_out=%d  errored=%d  submitted=%d  new_jobs=%d  time=%.0fm",
        len(pending), timed_out, errored, total_submitted, total_new_jobs, elapsed / 60,
    )
