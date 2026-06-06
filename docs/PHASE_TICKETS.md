# Engine merge — phase ticket list

Authoritative roadmap context: **`docs/UNIFIED_PRODUCT_PLAN.md`**. Status below reflects **`2026-04-29`** implementation passes (includes **C3** dual CSV → **`ingestion_sources`**). **Streamlit dogfood / 4-tab UX plan:** **`docs/STREAMLIT_CONSOLIDATED_UX_PLAN.md`**.

---

## Phase C — Manual job URL → pipeline (**shipped**)

| #   | Ticket | Outcome | Pointers |
|-----|--------|---------|----------|
| **C1** | Resolve / normalize / fetch pipeline | **`POST /imports/manual-job-url`**: GET posting URL (**`collectors/http_utils`**), **`payload_from_job_page_html`** → **`RawJobEvent`** (provider **`manual_job_page`**) → **`importer.process_pending`** → optional **`then_rescore`**. Fits cleaner/ranker invariants (`company_name`, `job_title`, `apply_url`, `description_clean`, …). On fetch failure still inserts placeholder raw event so cleaner can classify. | **`backend/app/services/manual_job_url.py`**, **`backend/app/api/imports.py`**, **`backend/app/services/importer*.py`**; ingestion runs / pipeline bookkeeping via importer + **`pipeline`** models/events (see **`backend/app/api/pipeline.py`** for operator tooling). Repo **`scripts/example_sources.csv`** remains the *shape* reference for scripted collectors until DB sources fully replace operator CSV workflows. |
| **C2** | DB-backed sources (stub) | Table **`ingestion_sources`** (**`0011_ingestion_sources`**): **`GET /imports/sources`**, **`POST /imports/sources`**. **`ingestion_source_id`** on manual URL optional; updates **`last_used_at`** when the row belongs to the tenant | **`backend/app/models/ingestion_source.py`**, **`backend/migrations/versions/0011_ingestion_sources.py`**, **`backend/app/api/imports.py`**; **`README.md`** (repo-level sources narrative) |

---

## Phase D — Application packages (after CM slice) (**shipped — engine slice**)

| #   | Ticket | Outcome | Pointers |
|-----|--------|---------|----------|
| **D1** | Packages + tenant-scoped versions | Table **`application_packages`** (**`0012_application_packages`**): versioned **`user_id` + `job_id` + `version`**; strategy / résumé / cover-letter **markdown in Postgres**. **`POST …/generate`**, **`GET`** list/detail, **`POST …/save-version`**. | **`backend/app/models/application_package.py`**, **`backend/app/services/application_packages.py`**, **`backend/app/api/application_packages.py`**, **`backend/app/schemas/application_packages.py`**. |
| **D2** | DOCX ZIP export | **`GET …/packages/{package_id}/export/docx-zip`** — in-memory ZIP with **`resume_draft.docx`**, **`cover_letter_draft.docx`**, **`strategy_notes.docx`** (Jobr-style heading/bullet mapping). **`python-docx`**. | **`backend/app/services/application_package_docx.py`**; legacy reference **`Jobr/backend/app/services/package_service.py`** (`_markdown_to_docx`). |

---

## Phase E — Unified “application job” lifecycle (**E1 + E1+ shipped**)

| #   | Ticket | Outcome | Pointers |
|-----|--------|---------|----------|
| **E1** | Namespace Jobr-era workflow vs **`/jobs`** (**stub shipped**) | **`application_job_tracks`** migrations **`0013`** + **`0018`** (**W6 outcomes**): tenant + **`canonical_job_id`** FK, **`current_stage`**, optional structured **`application_outcome`**, **`stage_changed_at`**, **`notes`**. **`/applications/job-tracks`** REST + **`POST …/{id}/rescore`**. | **`backend/app/api/application_job_tracks.py`**, **`services/application_job_tracks.py`**; **`10_Application_Tracks.py`**. See **`Jobr/backend/app/api/jobs.py`**. |
| **E1+** | Jobr **`POST /jobs/intake`** → Atlas canonical pipeline (**shipped**) | **`POST /applications/jobs/intake`**: **`url`** *or* **`manual_text`** (synthetic **`https://atlas.manual/{digest}`**) → **`manual_job_page`** + importer · optional **`application_job_tracks`**. Parity with **`/imports/manual-job-url`** on **`then_process`** / **`then_rescore`** / **`profile_slug`**. | **`application_job_intake.py`**, **`manual_job_url.py`**, **`application_job_intake` schema**, **`lib/api`** **`applications_job_intake`**. |

---

## Phase E2 — CRM dashboard (**shipped**)

| #   | Ticket | Outcome | Pointers |
|-----|--------|---------|----------|
| **E2** | Jobr-style dashboard on canonical schema | **`GET /applications/dashboard`**: groups tracks into swim lanes; when **`application_outcome`** is set it **overrides** free-text stage bucketing (**W6** **`0018`**); optional comma **`application_outcomes`** query filter (`unset`, `rejected`, …); ranker overlay via **`profile_slug`**; optional **untracked** watchlist. | **`services/application_dashboard.py`**, **`schemas/application_dashboard.py`**, **`api/application_dashboard.py`**; **`tests/test_application_dashboard.py`**; Streamlit **`12_CRM_Dashboard.py`**, **`AtlasAPI.applications_dashboard`**. |

---

## Phase E3 — Discovery + email intake (**shipped — Atlas parity slice**)

Seed discovery and labelled Gmail ingestion feed the **canonical** pipeline via **`ingest_manual_job_url`** / **`manual_job_page`** (not Jobr SQLite **`jobs`**). Jobr **`discovery_service.py`** full crawler parity intentionally out of scope for v1.

| #   | Ticket | Outcome | Pointers |
|-----|--------|---------|----------|
| **E3a** | Seed discovery REST + service | **`0015_discovery_email_intake`**: **`discovery_seeds`**, **`discovery_events`**. **`/discovery/seeds`** enqueue · list · pause · cancel · **`/discovery/queue`** · **`/discovery/run-due`** · **`/discovery/cancel-all`**. BFS crawl in **`services/job_discovery.py`**. | **`api/discovery.py`**, **`models/discovery_*`**, **`tests/test_job_discovery.py`** (`looks_like_job_posting_url`); **`13_Discovery.py`**, **`AtlasAPI.discovery_*`**. |
| **E3b** | Gmail IMAP intake | **`email_sync_sources`** / **`email_sync_events`**; **`/email/sources`** · **`/email/events`** · **`/email/sources/{id}/sync-now`** · **`/email/run-due`**. **`services/email_intake_svc.py`**. Env: **`ATLAS_GMAIL_IMAP_USERNAME`**, **`ATLAS_GMAIL_IMAP_PASSWORD`**, **`ATLAS_GMAIL_IMAP_HOST`**, **`ATLAS_GMAIL_IMAP_PORT`** (**not** **`ATLAS_IMAP_*`**). | **`api/email_intake_route.py`**; **`14_Email_Intake.py`**, **`AtlasAPI.email_*`**. |
| **E3c** | Background **run-due** tick | Optional **`ATLAS_INTAKE_SCHEDULER_ENABLED`** — **`main.py`** runs **`services/intake_scheduler.tick`** on **`ATLAS_INTAKE_SCHEDULER_INTERVAL_SECONDS`** (default 300), capped by **`ATLAS_INTAKE_SCHEDULER_MAX_DISCOVERY_PER_TICK`** and **`ATLAS_INTAKE_SCHEDULER_MAX_EMAIL_PER_TICK`**. **`GET /health`** → **`intake_scheduler_enabled`**. | **`services/intake_scheduler.py`**, **`tests/test_intake_scheduler.py`**. |

---

## Phase F — Single Streamlit (**`UNIFIED_PRODUCT_PLAN.md` Phase 2**)

| #   | Ticket | Outcome | Pointers |
|-----|--------|---------|----------|
| **F1** | One entry + API base URL | **`AtlasAPI`** — merge surfaces: **`/applications/job-tracks`**, **`/applications/jobs/intake`**, **`/career-memory/*`**, packages, imports, **`/discovery/*`**, **`/email/*`**. **`lib/formatters`**: **`breadcrumb_caption`**, **`copyable_uuid`**. **`pages/Profile.py`** (+ **`lib/sections/career_memory.py`**), **`pages/1_Jobs.py`**, **`pages/8_Applications.py`**, **`pages/10_Application_Tracks.py`**, **`pages/13_Discovery.py`**, **`pages/14_Email_Intake.py`**. | **`frontend/streamlit_app/Home.py`**, **`frontend/streamlit_app/lib/api.py`**; **`Jobr/frontend/`** for remaining ported pages |

---

## Phase 3 — Qualification MVP (**deterministic rules slice, shipped**)

Per **`UNIFIED_PRODUCT_PLAN.md` §4 Phase 3** — filter/surface jobs with **stored JSON gates** (no LLM in v1).

| #   | Ticket | Outcome | Pointers |
|-----|--------|---------|----------|
| **Q1** | Rules + overlay + REST | **`user_qualification_settings`** (**`0014`**): **`GET`**/**`PUT /qualification/settings`** (writes need **`X-Admin-Token`**). **`POST /qualification/evaluate`** — batch **`job_ids`**, optional **`profile_slug`** (canonical **`jobs.ranking_score`** vs latest **`job_scores`** for that profile), optional **`rules_override`**. **`QualificationRules`**: **`min_ranking_score`**, **`remote_types_allowed`**, **`title_or_description_must_contain_any`**, **`block_if_text_contains_any`**, **`company_name_block_substrings`**. | **`backend/migrations/versions/0014_user_qualification_settings.py`**, **`models/user_qualification_settings.py`**, **`services/qualification.py`**, **`schemas/qualification.py`**, **`api/qualification.py`**; **`tests/test_qualification_mvp.py`** |
| **Q2** | Streamlit | Primary: **`pages/8_Applications.py`** **Qualification** section (shared **`lib/sections/qualification_rules.py`**). **`pages/11_Qualification.py`** — Advanced mirror/bookmark. **`AtlasAPI`**: **`qualification_get_settings`**, **`qualification_put_settings`**, **`qualification_evaluate`**. | **`frontend/streamlit_app/lib/api.py`**, **`frontend/streamlit_app/lib/sections/qualification_rules.py`** |
| **Q3** | Digest integration | **`digest_builder.build_digest`**: when **`apply_qualification`** is True (default), candidate pools are filtered with **`filter_jobs_by_qualification`** (same overlay as evaluate). **`DigestGenerateRequest.apply_qualification`**, stats **`excluded_by_qualification`**. **`2_Digests.py`** checkbox. | **`services/digest_builder.py`**, **`api/digests.py`**, **`schemas/digest.py`**, **`scheduler.py`** (`digest_config` whitelist) |

---

## Phase C+ — Ingestion sources CSV (**shipped 2026-04-29**)

| # | Ticket | Outcome | Pointers |
|---|--------|---------|----------|
| **C3** | Dual resolver CSV → **`ingestion_sources`** | **`POST /imports/sources/sync-from-csv`** accepts **`csv_format`**: **`auto`** (header inference), **`jobs_targets`**, **`ats_targets`**. **`ats_targets`** maps **`company_name`**, **`ats_slug`**, **`ats_board_url`**, **`ats_type`**, **`official_site`**, **`jobs_page`**. Streamlit sync on **Applications** + **Collectors**; sidebar **`GET /auth/me`** shows tenant UUID for **`ingestion_sources_user_id`** on scheduled runs. | **`services/ingestion_sources_collect.py`**, **`schemas/ingestion.py`**, **`api/imports.py`**, **`tests/test_ingestion_sources_collect.py`**, **`8_Applications.py`**, **`7_Collectors.py`**, **`lib/api.py`** |
| **C4** | List/search **`ingestion_sources`** | **`GET /imports/sources`**: optional **`q`** (ILIKE on label, notes, jobs/careers/ATS URLs, **`ats_type`**, **`resolution_type`**), **`limit`** (1–500; omit = all matches from **`offset`**), **`offset`**. Response includes **`total`**, **`limit`**, **`offset`**, **`items`**. | **`services/ingestion_sources_list.py`**, **`schemas/ingestion.py`** **`IngestionSourceListResponse`**, **`api/imports.py`**, **`tests/test_ingestion_sources_list.py`**, **`8_Applications.py`** sources tab, **`lib/api.py`** **`imports_list_sources`** |

---

## Next backlog (pick next vertical)

| Order | Focus | Notes |
|-------|--------|--------|
| 1 | **Jobr `POST /telegram` → Atlas** | Parse listing message → **`ingest_manual_job_url`** / canonical pipeline; optional **`telegram_ingest_events`**-style audit table — reference **`Jobr/backend/app/api/telegram_intake.py`**, **`telegram_intake_service.py`**. |
| 2 | **Phase 4 polish** | Lite vs Advanced gating; hosted vs BYOK UX (**`UNIFIED_PRODUCT_PLAN.md`** §4). |
| 3 | ~~**Sources UX**~~ | ~~**`GET /imports/sources`**: **`q`** (ILIKE across label / notes / URLs / ATS fields), **`limit`** (1–500, omit = all matches from offset), **`offset`**. Applications **sources** tab: search + page size + page.~~ **shipped 2026-04-29** |
| 4 | ~~**F1 polish** (breadcrumbs · **`copyable_uuid`**)~~ **shipped**. | ~~Jobr dashboard groupings~~ **E2:** **`GET /applications/dashboard`** + **`12_CRM_Dashboard`**. ~~Atlas operator raw-event / failure feed~~ **shipped** (**`GET /pipeline/operator/*`**, **`15_Pipeline_Debug.py`**). |
| 5 | ~~**D2** DOCX ZIP~~ **shipped**. | Optional per-file Word downloads from Streamlit. |
| 6 | ~~**discovery / email** Atlas routes~~ **shipped** (`/discovery/*`, `/email/*`, **`0015`**). ~~Optional **scheduled run-due**~~ **shipped** (**`ATLAS_INTAKE_SCHEDULER_*`**). | Legacy **`/telegram`** and remaining Jobr-only surfaces deferred. |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-04-29 | **Operator pipeline debug:** **`GET /pipeline/operator/summary`**, **`…/raw-events`**, **`…/raw-events/{id}`** (**`pipeline_operator.py`**, **`15_Pipeline_Debug.py`**, **`AtlasAPI`**). |
| 2026-04-29 | **E3c intake scheduler:** **`ATLAS_INTAKE_SCHEDULER_*`**, **`services/intake_scheduler.py`**, **`GET /health`**, **`tests/test_intake_scheduler.py`**. |
| 2026-04-29 | **E3 discovery + email intake:** **`0015`**, **`/discovery/*`**, **`/email/*`**, **`13_Discovery`**, **`14_Email_Intake`**, **`AtlasAPI`** helpers, **`tests/test_job_discovery.py`**. |
| 2026-04-29 | **E2 CRM dashboard:** **`GET /applications/dashboard`**, **`12_CRM_Dashboard.py`**, **`AtlasAPI.applications_dashboard`** — Jobr **`GET /jobs/dashboard`** parity on canonical jobs + tracks. |
| 2026-04-29 | **Phase 3 digest hook:** **`build_digest`** applies qualification rules by default (**`apply_qualification`** / **`excluded_by_qualification`** stats); **`2_Digests`** checkbox. |
| 2026-04-29 | **Phase 3 (Qualification MVP, deterministic slice):** **`0014`** **`user_qualification_settings`**; **`/qualification/*`**; **`11_Qualification`** + **`AtlasAPI`** qualification helpers. |
| 2026-04-29 | **F1 UX:** **`breadcrumb_caption`** + **`copyable_uuid`** (`lib/formatters.py`); **Jobs**, **Applications** Packages hint, **Job tracks** QP row. |
| 2026-04-29 | **D2 shipped:** **`GET …/packages/{id}/export/docx-zip`**, **`application_package_docx.py`**, **`python-docx`** in **`requirements.txt`**. |
| 2026-04-29 | Streamlit **`9_Career_Memory.py`** + **`AtlasAPI`** **`/career-memory/*`** wrappers; **F1** pointers updated. |
| 2026-04-29 | **W6 structured outcomes:** **`0018`**, **`application_outcome`**, **`stage_changed_at`**, **`GET /applications/dashboard?application_outcomes=`**; **`pipeline_crm`** / **`pipeline_tracks`**. |
| 2026-04-29 | **W5 digest alerts:** **`feed_alerts.maybe_digest_top_jobs_alert`**, **`ATLAS_DIGEST_ALERT_*`**, scheduler + **`POST /digests/generate`**; **`tests/test_feed_alerts.py`**. |
| 2026-04-29 | **Streamlit W4:** **`pipeline_crm.py`**, **`pipeline_tracks.py`**; merged **Pipeline** (**`12_CRM_Dashboard`**); **`10_Application_Tracks`** thin mirror — **`STREAMLIT_CONSOLIDATED_UX_PLAN`**. |
| 2026-04-29 | **`GET /jobs`** qualification + **`first_seen_after`** (**`jobs.py`**), Opportunities Streamlit (**W3 v2**) — **`PHASE`** + **`STREAMLIT_CONSOLIDATED_UX_PLAN`**. |
| 2026-04-29 | **Streamlit W3 v1:** **`1_Jobs.py`** Opportunities UX (Digests/Qual expander **`?profile=`**) — **`STREAMLIT_CONSOLIDATED_UX_PLAN`**. |
| 2026-04-29 | **Streamlit W2:** **`lib/sections/qualification_rules.py`**; Search setup **Qualification** section (**`8_Applications.py`**); **`11_Qualification.py`** thin mirror. |
| 2026-04-29 | **Streamlit W1:** **`Profile.py`** (+ **`lib/sections/career_memory.py`**); removed **`9_Career_Memory.py`**. **Primary →** **`pages/Profile.py`**. |
| 2026-04-29 | **Streamlit W0:** **`Home.py`** + **`st.navigation`** (Primary / Advanced), **`pages/Admin_Overview.py`**, **`frontend/requirements`** Streamlit **≥1.36** — see **`docs/STREAMLIT_CONSOLIDATED_UX_PLAN.md`**. |
| 2026-04-29 | **Streamlit consolidated UX (dogfood) plan:** **`docs/STREAMLIT_CONSOLIDATED_UX_PLAN.md`** — 4 primary tabs + Advanced, phases W0–W6. |
| 2026-04-29 | **`GET /imports/sources`**: **`q`**, **`limit`**, **`offset`** + **`services/ingestion_sources_list.py`**; Streamlit sources search/pagination (**`8_Applications`**). |
| 2026-04-29 | **C3:** **`jobs_targets`** + **`ats_targets`** CSV sync into **`ingestion_sources`** (**`csv_format`**, inference, Streamlit + **`GET /auth/me`** sidebar). |
| 2026-04-29 | Docs synchronized (`HANDOVER`, `README*`, **`PHASE_TICKETS`**); Streamlit **`8_Applications.py`** + **`lib/api`** for merge routes. |

