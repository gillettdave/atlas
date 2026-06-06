# Project Atlas — Unified product plan (merge roadmap)

**Status:** Active roadmap (2026). This document is the single source of truth for merging **Jobr-era capabilities** (under `Jobr/`: career memory, application packages, additional intake paths) into the **Project Atlas** engine (`backend/`, collectors, cleaner, ranker, digests).

**Naming:** **Project Atlas** is the unified product name at ship time and in UX. **`Jobr/`** is legacy / reference implementation for capabilities being ported into `backend/app/` — not a parallel product brand.

**Goal:** One engine (FastAPI + PostgreSQL), then unified web UI, then mobile app stores. **Near term:** dogfood locally via FastAPI + Streamlit while job-searching.

---

## 1. Product vision

### End-user workflow

1. **Build personal experience source of truth** — Upload résumés, cover letters, certificates, other docs, and free-text. AI extracts structure, prompts **gap-filling questions**, and explores **adjacencies** (ongoing; the DB is never “finished”).
2. **Set job-search criteria** — Including overrides when automated qualification is wrong.
3. **Daily job list** — Combine personal DB + criteria with **Project Atlas** ingestion, cleaning, ranking, and digests to surface roles the user should consider.
4. **Application packages** — Per job: AI-assisted tailored résumé / cover letter / notes using **source of truth + posting + company tone** (copy/paste MVP for ATS pages).
5. **Apply** — User applies on employer sites; structured field automation (Greenhouse/Lever, etc.) comes after MVP.

### Two UX modes (later)

- **Lite:** Minimal settings; guided flows.
- **Advanced:** Most Project Atlas knobs exposed (operators, ranker/memory/packages as applicable — may be gated behind an “Advanced options” menu). Not a blocker for engine work.

---

## 2. Current codebase split (today)

| Area | Location | Role |
|------|----------|------|
| Ingestion, dedupe, ranker, digests, schedules | `backend/` | Project Atlas engine: canonical jobs pipeline; Streamlit **`frontend/`** is operator UI |
| Career memory (ported slice) | `backend/` | **Atlas API** — `/career-memory/*`, `career_*` tables (`0010`; tenant-scoped) |
| Manual job URL + DB ingestion sources stub | `backend/` | `POST /imports/manual-job-url`, `ingestion_sources` (`0011`) |
| Application packages (template drafts) | `backend/` | `/applications/jobs/{job_id}/packages/*`; `application_packages` (`0012`) |
| Application workflow tracks (stages over canonical jobs) | `backend/` | **`GET|POST /applications/job-tracks`**; `application_job_tracks` (**`0013`** — **E1** stub). |
| Qualification rules (deterministic MVP) | `backend/` | **`GET|PUT /qualification/settings`**, **`POST /qualification/evaluate`**; `user_qualification_settings` (**`0014`** — **Phase** **3** rules slice; LLM optional later). |
| **Application CRM dashboard** | `backend/` | **`GET /applications/dashboard`** (**E2**) — grouped **`application_job_tracks`** + ranker overlay; replaces Jobr **`GET /jobs/dashboard`**. Streamlit **`12_CRM_Dashboard.py`**. |
| **Seed discovery + Gmail email intake** | `backend/` | **`/discovery/*`**, **`/email/*`**, Postgres **`0015`**. Canonical ingest via **`ingest_manual_job_url`**. Streamlit **`13_Discovery`** / **`14_Email_Intake`**. Optional **`ATLAS_INTAKE_SCHEDULER_*`** background tick (**`services/intake_scheduler.py`**). |
| SQLite job lifecycle, telegram intake, richer Jobr-only UI | **`Jobr/backend/`**, **`Jobr/frontend/`** | Full **`POST /jobs/intake`** + Jobr job rows vs Atlas **`POST /applications/jobs/intake`**; **`/telegram`**; automation/bootstrap/fit-bucket UX — see **`docs/PHASE_TICKETS.md`** |

Anything still labeled **ported from Jobr** in older docs without a ✅ should be validated against **`docs/PHASE_TICKETS.md`** and **`TARGET_MODULE_LAYOUT.md`** — many routes now ship on **`backend/`**.

---

## 3. Architectural decisions

### 3.1 Single backend

Use **one FastAPI application** and **one primary PostgreSQL** schema for the unified product. Separate **worker processes** for heavy jobs are fine; **two independent HTTP APIs** are discouraged unless scale or org boundaries demand it (not now).

### 3.2 Migration path

**Adapter / sync layers are acceptable** between established Atlas tables and Jobr-era table shapes **only while migrating**, with each migration step reducing duplication. Target: **one consolidated Project Atlas schema**, not eternal dual-write.

### 3.3 Multi-user readiness

- **Implement `users` (or equivalent) and `user_id` on tenant-owned rows early** for facts, documents, preferences, packages, and per-user source lists — even if runtime stays **single seeded user** with auth deferred.
- Avoid new tables that are implicitly global if they will become per-user later (painful migration).

### 3.4 AI providers and cost

- Introduce a **provider abstraction** (env-based keys for dogfooding).
- **Phase A:** Operator keys via environment (single-user).
- **Phase B:** Optional **BYOK** (user API keys, stored securely — mobile will need OS secure storage) vs **hosted** AI for accessibility; product decision can follow without blocking the abstraction.

### 3.5 Sources and manual URLs

- Long-term: **database-backed sources** (global and/or per-user), not only appending a shared CSV file — safer for concurrency and mobile sync.
- **Feature:** User-submitted job URL or JD → resolve/fetch → normalize → dedupe → optionally register as a **source row** feeding the same collector/cleaner assumptions as `scripts/example_sources.csv`-shaped data. Design so it does not bypass Atlas cleaner/ranker invariants.

### 3.6 Application artifacts

- Store package metadata and artifact references **in the DB** (with `user_id`), not only ephemeral laptop paths — prepares for mobile sync and export without a second system.

### 3.7 Repo layout

- Prefer merging Jobr capabilities **into `backend/app/`** as namespaces (`career_memory`, `application_packages`, etc.) rather than maintaining two parallel trees indefinitely.

---

## 4. Phasing

| Phase | Focus |
|-------|--------|
| **1 — Engine** | Unified API boundaries, schema direction, port/adapt Jobr modules; single DB direction with adapters where needed |
| **2 — Desktop dogfood** | One Streamlit surface calling **one API**: SOt + jobs + digest + packages + **applications** stubs; **`/career-memory/*`** and **`/applications/*`** live on Atlas. |
| **3 — Qualification MVP** | Rules + optional LLM: filter/surface jobs against personal DB + user overrides |
| **4 — Polish** | Lite/advanced gating; hosted vs BYOK UX |
| **5 — Mobile / web** | App-store-ready clients reusing same API contracts |

**MVP constraint:** Copy/paste for application fields is sufficient; browser automation for ATS forms is out of scope until core loop is stable.

---

## 5. Related documentation

| Doc | Purpose |
|-----|---------|
| [PHASE_TICKETS.md](./PHASE_TICKETS.md) | **Engine merge checklist:** phases C–E3, qualification, next — file-level pointers |
| [README.md](../README.md) | Repo overview, sources pipeline, smoke-test commands |
| [TARGET_MODULE_LAYOUT.md](./TARGET_MODULE_LAYOUT.md) | Where merged modules live; `/applications/*` vs pipeline `/jobs` |
| [backend/README.md](../backend/README.md) | Project Atlas API (FastAPI), migrations, env vars |
| [frontend/README.md](../frontend/README.md) | Streamlit operator UI for Project Atlas |
| [CAREER_MEMORY_FACTS_AND_TIERS.md](./CAREER_MEMORY_FACTS_AND_TIERS.md) | **Career facts:** free heuristic drafts vs planned paid LLM extraction; API + Streamlit curation |
| [Jobr/README.md](../Jobr/README.md) | Legacy Jobr tree: SQLite job API, telegram, deep discovery/email UX (Atlas has **E3** routes; Jobr remains reference for parity depth) |
| [Jobr/job_application_engine_mvp_spec.md](../Jobr/job_application_engine_mvp_spec.md) | Original MVP spec (application engine) |
| [HANDOVER_PROMPT.md](./HANDOVER_PROMPT.md) | Paste-ready prompt for a fresh implementation chat |

---

## 6. Changelog

| Date | Change |
|------|--------|
| 2026-04-29 | **E3 discovery + email intake:** **`/discovery/*`**, **`/email/*`**, migration **`0015`**; optional **`ATLAS_INTAKE_SCHEDULER_ENABLED`** loop in **`main.py`**. |
| 2026-04-29 | **E2 CRM dashboard:** **`GET /applications/dashboard`**, Swim-lane grouping for **`application_job_tracks`**; **`12_CRM_Dashboard.py`**. |
| 2026-04-29 | **Phase 3 (Qualification MVP, deterministic slice):** `user_qualification_settings` (**`0014`**); **`/qualification/settings`** and **`POST /qualification/evaluate`**; Streamlit **`11_Qualification`**. Optional LLM later per roadmap §4. |
| 2026-04-29 | **E1 stub:** `application_job_tracks` + **`/applications/job-tracks`** on Atlas (**`0013`**); does **not** replace Jobr **`POST /jobs/intake`**. |
| 2026-04-29 | **DOCX/ZIP exports for packages:** **`GET …/applications/jobs/{job_id}/packages/{package_id}/export/docx-zip`** (three `.docx` from markdown via **`python-docx`**); **`app/services/application_package_docx.py`**. |
| 2026-04-29 | **Docs sweep:** **`HANDOVER_PROMPT`**, **`PHASE_TICKETS`**, Streamlit **`8_Applications`** + **`lib/api`** for merge routes. |
| 2026-04-29 | **Phase D (application packages, shipped):** `application_packages` table (`0012`): template drafts combining canonical **`jobs`**, **`job_scores`**, and career **`career_facts`**; routes **`/applications/jobs/{job_id}/packages/*`** (generate · list · get · **`save-version`**). Markdown persisted in Postgres. |
| 2026-04-29 | **Phase C (manual URL + DB sources stub, shipped):** `POST /imports/manual-job-url` resolves an http(s) posting URL → `manual_job_page` raw event → cleaner/importer (optional ingest `profile_slug` + **`then_process`**) → optional **`then_rescore`**. Tenant-scoped **`ingestion_sources`** table (`0011_ingestion_sources`): **`GET`/`POST /imports/sources`** and optional **`ingestion_source_id`** on manual URL (updates **`last_used_at`** when ownership matches). |
| 2026-04-29 | **Naming:** Unified product name locked to **Project Atlas** (`Jobr/` = legacy codebase label only). |
| 2026-04-29 | **Phase B (engine slice):** Postgres career memory tables + `/career-memory/*` on the Atlas API (`0010_career_memory_tables`); seeded-tenant scoped; questions link to Atlas jobs via `canonical_job_id` (UUID). |
| 2026-04-29 | **Phase A (engine):** `users` table + seeded local tenant UUID; tenant-scoped `user_profiles`; `services/ai` OpenAI façade; see `docs/TARGET_MODULE_LAYOUT.md`, migration `0009_users_and_profile_scope`. |
| 2026-04-27 | Initial unified plan and decisions documented |
