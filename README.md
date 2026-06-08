# Project Atlas

Personal AI job search engine. Collectors pull listings from 10+ sources, a cleaner dedupes into canonical jobs, a ranker scores them against your career profile, and digests surface your best matches. A React Native mobile app (Android + iOS) is the primary interface.

---

## Quick Start (local dev)

Double-click `Launch Atlas.bat` — starts the backend and Expo in separate windows.

Or manually:
```powershell
# Terminal 1 — backend
.\atlas-backend.ps1

# Terminal 2 — mobile
.\atlas-mobile.ps1
```

---

## Repository Structure

```
atlas/
├── backend/          # FastAPI backend + collectors + migrations
├── mobile/           # React Native / Expo mobile app
├── scripts/          # ATS discovery + runner scripts
├── docs/             # All documentation
├── docker-compose.yml
├── deploy.sh         # One-command server deploy
└── Launch Atlas.bat  # Local dev launcher
```

---

## Documentation

| Doc | What's in it |
|---|---|
| **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** | **Step-by-step server deploy, EAS mobile builds, ongoing workflow** |
| [docs/BUILD_NOTES.md](docs/BUILD_NOTES.md) | Operator notes: filtering jobs, profile vs qualification, mobile screen map |
| [docs/UNIFIED_PRODUCT_PLAN.md](docs/UNIFIED_PRODUCT_PLAN.md) | Product vision, architecture, phasing |
| [docs/PHASE_TICKETS.md](docs/PHASE_TICKETS.md) | Feature tickets with file-level pointers |
| [docs/CAREER_MEMORY_FACTS_AND_TIERS.md](docs/CAREER_MEMORY_FACTS_AND_TIERS.md) | Career memory fact types and tiers |
| [backend/README.md](backend/README.md) | Backend API reference, env vars, migrations |

---

## Job Sources (live)

| Source | File | Notes |
|---|---|---|
| RemoteOK | `collectors/remoteok.py` | |
| We Work Remotely | `collectors/weworkremotely.py` | |
| Arbeitnow | `collectors/arbeitnow.py` | |
| The Muse | `collectors/themuse.py` | |
| JSearch (RapidAPI) | `collectors/jsearch.py` | 200 req/mo free |
| Adzuna | `collectors/adzuna.py` | 250 calls/day free |
| Jobstash | `collectors/jobstash.py` | |
| Himalayas | `collectors/himalayas.py` | ~300 records/run |
| Jobicy | `collectors/jobicy.py` | ~30 records/run |
| Greenhouse/Lever/Ashby/etc. | `web3_ats.py` + CSV | 170+ boards |
| Workday | `collectors/workday.py` | Playwright |

---

## Dev Workflow

```
dev branch (local) → git push → GitHub → merge to main → deploy.sh on server
```

**Day-to-day:**
```powershell
git add -A
git commit -m "what changed"
git push
```

**Deploy to server:**
```powershell
git checkout main
git merge dev
git push
git checkout dev
# then on server: ./deploy.sh
```

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for the full server setup and mobile build guide.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + SQLAlchemy + Alembic + PostgreSQL |
| Collectors | httpx + Playwright (for Workday) |
| AI features | OpenAI gpt-4o-mini |
| Mobile | React Native + Expo SDK 54 + NativeWind |
| Builds | EAS (Expo Application Services) |
| Server | Docker Compose (`restart: unless-stopped`) |
| CI | GitHub Actions (pytest on backend changes) |

---

## Recent Updates (June 2026)

- **GitHub + Docker deploy pipeline** — repo on GitHub, `deploy.sh` for one-command server deploys, auto-restart on reboot
- **EAS mobile builds** — Android APK installable directly on phone without app store; iOS ready
- **Job sources expanded** — Himalayas, Jobicy, The Muse, JSearch re-enabled
- **AI application packages** — resume + cover letter generation via OpenAI
- **Career memory** — LLM fact extraction, approve/reject UI, rescore all jobs
- **Candidate profile** — contact info for resume/cover letter header
