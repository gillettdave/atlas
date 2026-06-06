# Handover prompt — fresh chat (copy below the line)

---

## Context for the assistant

You are working in the **ATS Bot** workspace (Project Atlas). Read **`docs/UNIFIED_PRODUCT_PLAN.md`** first — it is authoritative for goals and architectural decisions.

### Mission

Merge **Jobr-era code** (`Jobr/`) into **Project Atlas** (`backend/`, `frontend/`) toward **one FastAPI backend**, **one PostgreSQL schema**, and eventually **one Streamlit (then web/mobile) UI**. The shipped product name is **Project Atlas** (`Jobr` is not a dual brand — legacy tree only). **Engine and schema direction before polish.** The founder will dogfood locally (FastAPI + Streamlit) while job searching.

### Product summary

1. **Personal experience DB** — Uploads (résumé, cover letters, certs, etc.) + prompts → AI extracts facts, asks **gap questions**, explores adjacencies (never “done”).
2. **Job criteria + overrides** — Qualify/filter roles against that DB.
3. **Daily digest / job list** — Use **Project Atlas** collectors → cleaner → ranker → digest pipeline for curated apply targets.
4. **Application packages** — Per job: tailored docs from SOt + posting + company tone; **copy/paste MVP** for ATS pages.
5. Later: **Lite vs Advanced** UX (hide/gate deep settings — not blocking).

### Locked decisions

- **Single backend** (one FastAPI app); workers OK, second unrelated HTTP API discouraged unless justified.
- **Adapter/sync acceptable** short-term; migrate toward **one schema**.
- **Add `user_id` early** on tenant data even if only one seeded user / auth later — avoid global-only tables that must retrofit multi-user.
- **AI:** Abstract providers early; env keys for now; **BYOK vs hosted** decided later without blocking abstraction.
- **Manual job URL:** Resolve → normalize → pipeline → optionally merge into **DB-backed sources** (avoid forever relying on a single shared CSV file).
- **Artifacts:** DB-backed metadata for packages/exports for future mobile.
- **Repo:** Fold Jobr into **`backend/app/`** modules over time.

### What exists today

- **Project Atlas (engine):** `backend/` — ingestion, cleaner, ranker, digests, schedules; **`/career-memory/*`** on the unified API (**Phase B**); **`POST /imports/manual-job-url`** + **`ingestion_sources`** (**Phase C**); **`POST /imports/sources/sync-from-csv`** with **`csv_format`** **auto** / **jobs_targets** / **ats_targets** (**C3**); **`GET /imports/sources`** with **`q`** / **`limit`** / **`offset`** (**C4**); **`/applications/jobs/{job_id}/packages/*`** application-package drafts (**Phase D**); **`GET|POST /applications/job-tracks`** (**Phase E1** — CRM rows; **`0018`** optional **`application_outcome`** + **`stage_changed_at`**); **`GET /applications/dashboard`** (**E2**, **`application_outcomes=`** filter · outcome overrides lane buckets); **`POST /applications/jobs/intake`** (**E1+** unified Jobr-style intake vs canonical **`/jobs`**); **`/qualification/*`** (**Phase 3** — stored JSON qualification rules over canonical **`jobs`** + **`job_scores` overlay**); **`/discovery/*`** (seed crawl → **`ingest_manual_job_url`**) + **`/email/*`** (Gmail IMAP labels → URL ingest — migration **`0015`**); optional **`ATLAS_INTAKE_SCHEDULER_*`** background **run-due** (**`services/intake_scheduler.py`**); **`GET /pipeline/operator/*`** (**raw_job_event** failure / queue inspection + **`pipeline_events`** tail); optional **`ATLAS_DIGEST_ALERT_*`** top-job pings after persisted digests (**`services/feed_alerts.py`** — schedule run + **`POST /digests/generate`**).
- **`frontend/`** Streamlit — operator UI (pipeline, jobs, digests, review, profiles, schedules, collectors, feedback, qualification, **CRM dashboard**, **Discovery**, **Email intake**, **Pipeline debug** (**`15_Pipeline_Debug`**). Cross-page links: **Opportunities** canonical id → **Search setup** (**Packages**) + **Job tracks**; merge routes: **`lib/api.py`** + **`8_Applications.py`** (intake / sources / qualification / packages) + **`lib/sections/qualification_rules.py`** + **`12_CRM_Dashboard.py`** (**Primary Pipeline** — **`lib/sections/pipeline_crm.py`** + **`pipeline_tracks.py`**; **W6** **`application_outcome`** + **`application_outcomes=`** filter on **`GET /applications/dashboard`**) + **`10_Application_Tracks.py`** (**Advanced** mirror · **`/applications/job-tracks`**) + **`Profile.py`** / **`lib/sections/career_memory.py`** (**`/career-memory/*`** — **Phase F**) + **`11_Qualification.py`** (**`/qualification/*`** — **Phase** **3** mirror; **`docs/PHASE_TICKETS.md`**) + **`13_Discovery.py`**, **`14_Email_Intake.py`**. **E2** **`/applications/dashboard`** is rendered inside **`12_CRM_Dashboard`**.
- **Legacy Jobr tree:** `Jobr/backend/`, `Jobr/frontend/` — remaining **SQLite job-row** lifecycle (**`POST /jobs/intake`** parity vs **`POST /applications/jobs/intake`**), **`/telegram`** intake, richer Jobr-only CRM/automation UX, etc. Discovery + Gmail email intake ship on **`backend/`** (**E3** — **`docs/PHASE_TICKETS.md`**). **`Jobr/README.md`** stays the legacy reference map.

### Success criteria for early milestones

1. Document / implement **target unified module layout** and **schema direction** (even if adapters remain).
2. **Inventory Jobr** intake + APIs that must move first (career memory, packages, manual URL).
3. **Smallest vertical slice** that runs **one** API process against **Postgres** with **user-scoped rows** where applicable.
4. **Single Streamlit entry point** plan — either extend `frontend/` or merge tabs — calling unified routes only.

### Out of scope for first engine milestone

- Full mobile app, app store submission.
- ATS form auto-fill (beyond copy/paste).
- Final Lite/Advanced split UI.

### Instructions

Propose a **phased ticket list** with file-level pointers. Prefer small PR-sized steps. Do not duplicate **`docs/UNIFIED_PRODUCT_PLAN.md`** in chat — reference it and update it if decisions change. **Shipped engine tickets (through E3, qualification, …)** live in **`docs/PHASE_TICKETS.md`**; keep that file aligned when closing tickets.

---

**Optional:** Paste your workspace path, branch name, and Python/Postgres versions if relevant.
