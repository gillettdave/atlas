# Streamlit consolidated UX — dogfood plan

**Goal:** One calm **4-tab** daily surface for personal use, with **Advanced** holding today’s operator pages. Use it for **days/weeks** to surface product gaps before a **public / mobile** phase.

**Authoritative product context:** `docs/UNIFIED_PRODUCT_PLAN.md`, engine tickets: `docs/PHASE_TICKETS.md`.

---

## Principles

1. **Compose before rebuilding** — Prefer wiring existing API routes and lifting UI from current pages over new domains until a gap is proven.
2. **Backend only when the UI is blocked** — E.g. a unified “Opportunities” feed may need `GET /jobs` extensions; until then, ship a thinner v1 (digest + jobs list) if needed.
3. **Advanced stays available** — Collectors, raw pipeline debug, email IMAP, etc. remain reachable; they are not primary for the job-search loop.
4. **Remote-first** — **Remote-only** + JSON gates on **Primary → Search setup → Qualification** (mirrored **Advanced → Qualification**); saved rules drive **Digests** by default.

---

## Target information architecture

| Primary tab | User job | Main existing sources (lift / link) |
|-------------|----------|-------------------------------------|
| **1 · Profile** | Maintain source of truth | **`pages/Profile.py`** + **`lib/sections/career_memory.py`** (`/career-memory/*`). Quick **page_link** to **`4_Profiles.py`** for ranker weights. |
| **2 · Search setup** | Define *how* jobs enter and *what* passes the bar | **`8_Applications.py`**: intake · sources/CSV · **Qualification** (`lib/sections/qualification_rules.py`) · packages; expander links **Discovery** / **Email**. **`11_Qualification.py`** = Advanced bookmark to the same renderer. |
| **3 · Opportunities** | Daily ranked list of roles worth opening | **`pages/1_Jobs.py`**: **`GET /jobs`** (**`apply_qualification`**, **`first_seen_after`**, **`include_qualification`**/`qualifies`), **`?profile=`**, **`digest_refresh_guidance.py`** (W5 checklist). |
| **4 · Pipeline** | Applied / interviewing / outcomes + packages | **`pages/12_CRM_Dashboard.py`**: **CRM overview** + **Tracks & edits** (`lib/sections/pipeline_crm.py`, `pipeline_tracks.py`) — **W6** **`application_outcome`** + dashboard filter; Packages jump **`?job_id=`** **`?tab=`** (`tracks`/`crm`). **`pages/10_Application_Tracks.py`** = Advanced bookmark. |
| **Advanced** (group) | Operator / debug | **Overview** (`Admin_Overview.py`), Digests, Qualification, Collectors, Schedules, Review, Feedback, Discovery, Email intake, Pipeline debug — wired in **`Home.py`**. |

**Entry:** **`Home.py`** only — sidebar connection + **`st.navigation`** groups (**W0**).

---

## Identified gaps (from product discussion)

| Gap | Impact | Suggested placement |
|-----|--------|---------------------|
| **Opportunities polish** — e.g. `last_seen_after`, cursor paging with **apply_qualification** | Daily loop ergonomics | Tab 3 + extend **`GET /jobs`** when needed |
| **Refresh habit** — tame manual Opportunities reload noise | Pace / focus | **`5_Schedules`** cadence · **Primary → Opportunities** W5 expander (no hard API guard yet). |
| **Alerts for digest top ranks** — lightweight ping | Attention on strong rows | **`feed_alerts.py`** + **`ATLAS_DIGEST_ALERT_*`** (optional; **`pipeline_events.digest_top_jobs_alert`**). |
| **Structured apply outcomes** — rejected vs interview vs offer | Pipeline tab truth | **W6 (shipped):** **`application_job_tracks.application_outcome`** + **`stage_changed_at`** (**`0018`**); **`GET /applications/dashboard?application_outcomes=`** · Streamlit **`pipeline_crm`** / **`pipeline_tracks`**. |
| **Cleaner `remote_type` coverage** | Remote-only filter usefulness | Cleaner/heuristics / data quality iteration (parallel to UX) |

---

## Completed — W2 (2026-04-29)

- **`lib/sections/qualification_rules.py`** — **`render_qualification_rules()`**.
- **`8_Applications.py`** — new horizontal section **Qualification** · digest copy + Discovery/Email expander.
- **`11_Qualification.py`** — thin Advanced mirror (bookmark).

---

## Completed — W3 v1 (2026-04-29)

- **`pages/1_Jobs.py`** — Primary **Opportunities** copy + **Digests & qualification** expander (**`page_link`** to **`2_Digests.py`** and Search setup **`tab=qualification`**).
- Existing **`AtlasAPI.list_jobs`** wiring ( **`order`** · **`min_score`** · **`profile_slug`**) unchanged; **`?profile=<slug>`** applies profile select box when valid.

---

## Completed — W3 v2 (2026-04-29)

- **Backend** — **`GET /jobs`**: **`first_seen_after`**, **`apply_qualification`** (**`filter_jobs_by_qualification`**, over-fetch cap, **`offset` must be 0**), **`include_qualification`** + optional **`JobOut.qualifies`**; response **`qualification_pool_scanned`**, **`qualification_excluded_count`**.
- **`qualification_pass_map`** — annotate rows without filtering (`services/qualification.py`).
- **Streamlit** — **`pages/1_Jobs.py`** + **`AtlasAPI.list_jobs`**.

---

## Completed — W4 (2026-04-29)

- **`lib/sections/pipeline_crm.py`** — **`render_pipeline_crm_dashboard()`** (`GET /applications/dashboard`).
- **`lib/sections/pipeline_tracks.py`** — **`render_pipeline_job_tracks()`** (E1 CRUD mirror).
- **`pages/12_CRM_Dashboard.py`** — Primary **Pipeline**: bordered **Packages** jump + **`?job_id`** / **`?tab`** routing; horizontal **CRM overview** \| **Tracks & edits**.
- **`pages/10_Application_Tracks.py`** — thin **Advanced → Job tracks** bookmark.

---

## Completed — W5 (2026-04-29)

- **`services/feed_alerts.py`** — **`maybe_digest_top_jobs_alert`** after each persisted digest (threshold, webhook JSON, plaintext email); **`ATLAS_DIGEST_ALERT_*`** in **`config.py`**.
- **`scheduler.run_schedule`** — merges **`digest_alert`** summary into **`schedule_run`** **`pipeline_events`**.
- **`POST /digests/generate`** — runs alert helper + **`db.commit()`** for audit rows.
- **Streamlit** — **`lib/sections/digest_refresh_guidance.py`** · **Opportunities** + **Schedules** captions.

---

## Completed — W6 (2026-04-29)

- **`migrations` `0018_application_outcomes`** — **`application_outcome`** (nullable enum text + check) · **`stage_changed_at`** · backfill from timestamps.
- **`ApplicationJobTrack`** / **`job-tracks`** API — create + PATCH **`application_outcome`** (empty clears); **`stage_changed_at`** bumped on **`current_stage`** change.
- **`GET /applications/dashboard`** — comma **`application_outcomes`** (`unset`, `rejected`, …); **`application_outcome`** dominates swim-lane buckets when set.
- **Streamlit** — **`pipeline_crm`** outcome multiselect; **`pipeline_tracks`** outcome create/patch controls + table columns.

---

## Completed — W1 (2026-04-29)

- **`lib/sections/career_memory.py`** — shared **`render_profile_career_memory()`** UI.
- **`pages/Profile.py`** — canonical **Primary → Profile**; **`9_Career_Memory.py`** removed.
- **`Home.py`** wires **Profile** to **`pages/Profile.py`**.

---

## Completed — W0 (2026-04-29)

- **`streamlit run streamlit_app/Home.py`** — `st.navigation` **Primary** + **Advanced**; `pages/` auto-discovery **off** when navigation runs.
- **`render_sidebar_config()`** only on the entrypoint; removed from `pages/*.py`.
- **`pages/Admin_Overview.py`** — pipeline metrics, queues, admin writes, recent runs.
- **`streamlit>=1.36`** — `frontend/requirements.txt`.

---

## Post–W6 follow-ups

- **Opportunities polish** — **`last_seen_after`**, cursor paging with **`apply_qualification`** (still in **gaps** table).
- **Cleaner `remote_type` coverage** — remote-only filter usefulness (parallel data work).

---

## Success criteria (“ready to dogfood daily”)

- [x] You can reach **Profile → Search setup → Opportunities → Pipeline** from grouped nav (plus **Advanced**).
- [x] Qualification (**Remote-only** + JSON) is edited from **Search setup**; **digests** and optional **Opportunities** **`GET /jobs`** knobs use saved rules after **Save qualification rules**.
- [x] **Opportunities** shows a **ranked** list (`GET /jobs`, optional **`apply_qualification`** / **`first_seen_after`**) with a clear path to **Packages** / apply.
- [x] **Pipeline** shows **CRM lanes** + **tracks** editing on one Primary surface, with a **Packages** jump by **`job_id`** (dogfood **1–2 weeks** to validate).
- [x] **Advanced** still available for collectors and pipeline debug.
- [x] **W5 — Refresh + alerts:** operator checklist on **Opportunities** / **Schedules**; optional **`ATLAS_DIGEST_ALERT_*`** after digest builds (no hard **≤4/day** API guard yet).
- [x] **W6 — Structured outcomes:** **`application_job_tracks.application_outcome`** + **`stage_changed_at`**; dashboard **`application_outcomes=`** filter; Streamlit Pipeline CRM + Tracks.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-04-29 | **W6:** **`0018`** **`application_outcome`** / **`stage_changed_at`** · **`GET /applications/dashboard?application_outcomes=`** lane logic · **`pipeline_crm`** / **`pipeline_tracks`**. |
| 2026-04-29 | **W5:** **`feed_alerts.py`**, **`ATLAS_DIGEST_ALERT_*`**, scheduler + **`POST /digests/generate`** hooks; Streamlit **`digest_refresh_guidance`**. |
| 2026-04-29 | **W4:** **`pipeline_crm.py`** · **`pipeline_tracks.py`** · merged **Pipeline** (**`12_CRM_Dashboard.py`**) + Advanced **`10_Application_Tracks`** mirror. |
| 2026-04-29 | **W3 v2:** **`GET /jobs`** **`apply_qualification`** / **`first_seen_after`** / **`include_qualification`** (**`jobs.py`**, **`qualifies`**, **`qualification_pass_map`**); Opportunities UI (**`1_Jobs.py`**, **`AtlasAPI.list_jobs`**). |
| 2026-04-29 | **W3 v1:** **`1_Jobs.py`** Opportunities framing · Digests/Qualification expander · **`?profile=`** deep link. |
| 2026-04-29 | **W2:** **`lib/sections/qualification_rules.py`** · Search setup **Qualification** section (**`8_Applications.py`**); **`11_Qualification.py`** thin mirror. |
| 2026-04-29 | **W1:** **`Profile.py`**, **`lib/sections/career_memory.py`**; **`9_Career_Memory.py`** removed. |
| 2026-04-29 | Initial plan — 4-tab IA, phases W0–W6, file pointers. |
