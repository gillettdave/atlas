# Project Atlas (ATS Bot)

Personal AI job search engine: **collectors** pull listings from ATS and native careers pages, **cleaner** dedupes into canonical jobs, **ranker** scores them, and **digests** surface your best matches. A React Native mobile app is the primary interface.

**Quick start:** Double-click `Launch Atlas.bat` — opens backend + Expo in separate windows, sets up USB tunnels automatically. See `QUICKSTART.txt` for full setup.

**Unified product: Project Atlas.** Core capabilities live on **`backend/`**: career memory **`/career-memory/*`**, manual URL + **`ingestion_sources`**, **`/applications/...`** (packages, job tracks, dashboard, **`/applications/jobs/intake`**), **`/qualification/*`**, **`/discovery/*`**, **`/email/*`**. **`Jobr/`** remains reference for SQLite job lifecycle, telegram, richer automation — see **[docs/UNIFIED_PRODUCT_PLAN.md](docs/UNIFIED_PRODUCT_PLAN.md)**, **[docs/PHASE_TICKETS.md](docs/PHASE_TICKETS.md)**. Paste-ready agent prompt: **[docs/HANDOVER_PROMPT.md](docs/HANDOVER_PROMPT.md)**.

## Documentation map

| Doc | Scope |
|-----|--------|
| **[docs/BUILD_NOTES.md](docs/BUILD_NOTES.md)** | **Operator build notes:** narrowing large job lists, profile vs qualification, step-by-step filtering, **mobile screen map**, developer notes. |
| **[docs/UNIFIED_PRODUCT_PLAN.md](docs/UNIFIED_PRODUCT_PLAN.md)** | **Merge roadmap:** vision, architecture, product phasing. |
| **[docs/PHASE_TICKETS.md](docs/PHASE_TICKETS.md)** | **Engine merge tickets** (C–E3, qualification, …) with file-level pointers. |
| [docs/TARGET_MODULE_LAYOUT.md](docs/TARGET_MODULE_LAYOUT.md) | **Code layout:** namespaces under `backend/app/`, `/applications/*` vs pipeline `/jobs`. |
| [docs/HANDOVER_PROMPT.md](docs/HANDOVER_PROMPT.md) | Copy-paste instructions for a fresh implementation chat. |
| [backend/README.md](backend/README.md) | FastAPI API, PostgreSQL, migrations, env vars, Sprint features (H schedules, M collectors, I feedback, ranker). |
| [frontend/README.md](frontend/README.md) | Streamlit operator UI (pages, env). |
| [Jobr/README.md](Jobr/README.md) | **Legacy Jobr** — telegram + SQLite **`/jobs/*`**; **`docs/PHASE_TICKETS`** tracks what still maps to Atlas only. |
| [README_profile_site_resolver_browser_v2.md](README_profile_site_resolver_browser_v2.md) | Offline Playwright: CryptoJobsList profile → `resolved_profile_sites.csv`. |
| [README_official_site_jobs_resolver_v2.md](README_official_site_jobs_resolver_v2.md) | Offline refinement: validated careers URLs + ATS hints → CSV aligned with collector input. |
| [README_jobs_collector_v4.md](README_jobs_collector_v4.md) | Legacy standalone collector script notes (backend pipeline supersedes CSV-only flow). |

**CI:** Changes under `backend/` run `pytest` on GitHub Actions (`.github/workflows/backend-pytest.yml`).

## Data pipeline (sources list → backend)

Building the **ATS / careers URL list** is intentionally **outside** the API:

1. **Discover** company sites and job tabs (e.g. `profile_site_resolver_browser_v2.py` → `resolved_profile_sites.csv`).
2. **Refine** (optional): `official_site_jobs_resolver_v2.py` produces rows closer to what collectors expect (validated native pages, ATS board URLs, fallbacks).
3. **Merge** into the shape consumed by `backend/scripts/example_sources.csv` (see `backend/app/collectors/base.py` `SourceRow` and `backend/README.md` collector sections): `jobs_page`, `ats_board_url`, `ats_type`, `resolution_type`, etc.
4. **Run** ingestion via `scripts/collector_runner.py` or **Collectors** in Streamlit / `POST /collector-schedules/pipeline`.

The backend **does not** crawl directory profile pages for you; it expects those URLs in your merged CSV.

## Recent milestones (2026)

- **Mobile app — alpha ready (June 2026):** Full React Native / Expo app at `mobile/`. Feed (digest + browse), Pipeline kanban, Profile / career memory, Settings. Stack screens: Job detail (pipeline awareness, quick reactions), Feedback log, Delivery schedules CRUD, Qualification rules editor. 1-click launcher (`Launch Atlas.bat` + 3 `.ps1` scripts). ADB reverse tunnel for USB-only dev. See `QUICKSTART.txt` and `docs/BUILD_NOTES.md`.
- **Job sourcing expansion (June 2026):** RemoteOK + WeWorkRemotely aggregator collectors; `POST /pipeline/find-jobs` 1-click endpoint (collect → import → rank → digest); "Find Jobs" button on mobile feed.
- **Engine merge:** Phases **A–E3** (**`users`**, **`/career-memory/*`**, **`0010`**), **C** (**`POST /imports/manual-job-url`**, **`ingestion_sources`**, **`0011`**), **D** (**`/applications/jobs/{job_id}/packages/*`**, **`0012`**), **E1** (**`/applications/job-tracks`**, **`0013`**), **E2** (**`/applications/dashboard`**, **`12_CRM_Dashboard`**), **E3** (**`/discovery/*`**, **`/email/*`**, **`0015`**, optional **`ATLAS_INTAKE_SCHEDULER_*`**). **Qualification MVP** (**`0014`**, **`/qualification/*`**). Ticket detail: **`docs/PHASE_TICKETS.md`**.
- **Unified roadmap:** **`docs/UNIFIED_PRODUCT_PLAN.md`** — remaining **`Jobr/`** parity (telegram, full **`POST /jobs/intake`** on SQLite semantics, automation depth).
- **Sprint H — delivery schedules:** `cadence=cron` with **5-field UTC** expressions (`cron_expression` column, `croniter`), Alembic revision **0007_delivery_schedule_cron**. Optional **early next tick** after transient failures: `ATLAS_DELIVERY_SCHEDULE_ERROR_RETRY_SECONDS` (see `backend/README.md` §9.1).
- **Streamlit Schedules** page supports cron editing alongside daily / hourly / every N minutes.
- **Applications** page (**`frontend/streamlit_app/pages/8_Applications.py`**) exposes manual posting URL ingestion, ingestion sources listing, and per-job package **generate**/list (**Phase F** incremental). **`10_Application_Tracks.py`** covers **`/applications/job-tracks`** (E1).
- **GitHub Actions:** `backend-pytest.yml` runs tests on pushes/PRs when `backend/` changes.
- **Operational clarity:** Sources pipeline (resolvers → `example_sources.csv`) documented below so operator work is explicit.

## Next steps (suggested)

1. **Apply DB migrations:** `cd backend && alembic upgrade head` (through **`0015_discovery_email_intake`** and earlier revisions).
2. **Finish merged sources CSV** when using scripted collectors — consolidate resolver output into `scripts/example_sources.csv` (or paths you pass to `collector_runner`). Prefer **`GET /imports/sources`** for operator-maintained rows where the stub fits your workflow.
3. **Smoke-test ingestion** — With the API running (`uvicorn`, often port **8001`), use **`frontend`** → **Applications** (manual URL) **or** from the repo root:  
     `python scripts/collector_runner.py --input-csv scripts/smoke_sources.csv --api-base http://127.0.0.1:8001 --then-import`
4. **Product backlog:** **`docs/PHASE_TICKETS.md`** — e.g. **telegram** intake, **`GET /jobs/debug/failures`**-style Atlas operator surface, fuller Jobr discovery/fit parity.
5. **Ranker** longer-term notes: **`backend/README.md`** §11 (embeddings / blend beyond shipped slices).
