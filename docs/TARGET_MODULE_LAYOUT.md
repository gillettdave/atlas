# Project Atlas — target module layout (Phase A anchor)

Authoritative merge vision stays in **`UNIFIED_PRODUCT_PLAN.md`**. **Shipped vs next tickets** stay in **`PHASE_TICKETS.md`**. This file is **where code should land** as Jobr-era features port into **`backend/`**.

## Naming: two different “jobs” worlds

Avoid mixing URL namespaces:

| Concept | Typical route prefix | Source today |
|---------|---------------------|---------------|
| **Canonical listings pipeline** — collectors → cleaner → ranker (`jobs`, `job_scores`, digests) | `/jobs`, `/imports`, `/collectors`, … | **`backend/app/api/`** |
| **Application workflow** — URL intake, stages, tailoring, packages (often Jobr-shaped) | **`/applications/...`** (recommended) — *not* reusing Atlas `/jobs` | **`Jobr/backend/app/`** → move under **`backend/app/api/application_*.py`** or **`backend/app/application/`** |

When porting Jobr **`GET/POST /jobs/*`**, remap so it does **not** collide with Atlas **`jobs.py`** (canonical pipeline HTTP API).

## Suggested namespaces under `backend/app/`

| Area | Intended path | Notes |
|------|----------------|-------|
| **Accounts / tenancy** | `models/user.py`, `services/users.py` | Postgres `users` row + seed; future auth attaches here (`user_id` on tenant tables). |
| **Ranker “profiles”** (weights, keywords) | `models/user_profile.py`, `services/profiles.py` | Compound unique `(user_id, slug)`. Not the same entity as **`users`** — rename in UI docs if confusing. |
| **Career memory** | `api/career_memory.py`, `services/career_memory.py`, `schemas/career_memory.py`, **`career_*`** models | **Shipped (Phase B)** under `/career-memory/*`. |
| **Application packages** | `api/application_packages.py`, `services/application_packages.py`, **`services/application_package_docx.py`** | **Shipped (Phase D)** — `/applications/jobs/{job_id}/packages/*`; **`application_packages`** markdown; **`GET …/export/docx-zip`** (ZIP of three `.docx` via **`python-docx`**). |
| **Application job tracks (CRM over canonical listings)** | **`api/application_job_tracks.py`**, **`api/application_dashboard.py`**, **`services/application_job_tracks.py`**, **`services/application_dashboard.py`**, **`application_job_tracks`** table | **E1** — **`/applications/job-tracks`** (**`0013`**). **E2** — **`GET /applications/dashboard`** (Jobr **`/jobs/dashboard`** successor). Intake parity: **`POST /applications/jobs/intake`**. |
| **Application jobs + intake + scoring (broader)** | `api/application_jobs.py`, `services/application_intake/`, … | Remaining Jobr job lifecycle bits; **`/applications`** namespace; see **`PHASE_TICKETS`** E1+. |
| **Discovery / email intake (Atlas)** | `api/discovery.py`, **`api/email_intake_route.py`**, **`services/job_discovery.py`**, **`services/email_intake_svc.py`**, **`services/intake_scheduler.py`** (optional background **run-due** tick alongside **`main.py`** lifetime) | **Shipped E3:** **`0015`**; ingest via **`ingest_manual_job_url`**. |
| **Pipeline ops / operator debugging** | **`api/pipeline.py`**, **`api/pipeline_operator.py`**, **`services/pipeline_operator.py`**, **`schemas/pipeline_operator.py`** | **`/pipeline/stats`**, **`/pipeline/operator/raw-events`** (filterable **`raw_job_events`** + detail with **`pipeline_events`** tail; admin token). **`15_Pipeline_Debug`**. |
| **Adapters (temporary)** | `services/adapters/` or beside feature | Dual-write/shape translation only until one schema wins. |

## Streamlit (`frontend/`)

Single operator + product surface over time:

- Extend **`frontend/streamlit_app/`** with new pages calling **one** **`ATLAS_*` API base** ( **`frontend/streamlit_app/lib/api.py`** ).
- **`Jobr/frontend/`** pages are migration sources until removed.

---

**Changelog**

| Date | Change |
|------|--------|
| 2026-04-29 | **Operator pipeline debugging:** **`pipeline_operator`** + **`schemas/pipeline_operator`**, **`GET /pipeline/operator/*`**. |
| 2026-04-29 | **E3 (+E3c):** **`discovery`**, **`email_intake_route`**, **`intake_scheduler`**; **`ATLAS_INTAKE_SCHEDULER_*`**. |
| 2026-04-29 | **E2 CRM dashboard:** **`application_dashboard`**, **`GET /applications/dashboard`**. |
| 2026-04-29 | **E1 stub:** **`application_job_tracks`**, **`/applications/job-tracks`**, **`0013_application_job_tracks`**. |
| 2026-04-29 | **D2 export:** **`application_package_docx.py`**, **`GET …/export/docx-zip`**. |
| 2026-04-29 | **Phase D:** **`application_packages`** table + **`/applications/jobs/{job_id}/packages/*`** (generate/list/get/save-version); **`app/services/application_packages.py`** bridges canonical **`jobs`** + **`job_scores`** + career-memory facts. Migration **`0012_application_packages`**. |
| 2026-04-29 | **Phase C:** **`services/manual_job_url.py`** + **`POST /imports/manual-job-url`**; **`models/ingestion_source.py`** + **`GET|POST /imports/sources`** (`ingestion_sources` table). |
| 2026-04-29 | **Phase B:** career memory namespace filled (`/career-memory/*`, `career_*` tables). |
| 2026-04-29 | Initial layout: Project Atlas namespaces, `/applications/*` vs pipeline `/jobs`. |
