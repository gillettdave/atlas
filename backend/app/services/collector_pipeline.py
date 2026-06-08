"""collector_pipeline — end-to-end collect + import + rank (+ optional digest).

Used by the collector runner CLI and by Sprint M.1 scheduled / API-triggered
runs. Drives the same HTTP surface the script uses (`/collectors/*`,
`/imports/*`, `/digests/generate`) so business logic stays single-sourced
in the FastAPI app.

Runs Playwright in-process via the async `collect_all` loop; only call
from worker threads or dedicated processes if you use the background
scheduler loop to avoid blocking the main uvicorn event loop.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional, TypeVar

import httpx

from ..collectors.base import RawCollectedRecord, SourceRow
from ..collectors.web3_ats import collect_all, load_sources
from ..config import Settings, get_settings
from ..db import SessionLocal
from ..models.candidate_profile import CandidateProfile

logger = logging.getLogger("atlas.collector_pipeline")

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Location context — loaded from candidate_profiles at pipeline start
# ---------------------------------------------------------------------------

@dataclass
class LocationContext:
    search_mode: str = "remote"       # "remote"|"local"|"both"|"target"|"all"
    home_city: str = ""
    search_radius_km: int = 50
    target_cities: list[str] = field(default_factory=list)

    @property
    def is_location_aware(self) -> bool:
        return self.search_mode in ("local", "both", "target")


def _load_location_context() -> LocationContext:
    """Load search location preferences from the candidate profile.

    Returns default (remote-only) context on any error so the pipeline
    always degrades gracefully if the DB is unavailable or pre-migration.
    """
    try:
        db = SessionLocal()
        try:
            row = db.query(CandidateProfile).first()
            if row is None:
                return LocationContext()
            return LocationContext(
                search_mode=row.search_mode or "remote",
                home_city=row.home_city or "",
                search_radius_km=row.search_radius_km or 50,
                target_cities=list(row.target_cities or []),
            )
        finally:
            db.close()
    except Exception:
        logger.debug("location_context: DB unavailable, using remote-only default")
        return LocationContext()


# ATS board providers whose records should be location-filtered in local/target modes.
_ATS_BOARD_PROVIDERS = frozenset({
    "greenhouse", "lever", "ashby", "smartrecruiters",
    "workable", "teamtailor", "kula", "native_jobs_page",
})


def _ats_location_matches(location: str, ctx: LocationContext) -> bool:
    """Return True if an ATS board record should be kept given the location context.

    Only called when ctx.search_mode is "local" or "target". For all other
    modes every ATS record passes through unchanged.

    No-location jobs are always kept — they may be remote-friendly roles that
    simply omit the field.
    """
    if not location:
        return True  # unknown location → keep

    loc = location.lower()

    if ctx.search_mode == "local" or ctx.search_mode == "both":
        if "remote" in loc:
            return ctx.search_mode == "both"
        if not ctx.home_city:
            return True  # no home city configured — don't filter
        city_lower = ctx.home_city.lower()
        # Match if any comma-separated segment of home_city appears in the location
        return any(seg.strip() in loc for seg in city_lower.split(",") if seg.strip())

    if ctx.search_mode == "target":
        if "remote" in loc:
            return False  # target mode = specific cities only
        return any(t.lower() in loc for t in ctx.target_cities if t)

    return True


# ---------------------------------------------------------------------------
# Pipeline cancel flag — thread-safe, set by POST /pipeline/cancel
# ---------------------------------------------------------------------------

_cancel_event = threading.Event()
_pipeline_running = threading.Event()


def request_cancel() -> None:
    """Signal the running pipeline to stop collecting and proceed to digest."""
    _cancel_event.set()


def clear_cancel() -> None:
    """Reset before a new pipeline run starts."""
    _cancel_event.clear()


def set_running(running: bool) -> None:
    if running:
        _pipeline_running.set()
    else:
        _pipeline_running.clear()


def is_running() -> bool:
    return _pipeline_running.is_set()


def is_cancel_requested() -> bool:
    return _cancel_event.is_set()

# Server / rate-limit statuses worth retrying for same-process localhost API calls.
_PIPELINE_RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _transient_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _PIPELINE_RETRY_STATUSES
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
            httpx.ProxyError,
        ),
    )


async def _retry_api(operation: str, coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Expose transient API failures so scheduled runs heal from short blips."""

    s = get_settings()
    attempts = max(1, int(s.collector_pipeline_http_max_attempts))
    base = float(s.collector_pipeline_http_base_seconds)
    cap_wait = float(s.collector_pipeline_http_max_wait_seconds)
    delay = base
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except BaseException as e:
            last_exc = e
            should_retry = _transient_http_error(e)
            if not should_retry or attempt >= attempts - 1:
                raise
            jitter = random.uniform(0.0, min(1.0, delay * 0.22))
            wait_s = min(cap_wait, delay + jitter)
            logger.warning(
                "collector_pipeline %s transient %s (%s); retry %s/%s in %.2fs",
                operation,
                type(e).__name__,
                e,
                attempt + 1,
                attempts,
                wait_s,
            )
            await asyncio.sleep(wait_s)
            delay = min(cap_wait, delay * 2)
    raise AssertionError("retry loop exited without return") from last_exc


def _repo_root() -> Path:
    s = get_settings()
    if s.repo_root:
        return Path(s.repo_root).resolve()
    # backend/app/services -> four parents to repo root
    return Path(__file__).resolve().parent.parent.parent.parent


def resolve_input_csv_path(stored: str) -> Path:
    """`stored` is either absolute or relative to the project repo root."""
    p = Path(stored.strip())
    if p.is_absolute():
        return p
    return _repo_root() / p


@dataclass
class CollectorPipelineResult:
    ok: bool
    error: Optional[str] = None
    duration_sec: float = 0.0
    input_csv: str = ""
    sources_attempted: int = 0
    sources_with_records: int = 0
    records_inserted: int = 0
    records_failed: int = 0
    ingestion_run_id: Optional[uuid.UUID] = None
    import_processed: Optional[int] = None
    new_canonical: Optional[int] = None
    rank_scored: Optional[int] = None
    digest_id: Optional[uuid.UUID] = None
    by_provider: dict[str, int] = field(default_factory=dict)

    def to_details(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ok": self.ok,
            "error": self.error,
            "input_csv": self.input_csv,
            "sources_attempted": self.sources_attempted,
            "sources_with_records": self.sources_with_records,
            "records_inserted": self.records_inserted,
            "import_processed": self.import_processed,
            "new_canonical": self.new_canonical,
            "rank_scored": self.rank_scored,
            "duration_sec": self.duration_sec,
            "by_provider": self.by_provider,
        }
        if self.ingestion_run_id:
            d["ingestion_run_id"] = str(self.ingestion_run_id)
        if self.digest_id:
            d["digest_id"] = str(self.digest_id)
        return d


def _api_base() -> str:
    s = get_settings()
    return f"http://{s.api_host}:{s.api_port}"


def _admin_headers() -> dict[str, str]:
    tok = (get_settings().admin_token or "").strip()
    if not tok:
        return {}
    return {"X-Admin-Token": tok}


# Long runs: many sources + browser.
_HTTP_TIMEOUT = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=30.0)


async def _open_run(
    client: httpx.AsyncClient, source_name: str, source_type: str, metadata: dict
) -> str:
    async def _call() -> str:
        resp = await client.post(
            "/collectors/run",
            json={
                "source_name": source_name,
                "source_type": source_type,
                "metadata": metadata,
            },
        )
        resp.raise_for_status()
        return str(resp.json()["id"])

    return await _retry_api("open_run", _call)


async def _submit_batch(
    client: httpx.AsyncClient, ingestion_run_id: str, records: list[RawCollectedRecord]
) -> dict:
    async def _call() -> dict:
        payload = {
            "ingestion_run_id": ingestion_run_id,
            "events": [r.to_api_payload() for r in records],
        }
        resp = await client.post("/collectors/raw-events", json=payload)
        resp.raise_for_status()
        return resp.json()

    return await _retry_api("raw_events_batch", _call)


async def _finalize_run(client: httpx.AsyncClient, ingestion_run_id: str) -> dict:
    async def _call() -> dict:
        resp = await client.post(f"/collectors/run/{ingestion_run_id}/finalize")
        resp.raise_for_status()
        return resp.json()

    return await _retry_api("finalize_run", _call)


async def _process_pending(
    client: httpx.AsyncClient,
    ingestion_run_id: str,
    limit: int,
    intake_max_listing_age_days: int | None = None,
) -> dict:
    async def _call() -> dict:
        body: dict[str, Any] = {
            "ingestion_run_id": ingestion_run_id,
            "limit": limit,
        }
        if intake_max_listing_age_days is not None:
            body["intake_max_listing_age_days"] = intake_max_listing_age_days
        resp = await client.post(
            "/imports/process-pending",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    return await _retry_api("process_pending", _call)


async def _rescore(
    client: httpx.AsyncClient,
    *,
    profile_slug: str | None,
    only_unscored: bool,
    limit: int | None,
) -> dict:
    async def _call() -> dict:
        body: dict[str, Any] = {"only_active": True, "only_unscored": only_unscored}
        if profile_slug:
            body["profile_slug"] = profile_slug
        if limit is not None:
            body["limit"] = limit
        resp = await client.post("/imports/rescore", json=body)
        resp.raise_for_status()
        return resp.json()

    return await _retry_api("rescore", _call)


async def _build_digest(
    client: httpx.AsyncClient,
    *,
    digest_type: str,
    fresh_hours: int,
    fresh_limit: int,
    gem_limit: int,
    per_company_cap: int,
    min_ranking_score: str,
    gem_min_score: str,
    profile_slug: str | None,
) -> dict:
    async def _call() -> dict:
        payload: dict[str, Any] = {
            "digest_type": digest_type,
            "fresh_hours": fresh_hours,
            "fresh_limit": fresh_limit,
            "gem_limit": gem_limit,
            "per_company_cap": per_company_cap,
            "min_ranking_score": min_ranking_score,
            "gem_min_score": gem_min_score,
        }
        if profile_slug:
            payload["profile_slug"] = profile_slug
        resp = await client.post("/digests/generate", json=payload)
        resp.raise_for_status()
        return resp.json()

    return await _retry_api("build_digest", _call)


async def _health_check(client: httpx.AsyncClient) -> None:
    async def _call() -> None:
        resp = await client.get("/health")
        resp.raise_for_status()

    await _retry_api("health", _call)


def _resolve_csv_path(raw: str, s: Settings) -> Optional[Path]:
    """Resolve a possibly-relative CSV path using ATLAS_REPO_ROOT or auto-detect."""
    p = Path(raw)
    if p.is_absolute():
        return p if p.is_file() else None
    # Try repo_root setting first
    if s.repo_root:
        candidate = Path(s.repo_root) / raw
        if candidate.is_file():
            return candidate
    # Fall back: walk up from this file's location to find the repo root
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / raw
        if candidate.is_file():
            return candidate
    return None


def _universal_aggregator_sources(
    s: Settings | None = None,
    location_ctx: LocationContext | None = None,
) -> list[SourceRow]:
    """Return SourceRow entries for always-on sources.

    Order: RemoteOK → We Work Remotely → Arbeitnow → per-company ATS CSV (if configured).
    All are prepended to whatever per-company sources the caller provides.

    When location_ctx is provided and search_mode includes local results,
    JSearch and Adzuna rows are given location_hint/radius_km so they search
    near the user's home city instead of remote-only.
    """
    if s is None:
        s = get_settings()
    if location_ctx is None:
        location_ctx = LocationContext()

    # Determine whether to pass location to query-based collectors.
    # "local" → only local; "both" → local + remote (pass location, collector handles it)
    use_location = (
        location_ctx.search_mode in ("local", "both")
        and bool(location_ctx.home_city)
    )
    loc_hint = location_ctx.home_city if use_location else ""
    loc_radius = location_ctx.search_radius_km if use_location else 0

    rows: list[SourceRow] = []

    if s.remoteok_enabled:
        rows.append(
            SourceRow(
                company_name="RemoteOK",
                ats_type="remoteok",
                ats_board_url="https://remoteok.com/api",
                notes=s.remoteok_tags,
            )
        )
    if s.wwr_enabled:
        rows.append(
            SourceRow(
                company_name="WeWorkRemotely",
                ats_type="weworkremotely",
                ats_board_url="https://weworkremotely.com",
                notes=s.wwr_categories,
            )
        )
    if getattr(s, "arbeitnow_enabled", True):
        rows.append(
            SourceRow(
                company_name="Arbeitnow",
                ats_type="arbeitnow",
                ats_board_url="https://www.arbeitnow.com/api/job-board-api",
            )
        )
    if getattr(s, "jsearch_enabled", False) and getattr(s, "jsearch_api_key", None):
        rows.append(
            SourceRow(
                company_name="JSearch",
                ats_type="jsearch",
                ats_board_url="https://jsearch.p.rapidapi.com/search",
                location_hint=loc_hint,
                radius_km=loc_radius,
            )
        )
    if getattr(s, "adzuna_enabled", False) and getattr(s, "adzuna_app_id", None) and getattr(s, "adzuna_app_key", None):
        rows.append(
            SourceRow(
                company_name="Adzuna",
                ats_type="adzuna",
                ats_board_url="https://api.adzuna.com",
                location_hint=loc_hint,
                radius_km=loc_radius,
            )
        )
    if getattr(s, "themuse_enabled", True):
        rows.append(
            SourceRow(
                company_name="The Muse",
                ats_type="themuse",
                ats_board_url="https://www.themuse.com/api/public/jobs",
            )
        )
    if getattr(s, "jobicy_enabled", True):
        rows.append(
            SourceRow(
                company_name="Jobicy",
                ats_type="jobicy",
                ats_board_url="https://jobicy.com/api/v2/remote-jobs",
            )
        )
    if getattr(s, "himalayas_enabled", True):
        rows.append(
            SourceRow(
                company_name="Himalayas",
                ats_type="himalayas",
                ats_board_url="https://himalayas.app/jobs/api",
            )
        )
    if getattr(s, "jobstash_enabled", True):
        rows.append(
            SourceRow(
                company_name="Jobstash",
                ats_type="jobstash",
                ats_board_url="https://jobstash.xyz/",
                jobs_page="https://jobstash.xyz/",
            )
        )

    # Per-company ATS boards CSV (e.g. scripts/company_ats_sources.csv)
    if s.company_sources_csv:
        csv_path = _resolve_csv_path(s.company_sources_csv, s)
        if csv_path:
            company_rows = load_sources(csv_path)
            rows.extend(company_rows)
            logger.info(
                "[aggregators] loaded %d company ATS sources from %s",
                len(company_rows),
                csv_path.name,
            )
        else:
            logger.warning(
                "[aggregators] company_sources_csv not found: %s", s.company_sources_csv
            )

    return rows


async def run_collector_pipeline_async(
    *,
    input_csv: Optional[Path] = None,
    sources: Optional[list[SourceRow]] = None,
    input_label: str = "",
    api_base: str | None = None,
    source_limit: int | None = None,
    headless: bool = True,
    batch_size: int = 50,
    source_name: str = "web3_ats_collector",
    source_type: str = "ats",
    then_import: bool = True,
    process_pending_limit: int = 10_000,
    then_rank: bool = True,
    rank_profile_slug: str | None = None,
    rank_only_unscored: bool = False,
    rank_limit: int | None = None,
    then_digest: bool = False,
    digest_type: str = "daily",
    digest_fresh_hours: int = 48,
    digest_fresh_limit: int = 15,
    digest_gem_limit: int = 10,
    digest_per_company_cap: int = 3,
    digest_min_ranking_score: str = "35",
    digest_gem_min_score: str = "60",
    digest_profile_slug: str | None = None,
    progress_log: bool = True,
    intake_max_listing_age_days: int | None = None,
) -> CollectorPipelineResult:
    """Run collect → (optional) process-pending → (optional) rescore → (optional) digest.

    Pass either ``input_csv`` (read via ``load_sources``) or a pre-built
    ``sources`` list (e.g. from ``ingestion_sources``).
    Communicates with the local API at `api_base` (default from settings).
    """
    t0 = time.perf_counter()
    base = (api_base or _api_base()).rstrip("/")
    out_label = input_label.strip() or (str(input_csv) if input_csv else "")
    result = CollectorPipelineResult(ok=False, input_csv=out_label)
    set_running(True)

    if sources is not None:
        loaded = list(sources)
        if source_limit is not None:
            loaded = loaded[:source_limit]
    elif input_csv is not None and input_csv.is_file():
        loaded = load_sources(input_csv, limit=source_limit)
    else:
        if input_csv is not None:
            result.error = f"input_csv not found: {input_csv}"
            result.duration_sec = time.perf_counter() - t0
            return result
        loaded = []

    # Load location preferences from candidate profile (safe — returns default on error).
    loc_ctx = _load_location_context()
    if loc_ctx.is_location_aware:
        logger.info(
            "[pipeline] location mode=%s home_city=%r radius=%dkm targets=%s",
            loc_ctx.search_mode, loc_ctx.home_city,
            loc_ctx.search_radius_km, loc_ctx.target_cities,
        )

    # Always prepend universal aggregators (RemoteOK, WWR) if enabled —
    # they run even when no per-company CSV/sources are provided.
    aggregators = _universal_aggregator_sources(location_ctx=loc_ctx)
    sources_list = aggregators + loaded

    if not sources_list:
        result.error = "no sources loaded (no CSV, ingestion_sources, or enabled aggregators)"
        result.duration_sec = time.perf_counter() - t0
        return result
    result.sources_attempted = len(sources_list)

    def _pr(idx: int, total: int, row: SourceRow) -> None:
        if not progress_log:
            return
        logger.info("[collect] %d/%d  %-30s  (%s)", idx, total, row.company_name, row.ats_type)

    meta: dict[str, Any] = {
        "sources_total": len(sources_list),
        "source_limit": source_limit,
    }
    if input_csv is not None:
        meta["input_csv"] = str(input_csv.resolve())
    else:
        meta["input_mode"] = "ingestion_sources"

    try:
        async with httpx.AsyncClient(
            base_url=base, headers=_admin_headers(), timeout=_HTTP_TIMEOUT
        ) as client:
            try:
                await _health_check(client)
            except BaseException as e:  # noqa: BLE001
                result.error = f"API not reachable at {base}: {e}"
                result.duration_sec = time.perf_counter() - t0
                return result

            logger.info("=" * 60)
            logger.info("[pipeline] START — %d sources queued", len(sources_list))
            logger.info("=" * 60)

            rid = await _open_run(
                client,
                source_name=source_name,
                source_type=source_type,
                metadata=meta,
            )
            result.ingestion_run_id = uuid.UUID(rid)
            buffer: list[RawCollectedRecord] = []
            by_prov: dict[str, int] = {}
            with_records = 0
            ins = 0
            failed = 0

            async def flush() -> None:
                nonlocal ins, failed, buffer
                if not buffer:
                    return
                buf_len = len(buffer)
                try:
                    r = await _submit_batch(client, rid, buffer)
                    ins += int(r.get("inserted", 0) or 0)
                    failed += int(r.get("failed", 0) or 0)
                except BaseException:
                    logger.exception(
                        "raw_events_batch failed permanently after retries (%s events)", buf_len
                    )
                    failed += buf_len
                finally:
                    buffer = []

            cancelled_early = False
            async for _row, records, _reason in collect_all(
                sources_list, headless=headless, progress_cb=_pr,
            ):
                if _cancel_event.is_set():
                    logger.info(
                        "[pipeline] CANCEL requested — stopping collection early, "
                        "will still import → rank → digest from what's collected so far"
                    )
                    cancelled_early = True
                    break
                if records:
                    # Location post-filter: for local/target modes, drop ATS board
                    # records whose location field doesn't match the user's context.
                    if loc_ctx.search_mode in ("local", "target"):
                        before = len(records)
                        records = [
                            r for r in records
                            if r.provider not in _ATS_BOARD_PROVIDERS
                            or _ats_location_matches(
                                str(r.raw_payload.get("location") or ""), loc_ctx
                            )
                        ]
                        dropped = before - len(records)
                        if dropped:
                            logger.debug(
                                "[collect]   location filter dropped %d/%d records from %s",
                                dropped, before, _row.company_name,
                            )
                    if records:
                        with_records += 1
                        for r in records:
                            by_prov[r.provider] = by_prov.get(r.provider, 0) + 1
                        buffer.extend(records)
                        logger.info(
                            "[collect]   → %3d records  (reason: %s)",
                            len(records),
                            _reason or "ok",
                        )
                        if len(buffer) >= batch_size:
                            await flush()
                elif _reason:
                    logger.info("[collect]   → 0 records  (reason: %s)", _reason)
            await flush()
            if cancelled_early:
                # Always finish the pipeline even after cancel — import, rank, digest
                # whatever was collected so the user gets a result.
                then_import = True
                then_rank = True
                then_digest = True

            result.sources_with_records = with_records
            result.records_inserted = ins
            result.records_failed = failed
            result.by_provider = by_prov

            logger.info("-" * 60)
            logger.info(
                "[pipeline] COLLECT done — %d sources returned records, %d raw events inserted",
                with_records, ins,
            )
            logger.info("[pipeline] by provider: %s", by_prov)

            await _finalize_run(client, rid)
            if then_import:
                logger.info("[pipeline] IMPORT — processing pending events in batches …")
                total_processed = 0
                total_new_canonical = 0
                _batch_size = 500
                while True:
                    imp = await _process_pending(
                        client,
                        rid,
                        limit=_batch_size,
                        intake_max_listing_age_days=intake_max_listing_age_days,
                    )
                    batch_processed = int(imp.get("processed", 0) or 0)
                    total_processed += batch_processed
                    total_new_canonical += int(imp.get("new_canonical", 0) or 0)
                    logger.info(
                        "[pipeline] IMPORT batch — processed=%d  new_canonical=%d  (total so far: %d)",
                        batch_processed, int(imp.get("new_canonical", 0) or 0), total_processed,
                    )
                    if batch_processed < _batch_size:
                        break  # No more pending events
                result.import_processed = total_processed
                result.new_canonical = total_new_canonical
                logger.info(
                    "[pipeline] IMPORT done — processed=%d  new_canonical=%d",
                    result.import_processed, result.new_canonical,
                )
            if then_rank:
                logger.info("[pipeline] RANK — scoring jobs …")
                rk = await _rescore(
                    client,
                    profile_slug=rank_profile_slug,
                    only_unscored=rank_only_unscored,
                    limit=rank_limit,
                )
                result.rank_scored = int(rk.get("scored", 0) or 0)
                logger.info("[pipeline] RANK done — scored=%d", result.rank_scored)
            if then_digest:
                dig = await _build_digest(
                    client,
                    digest_type=digest_type,
                    fresh_hours=digest_fresh_hours,
                    fresh_limit=digest_fresh_limit,
                    gem_limit=digest_gem_limit,
                    per_company_cap=digest_per_company_cap,
                    min_ranking_score=digest_min_ranking_score,
                    gem_min_score=digest_gem_min_score,
                    profile_slug=digest_profile_slug,
                )
                did = dig.get("id")
                if did:
                    result.digest_id = uuid.UUID(str(did))
                logger.info("[pipeline] DIGEST done — id=%s", result.digest_id)

        result.ok = True
        logger.info("=" * 60)
        logger.info(
            "[pipeline] COMPLETE — %.1fs | collected=%d | new_jobs=%d | scored=%d",
            time.perf_counter() - t0,
            ins,
            result.new_canonical or 0,
            result.rank_scored or 0,
        )
        logger.info("=" * 60)
    except Exception as e:  # noqa: BLE001
        result.ok = False
        result.error = f"{type(e).__name__}: {e}"[:2000]
        logger.exception("collector pipeline failed: %s", e)
    finally:
        set_running(False)

    result.duration_sec = time.perf_counter() - t0
    return result


def run_collector_pipeline(
    **kwargs: Any,
) -> CollectorPipelineResult:
    """Sync entrypoint: `asyncio.run` of `run_collector_pipeline_async`."""
    return asyncio.run(run_collector_pipeline_async(**kwargs))
