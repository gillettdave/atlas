# Project Atlas — Backend

Internal engine for Project Atlas.

> Collectors collect. Cleaner decides. Canonical job is the product.

This package is the FastAPI + SQLAlchemy + Alembic backbone. It replaces the
CSV-oriented prototype scripts at the repo root. Collectors should stop
writing CSVs and start POSTing raw events to this API.

Resolver tooling (`profile_site_resolver_browser_v2.py`, etc.) and how merged **sources CSVs**
feed collectors are summarized in the repo **`README.md`** at the parent directory.

### Unified product (Project Atlas)

The **`Jobr/`** subtree holds **remaining** SQLite-centric workflow (**`POST /jobs/intake`** vs **`POST /applications/jobs/intake`**) and **telegram** tooling. **Discovery + Gmail intake**, **CRM dashboard**, qualification, packages, tracks, career memory, manual URL sources — ship on **`backend/`** (see **`../docs/PHASE_TICKETS.md`** through **`0015`**). Legacy route map: **`../Jobr/README.md`**.

**Phase A (foundation, shipped):** `users` table with a deterministic seeded local tenant id (`app.constants.SEEDED_LOCAL_USER_ID`), ranker `user_profiles` scoped by `user_id`, OpenAI chat façade under **`app/services/ai/`** (env `ATLAS_OPENAI_API_KEY` / `ATLAS_OPENAI_MODEL`). Module map: **`../docs/TARGET_MODULE_LAYOUT.md`**. Alembic revision **`0009_users_and_profile_scope`**.

**Phase B (career memory, shipped):** `/career-memory/*` routes in **`app/api/career_memory.py`**, PostgreSQL tables `career_*` (documents, chunks, facts, timeline, profile questions/answers, discovery profile) tenant-scoped. `POST …/questions/generate?canonical_job_id=<uuid>` links gap questions to **Atlas canonical jobs**. Alembic **`0010_career_memory_tables`**. Depends on **`python-multipart`** for file uploads.

**Phase C (manual job URL + DB-backed sources stub, shipped):** **`POST /imports/manual-job-url`** fetches HTML, builds a raw_payload for **`cleaner_v2`**, runs **`importer.process_pending`** (optional **`profile_slug`**, **`then_process`**, **`then_rescore`**). **`GET`/`POST /imports/sources`** lists or creates **`ingestion_sources`** rows (`user_id`-scoped label + optional **`extra_metadata`**). Alembic **`0011_ingestion_sources`**. **`app/services/manual_job_url.py`**, **`app/models/ingestion_source.py`**.

**Phase D (application packages, shipped):** **`/applications/jobs/{job_id}/packages/*`** — generate · list · get · **`save-version`**. **DOCX:** **`GET …/packages/{package_id}/export/docx-zip`** (ZIP of three Word files) **or** **`GET …/export/docx/resume`**, **`…/cover-letter`**, **`…/strategy`** (single `.docx` each) via **`python-docx`** (**`application_package_docx.py`**). Persisted rows: **`application_packages`** (**`0012`**).

**Phase E (application job tracks, stub shipped):** **`GET|POST /applications/job-tracks`** — list/create (**`canonical_job_id`**) · **`PATCH`/`DELETE`/`GET …/{id}`** · **`POST …/{id}/rescore`**. Persisted **`application_job_tracks`** (**`0013`**). Namespace avoids collision with pipeline **`GET/POST /jobs`**.

**Phase E2 (CRM dashboard, shipped):** **`GET /applications/dashboard`** — swim-lane **`application_job_tracks`** (**`application_outcome`** may override lane bucketing) + optional comma **`application_outcomes`** filter (`unset`, rejected, …); ranker/untracked watchlist (**`application_dashboard`**).

**Phase E3 (discovery + Gmail email intake, shipped):** **`/discovery/*`**, **`/email/*`** (**`0015`**). Canonical ingest (**`manual_job_page`**) vs Jobr SQLite jobs. Gmail env (**`config`**): **`ATLAS_GMAIL_IMAP_USERNAME`**, **`ATLAS_GMAIL_IMAP_PASSWORD`**, **`ATLAS_GMAIL_IMAP_HOST`** (default `imap.gmail.com`), **`ATLAS_GMAIL_IMAP_PORT`**. Optional **`uvicorn` background loop** (same pattern as **`ATLAS_COLLECTOR_SCHEDULER_*`): **`ATLAS_INTAKE_SCHEDULER_ENABLED`**, **`ATLAS_INTAKE_SCHEDULER_INTERVAL_SECONDS`** (default 300), **`ATLAS_INTAKE_SCHEDULER_MAX_DISCOVERY_PER_TICK`**, **`ATLAS_INTAKE_SCHEDULER_MAX_EMAIL_PER_TICK`** — **`services/intake_scheduler.tick`**. **`GET /health`** exposes **`intake_scheduler_enabled`**.

## 1. Requirements

- Python 3.11+
- PostgreSQL 14+ (no SQLite — mandatory per architecture)
- Windows / macOS / Linux
- **CI:** on GitHub, pushes/PRs that touch `backend/` run `python -m pytest tests/`
  (see `.github/workflows/backend-pytest.yml`). Locally run the same from `backend/`.

## 2. One-time setup

### 2a. Install PostgreSQL

On Windows, install from https://www.postgresql.org/download/windows/ or via
`winget install PostgreSQL.PostgreSQL.16`.

Create a database and role:

```sql
-- psql as superuser
CREATE ROLE atlas WITH LOGIN PASSWORD 'atlas';
CREATE DATABASE atlas OWNER atlas;
GRANT ALL PRIVILEGES ON DATABASE atlas TO atlas;
```

### 2b. Python virtualenv

From the repo root:

```powershell
C:\Users\cynnb\AppData\Local\Programs\Python\Python311\python.exe -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

### 2c. Configure env

```powershell
Copy-Item backend\.env.example backend\.env
# Edit backend\.env and set ATLAS_DATABASE_URL if not using the default.
```

Default URL: `postgresql+psycopg://atlas:atlas@localhost:5432/atlas`.

## 3. Run migrations

From the `backend/` directory:

```powershell
cd backend
alembic upgrade head
```

Verify in psql:

```sql
\dt
-- expect: ingestion_runs, raw_job_events, jobs, job_source_sightings,
--         job_scores, digests, digest_items, pipeline_events,
--         delivery_schedules (incl. cron_expression after 0007), ...
```

## 4. Run the API (dev)

```powershell
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs for the interactive OpenAPI UI, or
http://127.0.0.1:8000/health for a liveness check.

## 5. Directory layout

```
backend/
  app/
    main.py                 FastAPI entrypoint
    config.py               Settings (pydantic-settings, ATLAS_* env)
    db.py                   SQLAlchemy engine + session
    models/                 ORM models (one file per table)
    schemas/                Pydantic request/response DTOs
    services/
      normalization.py      company/title/location canonicalization + description hash
      url_canonicalize.py   apply_url canonicalization (tracking stripped)
      cleaner_v2.py         Tier 1/2/3 matcher + CleanerDecision; optional
                            ``ATLAS_INTAKE_MAX_LISTING_AGE_DAYS`` rejects **new**
                            canonical rows when listing date in ``raw_payload``
                            is older than N days (known dates only).
      importer.py           Applies CleanerDecisions to the DB
      ranker.py             Ranker v1 + v2 — ranking_score / quality_score / buckets;
                            profile-aware via build_runtime(profile)
      profiles.py           user_profiles CRUD + default bootstrap
      digest_builder.py     Digest builder — freezes ranked snapshots with caps
      digest_delivery.py    CSV export + Slack/email senders for digests
      backfill.py           Re-normalize existing Jobs from latest RawJobEvent
      review.py             Human-in-the-loop resolver for needs_review events
      scheduler.py          Cadences (daily/hourly/every_n_minutes/cron UTC) +
                            run_schedule + tick (Sprint H); transient-error early retry
      collector_pipeline.py  collect+HTTP import+rescore+digest (Sprint M.1)
      collector_scheduler.py  collector_schedules tick + run (Sprint M.1)
      feedback.py           job_feedback record + resolution_set (Sprint I)
      learning.py           Mean-difference weight nudges from feedback (Sprint I.1)
    collectors/
      base.py               RawCollectedRecord, SourceRow, CollectionStats
      web3_ats.py           Lever/Greenhouse/Workable/Teamtailor/Ashby/Kula + rendered pages
      http_utils.py          GET retry/backoff + JSON helper (Sprint M.4 — 429/long tail)
      jobstash.py           Jobstash aggregator (Sprint M.3: sitemap/JSON-LD or partner API)
    api/
      collectors.py         POST /collectors/run, POST /collectors/raw-events
      imports.py            POST /imports/process-pending, POST /imports/rescore,
                            POST /imports/backfill-normalization
      jobs.py               GET /jobs [?profile_slug=...], GET /jobs/{id},
                            set-primary-source, review/duplicates,
                            review/{id}, review/{id}/resolve,
                            POST/GET /jobs/{id}/feedback,
                            GET /jobs/{id}/feedback/summary
      digests.py            GET /digests/preview, POST /digests/generate, GET /digests,
                            GET /digests/{id}, GET /digests/{id}/export.csv,
                            POST /digests/{id}/send
      profiles.py           GET/POST /profiles, GET/PATCH/DELETE /profiles/{slug},
                            POST /profiles/{slug}/score/{job_id} (dry-run)
      schedules.py          GET/POST /schedules, GET/PATCH/DELETE /schedules/{id},
                            POST /schedules/{id}/run-now, POST /schedules/tick
      collector_schedules.py  CRUD /collector-schedules, POST /pipeline (one shot),
                            POST /tick, POST /{id}/run-now
      feedback.py           GET /feedback (cross-job log view)
      pipeline.py           GET /pipeline/stats, GET /pipeline/events
      pipeline_operator.py  GET /pipeline/operator/summary, GET …/operator/raw-events,
                            GET …/operator/raw-events/{id} (**X-Admin-Token**)
  migrations/               Alembic env + versions
  alembic.ini
  requirements.txt
  .env.example

scripts/
  collector_runner.py       CLI: drives web3_ats collector, streams to API
  example_sources.csv       Tiny demo rows only (full targets: jobs_resolver_v2_full/jobs_targets.csv)
```

## 6. End-to-end smoke test (manual)

With the API running and migrations applied:

1. **Open an ingestion run**
   ```
   POST /collectors/run
   { "source_name": "jobs_collector_v4", "source_type": "ats" }
   ```

2. **Submit raw events**
   ```
   POST /collectors/raw-events
   {
     "ingestion_run_id": "<run_id from step 1>",
     "events": [
       {
         "provider": "greenhouse",
         "source_url": "https://boards.greenhouse.io/acme",
         "raw_payload": {
           "company_name": "Acme Labs",
           "job_title": "Senior Rust Engineer",
           "job_url": "https://boards.greenhouse.io/acme/jobs/12345?utm_source=x",
           "location": "Remote - Global",
           "external_job_id": "12345"
         }
       }
     ],
     "finalize": true
   }
   ```

3. **Run the cleaner**
   ```
   POST /imports/process-pending
   { "limit": 500 }
   ```

4. **See canonical jobs**
   ```
   GET /jobs
   ```

5. **Re-submit the same raw event**
   The canonical job will NOT be duplicated — `last_seen_at` advances and a
   new `JobSourceSighting` may be added if the `source_url` differs. Confirm
   with `GET /jobs/{id}`.

## 7. Running real collectors (Web3 ATS)

Once the API is up (`uvicorn app.main:app --port 8001`), drive the collector
from a **second** PowerShell window:

```powershell
cd "C:\Users\cynnb\Dropbox\Apps and Bots\ATS Bot"
backend\.venv\Scripts\Activate.ps1

# One-time (first run only): install a Chromium binary for Playwright.
python -m playwright install chromium

# Quick 3-row sanity check (Chainlink, Uniswap, Aave via native APIs).
python scripts\collector_runner.py `
  --input-csv scripts\example_sources.csv `
  --api-base http://127.0.0.1:8001 `
  --then-import

# Real 50-row Web3 run against your existing resolved sources:
python scripts\collector_runner.py `
  --input-csv jobs_resolver_v2_test_50\jobs_targets.csv `
  --api-base http://127.0.0.1:8001 `
  --then-import --then-rank

# Larger run; visible browser for debugging a single source:
python scripts\collector_runner.py `
  --input-csv jobs_resolver_v2_test\jobs_targets.csv `
  --api-base http://127.0.0.1:8001 `
  --limit 5 --show-browser --then-import --then-rank

# Full resolved Web3 target list (~3k rows — use --limit for smoke tests):
python scripts\collector_runner.py `
  --input-csv jobs_resolver_v2_full\jobs_targets.csv `
  --api-base http://127.0.0.1:8001 `
  --limit 80 --then-import --then-rank
```

Useful flags:

- `--dry-run` — collect only, do not open a run or POST anything.
- `--batch-size 50` — raw-event flush size.
- `--then-import` — run `/imports/process-pending` against this run when collection finishes (canonical jobs appear in `/jobs` immediately).
- `--then-rank` — after import, run `/imports/rescore` to populate `ranking_score` / `quality_score` / bucket.
- `--rank-only-unscored` — with `--then-rank`, only score jobs that have never been scored (cheap incremental runs).
- `--rank-limit N` — cap the number of jobs the ranker touches in one pass.
- `--then-digest` — after rank, build + persist a digest via `/digests/generate`.
- `--digest-type`, `--digest-fresh-hours`, `--digest-fresh-limit`, `--digest-gem-limit`, `--digest-per-company-cap` — knobs for the digest.
- `--admin-token` — only required when `ATLAS_ENV != dev`.
- `--api-base` — override if your API is on a different port/host.

The runner prints per-source progress, per-batch insert counts, and a
final summary including cleaner_v2 results when `--then-import` is set.

### Existing input CSVs in this repo

The `jobs_resolver_v2*` folders already contain `jobs_targets.csv` files
that match the SourceRow schema — you can feed them straight into the
runner with no changes.

**`jobs_resolver_v2_full/jobs_targets.csv`** is the full resolved run (crypto
list + ATS / native / fallback columns). Files alongside it are **not** extra
inputs for the collector: `ats_targets.csv` is a narrow ATS-only export;
`cryptojobslist_fallback_pages.txt` and `native_jobs_pages.txt` are plain URL
lists that the resolver already folded into `jobs_targets.csv` (keep them as
audit artifacts or for diffing, not as a second source of truth).

## 8. Ranker

`services/ranker.py` implements the scoring pass over canonical jobs.

Sprint G introduced Ranker v2: all behavior below is the v1 baseline
(default weights = 1.0, no keyword extras). See §8.1 for per-profile
personalisation on top of that baseline.

**Inputs per job**

- `web3_fit` (0–25): strong/weak keyword hits in title, company, description.
- `title_quality` (0–15): seniority + role word positives; short / ALL CAPS / spam patterns penalised.
- `provider_trust` (0–10): ATS-direct providers trusted most; aggregator-only listings discounted.
- `freshness` (0–20): exponential decay, 5-day half-life from `first_seen_at`.
- `remote_fit` (0–10): remote > hybrid > onsite; unknown is neutral.
- `duplicate_confidence` (0–10): more independent sightings = higher.
- `hidden_gem_bonus` (+10): ATS-direct AND strong web3 AND fresh AND single-sourced.

**Outputs written**

- `jobs.ranking_score` (0–100) — what `/jobs?order=ranking` and digests sort by.
- `jobs.quality_score` (0–100) — intrinsic trustworthiness of the listing itself.
- `job_scores` row — history, latest is authoritative, carries `bucket`,
  `rationale`, `hidden_gem`, `freshness_score`, `fit_score`.

**Buckets** (applied to `ranking_score`)

| bucket | score | meaning                                 |
|--------|-------|-----------------------------------------|
| top    | ≥ 75  | headline of a digest                    |
| strong | 55–74 | solid match, include below the fold     |
| maybe  | 35–54 | worth a glance, low priority            |
| skip   | < 35  | out-of-scope or low-quality; hide       |

**How to run it**

```powershell
# Score everything active (fast; pure Python, no external calls)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/imports/rescore" `
  -ContentType "application/json" `
  -Body (@{only_active=$true} | ConvertTo-Json)

# Score only jobs that have never been scored (incremental)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/imports/rescore" `
  -ContentType "application/json" `
  -Body (@{only_active=$true; only_unscored=$true} | ConvertTo-Json)

# Restrict to one provider
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/imports/rescore" `
  -ContentType "application/json" `
  -Body (@{provider="greenhouse"} | ConvertTo-Json)
```

Or from the runner in one shot: append `--then-rank` to any real run.

Verify top bucket:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/jobs?limit=5&order=ranking" |
  ConvertTo-Json -Depth 4
```

### Backfilling normalized fields on existing jobs

When normalization rules improve (e.g. the Sprint B.1 tune that reads
`remote_type` from `employment_type` + title), pre-existing `jobs` rows
keep their stale fields — the cleaner only writes those during initial
insert. The backfill service re-runs `normalize_raw_event` against each
job's most recent `raw_job_events` row and fills in:
`remote_type`, `location`, `employment_type`, `salary_text`,
`description_clean`, `description_hash`.

Canonical-identity fields (provider, external_job_id, company,
normalized_company, title, normalized_title, apply_url,
canonical_apply_url) are never touched.

```powershell
# Default: only touch jobs with remote_type=null, also rescore touched jobs.
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/imports/backfill-normalization" `
  -ContentType "application/json" `
  -Body (@{} | ConvertTo-Json)

# Force mode: also overwrite existing non-null normalized fields
# (use when a normalization rule itself changed).
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/imports/backfill-normalization" `
  -ContentType "application/json" `
  -Body (@{only_missing_remote_type=$false; force=$true} | ConvertTo-Json)
```

Response counts: `scanned`, `updated`, `unchanged`, `no_raw_event`,
`failed`, `rescored`, plus a `fields_filled` map showing which fields
the backfill touched most.

### 8.1 Ranker v2 - user profiles (Sprint G)

A **user profile** stores personalised ranker configuration:

- `weights` (dict) - per-component multipliers keyed by:
  `web3_fit`, `title_quality`, `provider_trust`, `freshness`,
  `remote_fit`, `duplicate_confidence`, `description_fit`,
  `hidden_gem_bonus`.
  `1.0` = identical to v1; `0.0` = disables that component;
  values up to `5.0` emphasize it.
- `ranker_text_signals` (JSONB) - built by
  ``POST /profiles/{slug}/rebuild-ranker-text-signals``: a sparse TF–IDF-style
  **reference vector** over ``description_clean`` from jobs you gave **positive**
  feedback to, plus **suggested_keywords** mined from **dismissed/rejected** rows
  with free-text **notes** (and the job title). Until you rebuild, the
  ``description_fit`` component stays **out of the normalization denominator** so
  default scoring matches legacy v1. Optional **synergy** adds a few points when
  both web3 fit and description fit are strong: ``ATLAS_RANKER_SYNERGY_PROFILE_FIT_BOOST``.
- `strong_keywords` / `weak_keywords` - *added to* the global
  Web3 vocabulary for this profile only.
- `negative_keywords` - hits in title/company subtract 15 from
  the final ranking score; hits in description subtract 5.
- `preferred_remote` (`remote` | `hybrid` | `onsite`) - overrides
  the default "remote > hybrid > onsite" preference.
- `min_score_threshold` - reserved for future digest filters.

Exactly one profile has `is_default = true`. The default profile is
seeded by migration `0002_user_profiles`; when scoring against it (or
when no profile is specified) `jobs.ranking_score` and
`jobs.quality_score` are updated. Scoring against any other profile
only writes per-profile rows to `job_scores` (with `profile_id` set).

**Endpoints**

```
GET    /profiles                         (public)   list all
GET    /profiles/{slug}                  (public)   one
POST   /profiles                         (admin)    create
PATCH  /profiles/{slug}                  (admin)    partial update
DELETE /profiles/{slug}                  (admin)    delete (default is protected)
POST   /profiles/{slug}/score/{job_id}   (admin)    dry-run: returns the score
                                                    for one job without persisting
POST   /profiles/{slug}/rebuild-ranker-text-signals (admin) TF–IDF + note keywords
POST   /profiles/{slug}/promote-suggested-keywords (admin) move mined terms → strong/weak (dry-run default)
```

After rebuilding signals, run ``POST /imports/rescore?profile_slug=…`` so
``description_fit`` affects stored scores.

`/imports/rescore` accepts `profile_slug` to drive a per-profile rescore.
`/jobs` accepts `profile_slug` to overlay the latest per-profile score
(and use it for `min_score` filtering + `order=ranking|quality`).

**Example: create a profile and rescore against it**

```powershell
# Create a "devops-remote" profile that emphasizes freshness + remote,
# de-emphasizes web3, and excludes sales/marketing listings.
$body = @{
  slug            = "devops-remote"
  display_name    = "DevOps (remote-first)"
  description     = "Freshness + remote-heavy, low web3 emphasis."
  weights         = @{
    web3_fit             = 0.3
    freshness            = 1.5
    remote_fit           = 2.0
    title_quality        = 1.0
    provider_trust       = 1.0
    duplicate_confidence = 1.0
    hidden_gem_bonus     = 1.0
  }
  strong_keywords   = @("kubernetes", "terraform", "site reliability")
  negative_keywords = @("sales", "marketing", "recruiter")
  preferred_remote  = "remote"
} | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/profiles" `
  -ContentType "application/json" -Body $body

# Rescore all active jobs against it.
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/imports/rescore" `
  -ContentType "application/json" `
  -Body (@{only_active=$true; profile_slug="devops-remote"} | ConvertTo-Json)

# List jobs with the profile's score overlaid.
Invoke-RestMethod "http://127.0.0.1:8001/jobs?limit=5&order=ranking&profile_slug=devops-remote" |
  ConvertTo-Json -Depth 4
```

The Streamlit admin UI ships a **Profiles** page with sliders for every
weight, textareas for each keyword list, controls to **rebuild** TF–IDF +
note-mined ``suggested_keywords`` and **promote** those terms into weak/strong
lists (dry-run first), a "Rescore all jobs with this
profile" button, learn-from-feedback weight nudges, and a test-score form
that returns the full component breakdown without persisting anything.

## 9. Digests

`services/digest_builder.py` freezes "the best N jobs right now" into
durable rows, so a digest is reproducible, addressable, and diffable over
time — not a one-shot HTTP response.

**Two lanes per digest**

| lane          | criterion                                                                 |
|---------------|---------------------------------------------------------------------------|
| `fresh`       | `first_seen_at >= now - fresh_hours`, `ranking_score >= min_ranking_score` |
| `hidden_gem`  | latest `job_scores.hidden_gem = true` OR older job with `ranking_score >= gem_min_score` |

**Per-company cap**

A single company can contribute at most `per_company_cap` items *across*
the whole digest (not per lane). This is what stops one prolific ATS
from dominating the output — e.g. Anchorage Digital currently has ~40
active listings; with `per_company_cap=3`, at most three can appear.

**De-duping across lanes**

A job never appears twice in the same digest: `fresh` is selected first,
then `hidden_gem` skips anything already placed.

**Persistence**

`POST /digests/generate` inserts one `digests` row + N `digest_items`
rows (with lane, rank_position, and a human reason string) in one
transaction, and logs a `pipeline_events` row with the selection stats.

### Endpoints

```
POST /digests/generate           build + persist (admin-protected)
GET  /digests                    list recent digests (paginated)
GET  /digests/{id}               full digest with items + joined jobs
GET  /digests/preview            on-the-fly preview, nothing persisted
GET  /digests/{id}/export.csv    CSV download (admin-protected)
POST /digests/{id}/send          deliver to Slack or email (admin-protected)
```

### Delivery (Sprint F)

`services/digest_delivery.py` turns a persisted digest into a CSV file,
a Slack message, or an email and writes a `pipeline_events` row
(`event_name=digest_delivered`) for every attempt.

Env vars consumed on the backend:

```
ATLAS_SLACK_WEBHOOK_URL    default webhook (can be overridden per request)

ATLAS_SMTP_HOST            required for email
ATLAS_SMTP_PORT            default 587
ATLAS_SMTP_USERNAME        auth user (optional for open relays)
ATLAS_SMTP_PASSWORD        auth password
ATLAS_SMTP_FROM            From: address (required for email)
ATLAS_SMTP_USE_TLS         "true" (default) → STARTTLS after connect
```

Optional digest **top-job alert** (runs right after a digest is persisted — delivery schedules + `POST /digests/generate`):

```
ATLAS_DIGEST_ALERT_ENABLED            "true" to enable (default off)
ATLAS_DIGEST_ALERT_MIN_RANKING_SCORE default 75 — job must be ≥ this in the digest snapshot
ATLAS_DIGEST_ALERT_WEBHOOK_URL       HTTPS POST JSON (includes Slack-style "text" + job list)
ATLAS_DIGEST_ALERT_EMAIL_TO         comma/semicolon-separated; needs ATLAS_SMTP_* for send
ATLAS_DIGEST_ALERT_TOP_JOBS         max jobs enumerated in the ping (default 8)
```

Examples:

```powershell
# 1) Download the most recent digest as CSV
$digest = Invoke-RestMethod "http://127.0.0.1:8001/digests?limit=1" |
  Select-Object -ExpandProperty items | Select-Object -First 1
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8001/digests/$($digest.id)/export.csv" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN } `
  -OutFile ".\digest.csv"

# 2) Post to Slack using ATLAS_SLACK_WEBHOOK_URL
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/digests/$($digest.id)/send" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN } `
  -ContentType "application/json" `
  -Body (@{ channel = "slack" } | ConvertTo-Json)

# 3) Email it to two people
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/digests/$($digest.id)/send" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN } `
  -ContentType "application/json" `
  -Body (@{
    channel = "email"
    recipients = @("ops@example.com", "you@example.com")
    include_hidden_gems = $true
  } | ConvertTo-Json)
```

The Streamlit Digest page exposes all three (CSV download + Slack +
email) in the digest detail panel.

### How to run it

```powershell
# Build a daily digest with default config
$digest = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/digests/generate" `
  -ContentType "application/json" `
  -Body (@{} | ConvertTo-Json)

$digest.id
$digest.stats
$digest.fresh      | Select-Object rank_position, lane, reason, @{n='title';e={$_.job.title}}, @{n='company';e={$_.job.company_name}}
$digest.hidden_gems | Select-Object rank_position, lane, reason, @{n='title';e={$_.job.title}}, @{n='company';e={$_.job.company_name}}

# Tighter custom digest: smaller window, stricter caps
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/digests/generate" `
  -ContentType "application/json" `
  -Body (@{
    digest_type       = "custom"
    fresh_hours       = 24
    fresh_limit       = 10
    gem_limit         = 5
    per_company_cap   = 2
    min_ranking_score = 45
    notes             = "24h strict top-10"
  } | ConvertTo-Json)

# Browse recent digests
Invoke-RestMethod "http://127.0.0.1:8001/digests?limit=10" | ConvertTo-Json -Depth 4

# Fetch a specific digest later
Invoke-RestMethod "http://127.0.0.1:8001/digests/$($digest.id)" | ConvertTo-Json -Depth 5
```

Or drive it end-to-end from the runner by appending `--then-digest` to a
real collection run (implies `--then-import --then-rank` ordering):

```powershell
& "C:\Users\cynnb\Dropbox\Apps and Bots\ATS Bot\backend\.venv\Scripts\python.exe" `
  scripts\collector_runner.py `
  --input-csv scripts\example_sources.csv `
  --api-base http://127.0.0.1:8001 `
  --then-import --then-rank --then-digest
```

The runner summary will then show `digest.id`, `digest.fresh`,
`digest.hidden_gems`, and `digest.dropped_by_cap`.

### 9.1 Scheduled delivery (Sprint H)

A **delivery schedule** is a persistent row telling the system:

- *when* to fire — `daily HH:MM UTC`, `hourly @ :MM`,
  `every N minutes`, or `cron` with a **5-field cron string** interpreted
  in **UTC** (minute hour day-of-month month day-of-week)
- *what* to build — the same `DigestConfig` knobs `/digests/generate`
  takes (`fresh_hours`, `fresh_limit`, `gem_limit`, `per_company_cap`,
  `min_ranking_score`, `gem_min_score`, …) plus an optional
  `profile_slug` to override the default Ranker profile
- *where* to ship — `slack`, `email`, `csv_only`, or `none`

One fire = build a new `Digest` → ship it via the configured channel →
stamp `last_run_at / last_status / last_error / last_digest_id` and
recompute `next_run_at`. Every attempt writes a `pipeline_events` row
with `event_name=schedule_run`.

Endpoints (all mutations require `X-Admin-Token`):

```
GET    /schedules                    list schedules
POST   /schedules                    create
GET    /schedules/{id}               fetch one
PATCH  /schedules/{id}               partial update (recomputes next_run_at)
DELETE /schedules/{id}               delete
POST   /schedules/{id}/run-now       fire immediately, ignoring cadence
POST   /schedules/tick               process every schedule whose
                                      next_run_at <= now (SELECT ... FOR
                                      UPDATE SKIP LOCKED)
```

The optional **background loop** calls `tick()` on a timer without
requiring an external cron. Control with env vars:

```
ATLAS_SCHEDULER_ENABLED=true              # off by default
ATLAS_SCHEDULER_INTERVAL_SECONDS=60       # how often the loop ticks
ATLAS_SCHEDULER_MAX_PER_TICK=25           # cap of schedules per pass
ATLAS_DELIVERY_SCHEDULE_ERROR_RETRY_SECONDS=0   # >0: transient failures may shorten next_run_at (§9.1 prose above)
```

**Retries (same tick)** — `run_schedule` can repeat a **transient-looking** digest
`build_digest` (DB blip; rolls back between tries) up to ``1 +
ATLAS_DELIVERY_SCHEDULE_DIGEST_BUILD_EXTRA_ATTEMPTS`` total attempts with
pause ``ATLAS_DELIVERY_SCHEDULE_RETRY_BACKOFF_SECONDS × attempt``.
Slack/email **deliveries** reuse the same persisted digest id: up to ``1 +
ATLAS_DELIVERY_SCHEDULE_CHANNEL_SEND_EXTRA_ATTEMPTS`` calls to ``deliver()``
when a send fails, with the same backoff ramp (see ``backend/.env.example``).

**Retry without a full cadence** — if ``ATLAS_DELIVERY_SCHEDULE_ERROR_RETRY_SECONDS``
is greater than zero and the failure looks **transient** (same heuristic as digest-build
retries: DB timeouts, connection-ish errors, etc.), the scheduler sets ``next_run_at`` to
the **earlier** of the normal next fire and ``now + that many seconds``, so the next
``tick`` can retry without ``POST …/run-now``. Non-transient errors always use the
normal cadence only.

When disabled, just hit `POST /schedules/tick` yourself from Task
Scheduler / a cron / the Streamlit Schedules page.

Example: create a daily 14:00 UTC digest that posts to Slack.

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/schedules" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN } `
  -ContentType "application/json" `
  -Body (@{
    name                = "daily-14utc-slack"
    cadence             = "daily"
    hour_utc            = 14
    minute_utc          = 0
    channel             = "slack"
    include_hidden_gems = $true
    digest_config = @{
      digest_type       = "daily"
      fresh_hours       = 24
      fresh_limit       = 15
      gem_limit         = 5
      per_company_cap   = 2
      min_ranking_score = 45
    }
  } | ConvertTo-Json -Depth 5)
```

Cron uses standard **5-field** expressions evaluated in **UTC** (dependency: ``croniter`` in ``requirements.txt``). Example — weekdays at 09:30 UTC:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/schedules" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN } `
  -ContentType "application/json" `
  -Body (@{
    name              = "weekdays-0930-utc"
    cadence           = "cron"
    cron_expression   = "30 9 * * 1-5"
    channel           = "none"
    include_hidden_gems = $true
    digest_config     = @{ digest_type = "daily"; fresh_hours = 24; fresh_limit = 10 }
  } | ConvertTo-Json -Depth 5)
```

Fire it once manually to verify end-to-end:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/schedules/$($s.id)/run-now" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN }
```

Or trigger the whole tick from the CLI:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/schedules/tick" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN }
```

The Streamlit UI has a **Schedules** page (`frontend/streamlit_app/pages/5_Schedules.py`)
with create/edit forms, a one-click "Tick now", and per-row "Run now".

### 9.2 Feedback loop (Sprint I)

Feedback is an **append-only event log** of user reactions to jobs. Each
row captures `(job_id, profile_id, action, source, note, created_at)`.

Action vocabulary:

- **Positive / neutral (don't hide)**: `saved`, `clicked`
- **Resolution actions (hidden from future digests)**: `dismissed`,
  `applied`, `interviewed`, `rejected`

Source vocabulary: `ui | email_click | slack_reaction | api`.

Endpoints:

```
POST /jobs/{job_id}/feedback           record one event (admin)
     body: { action, profile_slug?, source?, note? }
GET  /jobs/{job_id}/feedback           full history for one job
GET  /jobs/{job_id}/feedback/summary   { latest_action, counts, is_resolved }
GET  /feedback                         cross-job log, filterable by profile + action
```

The **digest builder** consumes feedback via
`services.feedback.resolution_set(profile_id)`. When you call
`POST /digests/generate` with a `profile_slug` (or a schedule's
`profile_slug` column fires), jobs already resolved under that profile
are filtered out of both the fresh and hidden-gems lanes. The
`excluded_by_feedback` stat is returned on the generate response and
written to `pipeline_events.digest_built.details`.

Example:

```powershell
# Mark a job as applied (will be hidden from future digests for the
# default profile).
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/jobs/<job_id>/feedback" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN } `
  -ContentType "application/json" `
  -Body (@{ action = "applied"; note = "applied via YC careers" } | ConvertTo-Json)

# See what would currently be excluded for a profile-scoped digest.
Invoke-RestMethod "http://127.0.0.1:8001/feedback?action=dismissed&profile_slug=default" |
  ConvertTo-Json -Depth 4

# Generate a digest scoped to a profile so the exclusion applies.
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/digests/generate" `
  -Headers @{ "X-Admin-Token" = $env:ATLAS_ADMIN_TOKEN } `
  -ContentType "application/json" `
  -Body (@{ profile_slug = "default" } | ConvertTo-Json)
```

Scheduler rows always pass their `profile_slug` column through, so a
schedule's daily digest never re-shows an applied job.

On the UI side, the **Jobs** page shows a feedback panel on each job
detail with one-click action buttons plus a 10-event history, and a
dedicated **Feedback** page shows the global log.

### 9.3 Learned weight nudges (Sprint I.1)

The feedback log is now an input into ranking. `services/learning.py`
implements **mean-difference nudging**:

1. For a profile, pull every feedback event and collapse to one label
   per job (negative beats positive when mixed).
2. Score each labeled job against the profile in dry-run mode to recover
   the per-component raw values (`web3_fit`, `title_quality`,
   `provider_trust`, `freshness`, `remote_fit`, `duplicate_confidence`,
   `hidden_gem_bonus`).
3. For each component, compare **weighted** positives vs negatives:

       pos_norm = weighted_mean(positive[C]) / COMPONENT_MAX[C]   # in [0, 1]
       neg_norm = weighted_mean(negative[C]) / COMPONENT_MAX[C]
       signal   = pos_norm - neg_norm                             # in [-1, 1]

   Job-level weights default to **uniform**. Set
   ``ATLAS_LEARNING_FEEDBACK_DECAY_HALF_LIFE_DAYS`` (days, ``0`` = off)
   so each labeled job contributes ``0.5^(age_days / half_life)``
   relative to ``now``, using the timestamp stored when the profile's
   label rule last assigned that job. Overrides per request:
   ``POST …/learn`` body ``feedback_decay_half_life_days``.
       nudge    = clamp(signal * learning_rate, +/- max_step)
       new_w    = clamp(current * (1 + nudge), weight_min, weight_max)

4. Apply only components that cleared `min_samples` per class.
5. On apply: write `profile.weights`, bump `updated_at`, and log a
   `pipeline_events.profile_learned` row with the deltas.

Defaults are conservative (`learning_rate=0.5`, `max_step=0.2`,
`min_samples=3`, clamps `[0.1, 3.0]`) so one pass changes any single
weight by at most ±20% and only when there is real evidence.

**Endpoint**:

- `POST /profiles/{slug}/learn` (admin) — `dry_run=true` by default.

Example payload:

```json
{"dry_run": true, "min_samples": 3, "learning_rate": 0.5, "max_step": 0.2}
```

Example PowerShell:

```powershell
$body = @{ dry_run = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/profiles/default/learn" `
  -ContentType "application/json" -Body $body
```

Response surfaces a per-component table: `pos_mean`, `neg_mean`,
`signal`, `current_weight`, `nudge`, `new_weight`, `applied`, and a
`reason_skipped` field when a component didn't clear the threshold.

After applying, trigger a full rescore (
`POST /imports/rescore?profile_slug={slug}`) so stored scores reflect
the new weights.

### 9.4 Collector operational backbone (Sprint M.1)

`collector_schedules` stores **when** to run the same pipeline the CLI
implements (`scripts/collector_runner.py` flags `then_import` /
`then_rank` / `then_digest`). Cadences match delivery schedules:
**daily**, **hourly**, **every_n_minutes**, and **cron** (5-field UTC
via ``cron_expression``). Internally, `services/collector_pipeline.py`
opens an `ingestion_run`, streams `app.collectors.web3_ats.collect_all`
into `POST /collectors/raw-events`, then calls `process-pending`,
`rescore`, and optionally `digests/generate` over **HTTP to this same
API** (so the cleaner and ranker stay single-sourced in-process).

- **Path resolution**: `input_csv_path` is either absolute or relative to
  `ATLAS_REPO_ROOT` (or auto-detect: parent of the `backend/` package).
- **Endpoints**:
  - `GET/POST /collector-schedules`, `GET/PATCH/DELETE /collector-schedules/{id}`
  - `POST /collector-schedules/pipeline` — one ad-hoc run (no row)
  - `POST /collector-schedules/tick` and `POST /collector-schedules/{id}/run-now`
  - `GET /pipeline/events?event_name=collector_run&entity_type=collector_schedule`
- **Audit**: each completed run writes `pipeline_events.collector_run` with
  ingestion + digest ids and counts. Failures set `last_error` and advance
  `next_run_at` using normal cadence, or — when ``ATLAS_COLLECTOR_SCHEDULE_ERROR_RETRY_SECONDS>0``
  and the failure looks **transient** with **no** ``ingestion_run_id`` yet —
  the **earlier** of cadence and ``now + seconds`` (parity with
  ``ATLAS_DELIVERY_SCHEDULE_ERROR_RETRY_SECONDS`` on delivery schedules).
- **Background loop** (separate from Sprint H): set
  `ATLAS_COLLECTOR_SCHEDULER_ENABLED=true` to tick collector schedules
  on `ATLAS_COLLECTOR_SCHEDULER_INTERVAL_SECONDS` (default 120s) with
  `ATLAS_COLLECTOR_SCHEDULER_MAX_PER_TICK` (default 2 — each run can be
  very slow). `/health` exposes `collector_scheduler_enabled`.
- **Intake run-due loop** (**E3**): set **`ATLAS_INTAKE_SCHEDULER_ENABLED=true`**
  to run due **discovery seeds** and due **Gmail IMAP** sources on
  **`ATLAS_INTAKE_SCHEDULER_INTERVAL_SECONDS`** (default 300s) with caps
  **`ATLAS_INTAKE_SCHEDULER_MAX_DISCOVERY_PER_TICK`** /
  **`ATLAS_INTAKE_SCHEDULER_MAX_EMAIL_PER_TICK`** (same work as **`POST /discovery/run-due`**
  and **`POST /email/run-due`**; see **`services/intake_scheduler.py`**).
  **`GET /health`** exposes **`intake_scheduler_enabled`**.

**PowerShell (placeholder CSV, full pipeline, no schedule row):**

```powershell
$body = @{
  input_csv_path = "scripts/example_sources.csv"
  then_import = $true
  then_rank     = $true
  then_digest   = $false
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/collector-schedules/pipeline" `
  -ContentType "application/json" -Body $body
```

**Postgres ingestion sources — sync CSV then collect without `input_csv_path`:**

```powershell
# Upsert ingestion_sources from jobs_targets-shaped CSV (repo-relative path).
$sync = @{
  csv_path = "jobs_resolver_v2_full/jobs_targets.csv"
  dry_run = $false
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/imports/sources/sync-from-csv" `
  -Headers @{ "X-Admin-Token" = "changeme-local-only"; "Content-Type" = "application/json" } `
  -Body $sync

$bodyDb = @{
  use_ingestion_sources = $true
  source_limit           = 50
  then_import            = $true
  then_rank              = $true
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/collector-schedules/pipeline" `
  -Headers @{ "X-Admin-Token" = "changeme-local-only" } `
  -ContentType "application/json" -Body $bodyDb
```

Collector schedules created with **`use_ingestion_sources: true`** read rows for the **seeded** tenant (`SEEDED_LOCAL_USER_ID`) — background ticks have no Bearer user.

The Streamlit **Collectors** page runs the same `POST` and can create
and tick schedules. Prefer **manual** ticks over the background loop
until real sources and timeouts are proven stable.

### 9.5 Native ATS pulls (Sprint M.2)

Sprint **M.3** (Jobstash as an aggregator) is separate from employer ATS work:
see **§9.6**. M.2 here means **vendor native ATS HTTP** integrations.

The Web3 ATS collector (`app/collectors/web3_ats.py`) now prefers stable
vendor HTTP endpoints where they exist publicly:

**Ashby** — `collect_ashby` calls
`GET https://api.ashbyhq.com/posting-api/job-board/{slug}`
first (titles, `jobUrl`, `applyUrl`, `descriptionPlain`, etc.). Only if the
slug cannot be inferred from `ats_board_url` or the endpoint 404s / errors
does the old Playwright path run. Slug extraction:

- Standard board: ``https://jobs.ashbyhq.com/{slug}``
- Embedded board: ``.../embed/job_board?for={slug}``

**SmartRecruiters** — new `ats_type=smartrecruiters` rows call
``GET https://api.smartrecruiters.com/v1/companies/{companyId}/postings``
with offset pagination (100 per page, no authentication). The `{companyId}`
must match SmartRecruiters’ **career-site identifier**, taken from CSV
``ats_slug`` if set (recommended), otherwise the first path segment of
``https://jobs.smartrecruiters.com/{companyId}/...``.

Raw payloads carry `native_api_item` plus `collection_method` so debugging
shows whether HTTP or rendering produced the row.

Lever and Greenhouse were already HTTP-native from Sprint A; Workable /
Kula / generic pages remain Playwright-heavy.

Example SR row (identifiers are examples — use your tenant’s slug):

```csv
McDonalds Franchise Example,manual,,,,smartrecruiters,,McDonaldsCanada,,,sr_http,
```

(or set `ats_board_url` to the full careers home URL instead of relying on
slug alone.)

### 9.6 Jobstash aggregator (Sprint M.3)

Jobstash (`jobstash.xyz`) is an **aggregator**, not a single employer ATS. The
importer classifies listings as `aggregator_jobstash` when the apply/source
domain matches Jobstash (see `services/importer._source_kind_for`).

**CSV**

- `ats_type=jobstash`
- `ats_board_url` must be set (e.g. `https://jobstash.xyz`) so the Web3 ATS
  dispatch path runs.
- `company_name` is a label for the run only; rows are many-to-many companies
  from Jobstash.

**Modes**

1. **Public (default)** — Crawl Jobstash sitemap shards for two-segment job
   URLs, fetch each listing HTML, and parse **schema.org `JobPosting`**
   JSON-LD. Discovers up to `ATLAS_JOBSTASH_SITEMAP_DISCOVERY_MAX_URLS` listing URLs per run
   then walks them **last-to-first** before stopping at `ATLAS_JOBSTASH_SITEMAP_MAX_JOBS`
   accepted rows—this improves hit rate vs strict crawl-order sitemaps. Respects backoff
   between listing GETs (`ATLAS_JOBSTASH_SITEMAP_REQUEST_GAP_SECONDS`). At most
   `ATLAS_JOBSTASH_SITEMAP_MAX_SHARDS` shard sitemaps are fetched from the root index
   (raise toward 64 if you need broader coverage). **All** public Jobstash HTTP (root
   sitemap, shards, listing HTML, and middleware `/jobs/list`) uses
   `collectors/http_utils.py` — same `ATLAS_HTTP_*` retries and timeouts as native ATS GETs.
   Publication window in public mode comes from `ATLAS_JOBSTASH_PULL_PROFILE` plus
   **`ATLAS_JOBSTASH_INITIAL_MAX_AGE_DAYS`** and **`ATLAS_JOBSTASH_INCREMENTAL_MAX_AGE_HOURS`**
   (`datePosted`; date-only cells use midnight UTC for the check). Defaults match the
   older hardcoded **14-day** / **24-hour** windows.
2. **Partner Middleware API (optional)** — If `ATLAS_JOBSTASH_API_BASE` is set to
   the NestJS backend root that exposes `GET /jobs/list`, Atlas paginates that
   JSON. **Page size is capped at 20** (do not raise). Atlas waits **backoff + jitter**
   between successive page GETs (`ATLAS_JOBSTASH_API_REQUEST_BACKOFF_SECONDS` /
   `ATLAS_JOBSTASH_API_REQUEST_JITTER_SECONDS`). Publication filter: **initial** uses
   middleware **`past-2-weeks`** (~14 days); **incremental** uses **`today`** for
   daily runs. Override any time with `ATLAS_JOBSTASH_API_PUBLICATION_DATE` only if needed.
   Middleware contract aligns with Jobstash's [middleware](https://github.com/jobstash/middleware)
   repo (`{ data: { page, count, data: [...] } }` typical).

Set **`ATLAS_JOBSTASH_PULL_PROFILE=initial`** for a new user's first ingestion, then switch
to **`incremental`** for once-a-day deltas.

Emitted `RawCollectedRecord` payloads include `provider=jobstash` and
`collection_method` describing which mode succeeded.

Example row:

```csv
Jobstash feed,aggregator,,,,jobstash,https://jobstash.xyz,,,,m3_jobstash,
```

### 9.7 Reliability + long-tail ATS HTTP (Sprint M.4)

- **Shared HTTP policy** — Native GETs (Lever, Greenhouse, Ashby posting API, SmartRecruiters
  pages, Workable widget, Teamtailor RSS, scrape fallbacks, etc.) route through
  `app/collectors/http_utils.py`: retries on **429**, **5xx**, transient connection/timeout
  errors, with exponential backoff and optional **Retry-After** handling. Tune with
  ``ATLAS_HTTP_*`` env vars in `.env.example`.

- **Lever / Greenhouse / Ashby / SmartRecruiters** — Structured error reasons are returned
  when the JSON API fails (`lever_api:…`, `greenhouse_api:…`, `smartrecruiters:…`) instead
  of a generic exception. SR paginated calls add a polite pause between offsets
  (`ATLAS_SMARTRECRUITERS_PAGE_PAUSE_SECONDS`).

- **Workable** — First tries the public **widget** feed
  ``GET https://apply.workable.com/api/v1/widget/accounts/{slug}`` (infer **slug** from
  the hub URL path, or set ``ats_slug`` in CSV if the board URL is job-only). Falls back
  to Playwright scraping when the widget is empty or blocked.

- **Teamtailor** — First tries **RSS** ``https://{career-host}/jobs.rss`` on the
  ``*.teamtailor.com`` hostname from ``ats_board_url``; falls back to rendered link
  extraction. Use a full career-site URL (same host as RSS), e.g.
  ``https://acme.teamtailor.com/jobs``.

Runner **failures** still surface as the second string from each source tuple (see
`collector_runner.py` progress lines) so operators can distinguish `http_429_exhausted`
from `workable_render_timeout`.

- **Collector pipeline + scheduled runs** — The shared `collector_pipeline` path (CLI,
  `POST /collector-schedules/pipeline`, and the M.1 background tick) uses **httpx** with
  bounded retries and backoff for calls into the same API (`/health`, open/submit/finalize
  ingestion, process-pending, rank, digest). Tune with ``ATLAS_COLLECTOR_PIPELINE_*``.
  When a **scheduled** run fails with a **transient-looking** error **before** an
  ingestion run is opened, the scheduler may run the full pipeline again (defaults to one
  extra attempt); it **does not** do that once `ingestion_run_id` exists, to avoid
  duplicate collection. Tune with ``ATLAS_COLLECTOR_SCHEDULE_EXTRA_RUN_ATTEMPTS`` and
  ``ATLAS_COLLECTOR_SCHEDULE_RETRY_BACKOFF_SECONDS``. After a failed tick with no
  ``ingestion_run_id``, ``ATLAS_COLLECTOR_SCHEDULE_ERROR_RETRY_SECONDS`` can shorten
  ``next_run_at`` (same idea as delivery digest schedules).

## 10. Design principles already enforced in code

- **One visible job per opening**: `jobs.canonical_apply_url` has a unique
  constraint, and `cleaner_v2` matches on (provider + external_job_id) or
  canonical URL as Tier 1.
- **No buried business logic**: collectors write only to `raw_job_events`.
  All matching / dedupe lives in `services/cleaner_v2.py`.
- **Sponsor routing ready**: every sighting is stored with
  `source_priority` and `sponsor_priority` fields and a `is_primary` flag.
  Promote a preferred apply link via
  `POST /jobs/{id}/set-primary-source`.
- **Operable**: every important decision writes a row to
  `pipeline_events` with a JSONB `details` blob.

## 11. What is NOT built yet (explicit TODOs)

Sprints **M.3** (**§9.6**) and **M.4** (**§9.7**, HTTP resilience + Workable widget /
Teamtailor RSS + clearer error tags) are documented above and are not pending work
in this section.

These are the next sprints from the handover doc. They intentionally are
skeletons or absent for now:

- Scheduled delivery (**Sprint H**) — persistent `delivery_schedules`, `run-now`,
  `tick`, and the scheduler loop (`ATLAS_SCHEDULER_*`) are shipped. Cadences include
  **daily**, **hourly**, **every_n_minutes**, and **cron** (UTC). Same-tick retries for
  digest build + channel send plus optional **early next tick** after transient failures
  (``ATLAS_DELIVERY_SCHEDULE_ERROR_RETRY_SECONDS``) are documented in **§9.1**.
- Ranker v2+ — Profiles, keyword tuning, feedback exclusions, mean-difference nudges
  (**G / I / I.1**), half-life decay in learning (**I.2**), and **description-side fit**
  (sparse TF–IDF reference + note-mined suggestions + optional synergy; rebuild endpoint
  + ``ATLAS_RANKER_*``) are shipped. Automatic **promotion** of note-mined
  ``suggested_keywords`` into ``strong_keywords`` / ``weak_keywords`` is available via
  ``POST /profiles/{slug}/promote-suggested-keywords`` (dry-run by default). Still open:
  heavier semantic / embedding models,
  automatic promotion of mined keywords into profile lists, and more advanced blend
  curves than linear weighted sums + synergy bump.
- **Unified consumer engine (Jobr + Atlas)** — **On `backend/` today:** **`/career-memory/*`** (`0010`), manual URL + **`ingestion_sources`** (Phase **C**, `0011`), **`/applications/.../packages`** template drafts (Phase **D**, `0012`), **`application_job_tracks`** + **`/applications/job-tracks`** (Phase **E1 stub**, **`0013`**). **Still open vs `Jobr/`:** full **`POST /jobs/intake`** parity, discovery/email intake beyond stubs, richer legacy CRM UX (**`docs/PHASE_TICKETS.md`** E1+ / **F**).

An admin UI (Streamlit) lives under `frontend/` — see **`frontend/README.md`**
for launch instructions. It is read-heavy with operator write shortcuts
(process-pending, rescore, backfill, generate digest, **`8_Applications.py`**
manual URL/sources/packages, **`10_Application_Tracks.py`** `/applications/job-tracks`); **Review** for resolving `needs_review` events.

### Review workflow (Sprint E)

When `cleaner_v2.decide` produces `POSSIBLE_DUPLICATE_REVIEW`, the raw
event is parked with `parse_status='needs_review'` and a
`pipeline_event` rows records the candidate job ids + reason. Closing
the loop:

- `GET /jobs/review/duplicates` — queue listing (already existed).
- `GET /jobs/review/{raw_event_id}` — full detail for the review UI:
  the re-normalized "incoming" view and the full `JobOut` records for
  each candidate.
- `POST /jobs/review/{raw_event_id}/resolve` with
  `{action: merge|promote|reject, target_job_id?, note?}`:
  - `merge` re-attaches the raw event as a sighting on `target_job_id`
    (requires `target_job_id`), bumps `last_seen_at`, rescoes the job.
  - `promote` inserts a new canonical job + primary sighting
    (operator overrules the "possible duplicate" flag).
  - `reject` just marks the raw event `rejected` (spam / closed role /
    wrong company).

Every resolution writes a `review_merged / review_promoted / review_rejected`
pipeline event with the operator note if one was supplied.

## 12. Conventions

- All env vars are prefixed `ATLAS_`.
- All timestamps are UTC-aware (`timezone=True` on DateTime columns).
- UUIDs everywhere (Python-side `uuid.uuid4` default; no DB extension
  dependency).
- Service code owns business rules. API routers only translate HTTP.
- Migrations are explicit, not autogenerated, for the initial schema to
  keep indexes and constraints deterministic.
