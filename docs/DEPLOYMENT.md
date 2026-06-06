# Atlas — Server Deployment Guide

## Overview

- **Dev machine (Windows):** always on `dev` branch, push changes to GitHub
- **Linux server:** always on `main` branch, runs the live app
- **Deploy flow:** merge `dev` → `main` on GitHub, then run `./deploy.sh` on the server

Docker is already installed on the server. The stack runs as two containers
(`api` + `db`) that auto-restart on server reboot via `restart: unless-stopped`.

---

## First-Time Server Setup

Docker is already installed, so skip straight to cloning:

```bash
# 1. Clone the repo
git clone https://github.com/gillettdave/atlas.git
cd atlas

# 2. Create your .env from the example and fill in real values
cp backend/.env.example backend/.env
nano backend/.env
```

Key values to set in `backend/.env`:
- `ATLAS_DB_PASSWORD` — a strong password for the Postgres container (make one up, you won't type it manually)
- `ATLAS_OPENAI_API_KEY` — your OpenAI key
- `ATLAS_JSEARCH_API_KEY` — RapidAPI key
- `ATLAS_ADZUNA_APP_ID` / `ATLAS_ADZUNA_APP_KEY` — Adzuna credentials
- `ATLAS_GMAIL_IMAP_USERNAME` / `ATLAS_GMAIL_IMAP_PASSWORD` — Gmail app password

```bash
# 3. Make deploy script executable and run it
chmod +x deploy.sh
./deploy.sh
```

That's it. The script will:
1. Pull latest `main`
2. Build the API container
3. Start Postgres + API
4. Run database migrations
5. Print the server's local IP and a health check

---

## Every Subsequent Deploy

On your dev machine, when you're ready to ship:
```powershell
# Merge dev into main and push
git checkout main
git merge dev
git push
git checkout dev
```

Then on the server:
```bash
cd ~/atlas
./deploy.sh
```

---

## Useful Server Commands

```bash
# View live logs
docker compose logs -f api

# View last 100 lines
docker compose logs --tail=100 api

# Restart just the API (e.g. after editing .env)
docker compose restart api

# Stop everything
docker compose down

# Stop and wipe the database (DESTRUCTIVE — loses all data)
docker compose down -v

# Open a shell inside the API container
docker compose exec api bash

# Run a one-off script (e.g. seed profile)
docker compose exec api python scripts/seed_david_profile.py

# Run ATS board discovery
docker compose exec api python scripts/discover_ats_boards.py --max-searches 40

# Check container status
docker compose ps
```

---

## Accessing the API from Your Phone

While on the same network as the server:
- Set `EXPO_PUBLIC_API_BASE=http://<server-local-ip>:8000` in `mobile/.env`

From anywhere (requires port forwarding or a tunnel):
- Set up port forwarding on your router: external port 8000 → server local IP port 8000
- Or use Cloudflare Tunnel for HTTPS without port forwarding (required for App Store builds)

---

## Architecture

```
GitHub (main branch)
       │
       ▼
  Linux Server
  ┌─────────────────────────────┐
  │  docker compose             │
  │  ┌──────────┐ ┌──────────┐  │
  │  │  api     │ │  db      │  │
  │  │ FastAPI  │ │Postgres  │  │
  │  │ :8000    │ │ :5432    │  │
  │  └──────────┘ └──────────┘  │
  │  postgres_data (volume)     │
  └─────────────────────────────┘
```

Both containers use `restart: unless-stopped` — they come back automatically
after a server reboot without any manual intervention.

---

## Troubleshooting

**API won't start:**
```bash
docker compose logs api
```

**Database connection error:**
- Check `ATLAS_DB_PASSWORD` matches in both `.env` and the running db container
- `docker compose ps` — confirm db shows as healthy

**Migrations failed:**
```bash
docker compose exec api alembic upgrade head
```

**Port 8000 already in use:**
- Another service is on that port. Change the host-side port in `docker-compose.yml`:
  `"8001:8000"` maps server port 8001 → container port 8000
