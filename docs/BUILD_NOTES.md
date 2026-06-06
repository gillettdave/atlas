# Build notes — operator workflow & backlog

Ad-hoc notes for people dogfooding the stack (Streamlit + FastAPI + Postgres). Complements **[UNIFIED_PRODUCT_PLAN.md](./UNIFIED_PRODUCT_PLAN.md)** (vision) and **[PHASE_TICKETS.md](./PHASE_TICKETS.md)** (tracked work).

---

## Narrowing large job corpora (5k+ rows)

**Problem:** After a big collector run, **Opportunities** can show thousands of canonical jobs. Default **`jobs.ranking_score`** is **not** “fit to my résumé”; it blends listing quality, Web3-style keyword fit, freshness, remote/duplicate signals, etc. **Career memory** (approved facts) does **not** feed the ranker today.

**Existing levers (use together):**

| Lever | Where | Role |
|--------|--------|------|
| **Qualification rules** | **Search setup → Qualification** | Hard gates: include/exclude jobs by saved rules (titles, keywords, remote, …). |
| **`GET /jobs` + `apply_qualification=true`** | **Opportunities** → “Restrict to qualifying jobs only” | Server over-fetches by rank, filters to qualifying rows, returns your page size. Best “only show jobs I allow” switch. |
| **Ranker profile** | **Advanced → Profiles** | **Strong / weak / negative keywords** and **weight** multipliers; optional **preferred_remote**. |
| **Rescore** | **Profiles** → “Rescore all jobs with this profile” | Recomputes scores so keyword/weight changes apply. Default profile updates **`jobs.ranking_score`**; other profiles write **`job_scores`** (pick that profile in Opportunities). |
| **Min bucket + sort** | **Opportunities** | e.g. **strong+** or **top**, order by **ranking**. |
| **first_seen / provider / company** | **Opportunities** filters | Shrinks pool before qualification. |
| **Pipeline limits** | **Advanced → Collectors** | Source limit + optional **max listing age** for import step reduce how much enters the DB on first run. |

**New-user efficiency (product note):** The pieces exist but are spread across **Search setup**, **Profiles**, **Collectors**, and **Opportunities**. A **short onboarding wizard** (checklist: API/DB → tune profile → save qualification → rescore → open Opportunities with qualify + min bucket) would improve completion; a **heavy** wizard (CSV sync, discovery vs collectors) is optional for self-hosted operators only.

**Future (not shipped):** Optional “score vs career memory” would require new plumbing (e.g. promote approved facts into profile keywords or ranker text signals).

---

## Step-by-step: filter jobs using your profile

Do these in order once per environment (or after you change keywords/rules).

### 1. Tune your ranker profile (fit & ordering)

1. Open **Advanced → Profiles** (`frontend/streamlit_app/pages/4_Profiles.py`).
2. Select the profile you use day-to-day (usually the one marked **default**).
3. Edit:
   - **Strong keywords** — one per line: stack, domains, role words you want boosted.
   - **Negative keywords** — one per line: roles or words you never want (e.g. unrelated job families).
   - **Weak keywords** (optional) — softer signals.
   - **Weights** (optional) — sliders for components like `web3_fit`, `title_quality`, …
   - **Preferred remote** (optional).
4. Click **Save changes**.

### 2. Rescore so listings use the new profile

1. On the same **Profiles** page, click **Rescore all jobs with this profile** (calls `POST /imports/rescore` with `profile_slug`).
2. Wait for success (large DBs can take a while). You need **admin** token in the sidebar for this write.

**Behavior:** If this profile is the **default**, **`jobs.ranking_score`** is updated — **Opportunities** with Profile **“(default)”** uses that. If the profile is **not** default, scores live in **`job_scores`** — go to step 4 and select that profile in the dropdown.

### 3. Define qualification rules (hard “I qualify” gates)

1. Open **Search setup → Qualification** (Applications page, Qualification section).
2. Save rules that encode what you **require** or **forbid** (e.g. must mention your stack, exclude certain titles, remote-only, etc.).
3. Save / update the ruleset the API expects for your tenant (same page; see qualification API under `/qualification/*`).

### 4. Browse only qualifying, well-ranked jobs

1. Open **Primary → Opportunities** (`1_Jobs.py`).
2. Set **Profile** to your profile slug if you use a **non-default** ranker profile (otherwise leave **(default)** after rescoring the default).
3. Turn on **Restrict to qualifying jobs only** — only rows passing saved qualification rules are returned (with `offset=0` semantics documented in the UI).
4. Set **Min bucket** to **strong+** or **top** to drop low scores.
5. Optionally set **first_seen** cutoff, **provider**, or **company** to narrow further.
6. Click **Refresh** / reload the list as needed.

### 5. (Optional) Description fit over time

After you give **feedback** on jobs you like, **Profiles → Rebuild ranker text signals** improves the **description fit** component (TF–IDF + note terms). Then **Rescore** again. This still learns from **job descriptions + feedback**, not from career-memory résumé text.

### 6. (Optional) Smaller first ingest

For a new database, prefer a **limited first pipeline** (**Collectors** source limit, optional **max listing age** on import) so you are not scoring 5k unrelated rows on day one.

---

---

## Mobile App — Screen map & status (June 2026)

The React Native / Expo app at `mobile/` is the primary interface. Streamlit remains available as a desktop operator tool.

### Tab screens

| Tab | File | What it does |
|-----|------|--------------|
| Feed | `app/(tabs)/index.tsx` | Digest view (Fresh + Hidden Gems lanes) + Browse view (paginated all-jobs). "Find Jobs" 1-click button triggers `POST /pipeline/find-jobs`. "⚙ New Digest" opens advanced options modal (type, score thresholds, limits, qualification filter, profile). |
| Pipeline | `app/(tabs)/pipeline.tsx` | Application job tracks by stage (Kanban-style). Tap to view job detail. |
| Profile | `app/(tabs)/profile.tsx` | Career memory: facts, questions, timeline, documents. |
| Settings | `app/(tabs)/settings.tsx` | API connection config + Test button, pipeline overview stats, collection schedule frequency picker (Off/1x/2x/3x/4x), links to Schedules + Qualification, active scoring profile selector. |

### Stack screens

| Screen | File | What it does |
|--------|------|--------------|
| Job Detail | `app/job/[id].tsx` | Full description, scores, pipeline awareness banner (shows stage if tracked), quick reactions, intake URL |
| Feedback Log | `app/feedback.tsx` | Paginated feedback with filter chips |
| Delivery Schedules | `app/schedules.tsx` | Full CRUD for delivery schedules (cadence, channel, cron, webhook, recipients) |
| Qualification Rules | `app/qualification.tsx` | View/edit all qualification rules: score threshold, remote types, keyword allow/block lists |

### Shared components

| Component | File | Notes |
|-----------|------|-------|
| JobCard | `components/JobCard.tsx` | Two-zone card: top area navigates to detail, bottom bar has 🔖 Save / 👋 Skip / ✅ Applied reactions with local state |
| ErrorState | `components/ErrorState.tsx` | ⚠️ error screen with Retry button, shown when API is unreachable |
| EmptyState | `components/EmptyState.tsx` | Empty list placeholder |
| ScoreBadge | `components/ScoreBadge.tsx` | Colour-coded score pill |
| StageTag | `components/StageTag.tsx` | Pipeline stage chip |

### Developer notes

- **USB-only dev:** App talks to backend via ADB reverse tunnel. Run `adb reverse tcp:8000 tcp:8000` after connecting phone. Must re-run on each USB replug. See `QUICKSTART.txt`.
- **1-click launcher:** Double-click `Launch Atlas.bat` to open backend + Expo + optional Streamlit windows automatically.
- **Windows PowerShell encoding:** All `.ps1` scripts must use ASCII `--` instead of em-dash `—`. PowerShell 5.1 reads UTF-8 as Windows-1252 and `0x94` (part of em-dash) maps to a right smart-quote, breaking string parsing.
- **Profile slug vs ID:** Digest generation uses `profile_slug`; `getJobs` uses `profile_id`. Config store holds both; call `setActiveProfile(id, slug)` to keep them in sync.
- **Collector vs delivery schedule:** Two separate concepts in the app. "Collection Schedule" in Settings controls how often sources are harvested. "Delivery Schedules" controls how/when digests are sent to Slack/email.

### Still to build (mobile)

- Review queue screen
- Discovery seeds / source management screen
- Email intake setup screen
- Telegram notifications

---

## Changelog

| Date | Note |
|------|------|
| 2026-05-12 | Initial build note: narrow jobs, profile vs qualification, onboarding wizard backlog. |
| 2026-06-02 | Added mobile app screen map, component inventory, developer notes, and future backlog. |
