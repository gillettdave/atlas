"""FastAPI application entrypoint.

Run (dev):
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

from the `backend/` directory with venv active.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import api_router
from .config import get_settings
from .db import SessionLocal
from .services import collector_scheduler as collector_sched_svc
from .services import intake_scheduler as intake_sched_svc
from .services import profiles as profiles_svc
from .services import scheduler as scheduler_svc
from .services import users as users_svc

_settings = get_settings()

logging.basicConfig(
    level=getattr(logging, _settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("atlas")


# ---------------------------------------------------------------------------
# Background scheduler loop (Sprint H)
# ---------------------------------------------------------------------------

async def _scheduler_loop(stop_event: asyncio.Event) -> None:
    """Periodically call scheduler.tick() in a worker thread.

    The tick runs under `asyncio.to_thread` so synchronous SQLAlchemy
    work doesn't block the event loop. We swallow + log any exception
    to keep the loop alive across transient DB hiccups.
    """
    interval = max(int(_settings.scheduler_interval_seconds), 10)
    max_per_tick = int(_settings.scheduler_max_per_tick)
    logger.info(
        "scheduler loop starting: interval=%ss max_per_tick=%s",
        interval,
        max_per_tick,
    )

    def _do_tick() -> int:
        with SessionLocal() as db:
            outcomes = scheduler_svc.tick(db, max_per_tick=max_per_tick)
        return len(outcomes)

    while not stop_event.is_set():
        try:
            processed = await asyncio.to_thread(_do_tick)
            if processed:
                logger.info("scheduler tick processed %d schedule(s)", processed)
        except Exception:  # noqa: BLE001
            logger.exception("scheduler tick failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    logger.info("scheduler loop stopped")


async def _collector_scheduler_loop(stop_event: asyncio.Event) -> None:
    """Background tick for `collector_schedules` (Sprint M.1)."""
    interval = max(int(_settings.collector_scheduler_interval_seconds), 30)
    max_per = int(_settings.collector_scheduler_max_per_tick)
    logger.info(
        "collector scheduler loop: interval=%ss max_per_tick=%s",
        interval,
        max_per,
    )

    def _do_tick() -> int:
        with SessionLocal() as db:
            outcomes = collector_sched_svc.tick(db, max_per_tick=max_per)
        return len(outcomes)

    while not stop_event.is_set():
        try:
            n = await asyncio.to_thread(_do_tick)
            if n:
                logger.info("collector scheduler tick: %d run(s)", n)
        except Exception:  # noqa: BLE001
            logger.exception("collector scheduler tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("collector scheduler loop stopped")


async def _daily_collection_loop(stop_event: asyncio.Event) -> None:
    """Server-side fixed daily collection loop.

    Fires once per day at ATLAS_COLLECTION_HOUR_UTC:ATLAS_COLLECTION_MINUTE_UTC (UTC).
    Replaces the user-configurable CollectorSchedule for the primary collection run.
    ATS boards are subject to skip-if-fresh logic (ATLAS_ATS_BOARD_FRESHNESS_DAYS).
    Universal aggregators always run.
    """
    import datetime as _dt
    from pathlib import Path
    from .services import collector_pipeline as _cp

    hour = int(_settings.collection_hour_utc)
    minute = int(_settings.collection_minute_utc)
    logger.info("daily collection loop: fires daily at %02d:%02d UTC", hour, minute)

    def _seconds_until_next_run() -> float:
        now = _dt.datetime.now(_dt.timezone.utc)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += _dt.timedelta(days=1)
        return (target - now).total_seconds()

    def _run_collection() -> None:
        from .services import job_expiry as _expiry
        csv_path = Path(__file__).resolve().parent.parent / "scripts" / "company_ats_sources.csv"
        import datetime as _datetime
        if _settings.ats_board_rotation_enabled and _settings.ats_board_rotation_shards > 1:
            _shard = _datetime.date.today().timetuple().tm_yday % _settings.ats_board_rotation_shards
            logger.info(
                "daily collection starting (freshness=%dd, rotation=shard %d/%d)",
                _settings.ats_board_freshness_days, _shard, _settings.ats_board_rotation_shards,
            )
        else:
            logger.info("daily collection starting (freshness=%dd)", _settings.ats_board_freshness_days)
        result = _cp.run_collector_pipeline(
            input_csv=csv_path if csv_path.exists() else None,
            then_import=True,
            then_rank=True,
            rank_only_unscored=True,
            then_digest=False,  # digest is per-user, not global
            progress_log=True,
        )
        logger.info(
            "daily collection done: ok=%s records=%s new_jobs=%s duration=%.0fs",
            result.ok, result.records_inserted, result.new_canonical, result.duration_sec,
        )
        # Rebuild digest so users see fresh jobs when they open the app
        from .services import digest_builder as _db_svc
        from .services.digest_builder import DigestConfig as _DigestConfig
        from .constants import SEEDED_LOCAL_USER_ID as _SEED_UID
        with SessionLocal() as _db:
            try:
                _built = _db_svc.build_digest(_db, _DigestConfig())
                _db.commit()
                logger.info(
                    "daily digest rebuilt: fresh=%d gems=%d",
                    _built.stats.fresh_selected,
                    _built.stats.gem_selected,
                )
            except Exception:
                logger.exception("daily digest rebuild failed")

        # Cull stale listings and old digests after each collection run
        with SessionLocal() as _db:
            _expiry.expire_stale_jobs(_db)
            _expiry.expire_old_digests(_db)

    # Wait until the first scheduled time before entering the loop
    wait = _seconds_until_next_run()
    logger.info("daily collection: first run in %.0f minutes", wait / 60)
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=wait)
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(_run_collection)
        except Exception:  # noqa: BLE001
            logger.exception("daily collection run failed")

        # Wait until next scheduled time
        wait = _seconds_until_next_run()
        logger.info("daily collection: next run in %.0f minutes", wait / 60)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            continue

    logger.info("daily collection loop stopped")


async def _intake_scheduler_loop(stop_event: asyncio.Event) -> None:
    """Periodically run due discovery seeds + due email IMAP syncs (E3)."""
    interval = max(int(_settings.intake_scheduler_interval_seconds), 60)
    max_disc = int(_settings.intake_scheduler_max_discovery_per_tick)
    max_mail = int(_settings.intake_scheduler_max_email_per_tick)
    logger.info(
        "intake scheduler loop: interval=%ss max_discovery_per_tick=%s max_email_per_tick=%s",
        interval,
        max_disc,
        max_mail,
    )

    def _do_tick():
        if max_disc <= 0 and max_mail <= 0:
            return None
        with SessionLocal() as db:
            return intake_sched_svc.tick(
                db,
                max_discovery_runs_per_tick=max_disc,
                max_email_syncs_per_tick=max_mail,
            )

    while not stop_event.is_set():
        try:
            summary = await asyncio.to_thread(_do_tick)
            if summary and (
                summary.get("discovery_runs") or summary.get("email_syncs")
            ):
                logger.info("intake scheduler tick %s", summary)
        except Exception:  # noqa: BLE001
            logger.exception("intake scheduler tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    logger.info("intake scheduler loop stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with SessionLocal() as db:
            users_svc.ensure_seeded_local_user(db)
            profiles_svc.ensure_default(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("profile bootstrap skipped: %s", e)

    stop_event = asyncio.Event()
    task: asyncio.Task | None = None
    if _settings.scheduler_enabled:
        task = asyncio.create_task(
            _scheduler_loop(stop_event), name="atlas-scheduler-loop"
        )
    else:
        logger.info(
            "scheduler disabled (set ATLAS_SCHEDULER_ENABLED=true to enable)"
        )

    stop_c = asyncio.Event()
    task_c: asyncio.Task | None = None
    if _settings.collector_scheduler_enabled:
        task_c = asyncio.create_task(
            _collector_scheduler_loop(stop_c), name="atlas-collector-scheduler-loop"
        )
    else:
        logger.info(
            "collector scheduler disabled (set "
            "ATLAS_COLLECTOR_SCHEDULER_ENABLED=true to enable)"
        )

    stop_col = asyncio.Event()
    task_col: asyncio.Task | None = None
    if _settings.collection_enabled:
        task_col = asyncio.create_task(
            _daily_collection_loop(stop_col), name="atlas-daily-collection-loop"
        )
    else:
        logger.info(
            "daily collection disabled (set ATLAS_COLLECTION_ENABLED=true to enable)"
        )

    stop_i = asyncio.Event()
    task_i: asyncio.Task | None = None
    if _settings.intake_scheduler_enabled:
        task_i = asyncio.create_task(
            _intake_scheduler_loop(stop_i), name="atlas-intake-scheduler-loop"
        )
    else:
        logger.info(
            "intake scheduler disabled (set ATLAS_INTAKE_SCHEDULER_ENABLED=true to enable)"
        )

    try:
        yield
    finally:
        if task is not None:
            stop_event.set()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
        if task_c is not None:
            stop_c.set()
            try:
                await asyncio.wait_for(task_c, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task_c.cancel()
        if task_col is not None:
            stop_col.set()
            try:
                await asyncio.wait_for(task_col, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task_col.cancel()
        if task_i is not None:
            stop_i.set()
            try:
                await asyncio.wait_for(task_i, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task_i.cancel()


app = FastAPI(
    title="Project Atlas API",
    version=__version__,
    description=(
        "Internal engine for Project Atlas. Collectors collect. Cleaner decides. "
        "Canonical job is the product."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "env": _settings.env,
        "version": __version__,
        "scheduler_enabled": _settings.scheduler_enabled,
        "collector_scheduler_enabled": _settings.collector_scheduler_enabled,
        "intake_scheduler_enabled": _settings.intake_scheduler_enabled,
        "oauth_google_configured": bool(
            (_settings.google_oauth_client_id or "").strip()
            and (_settings.google_oauth_client_secret or "").strip()
            and (_settings.google_oauth_redirect_uri or "").strip()
        ),
        "auth_jwt_configured": bool(
            (_settings.jwt_secret or "").strip()
            and len((_settings.jwt_secret or "").strip()) >= 16
        ),
        "auth_allow_seeded_without_bearer": _settings.auth_allow_seeded_without_bearer,
    }
