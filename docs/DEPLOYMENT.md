# Atlas — Deployment Guide

## Overview

| Where | Branch | Purpose |
|---|---|---|
| Windows dev machine | `dev` | Active development |
| GitHub | `main` / `dev` | Source of truth |
| Linux server | `main` | Live backend, runs 24/7 |
| Phone (Android) | — | Native app via EAS build |

**Flow:** Code on `dev` → push to GitHub → merge to `main` → pull on server → app on phone points at server.

---

## Part 1 — First-Time Linux Server Setup

> Docker is already installed. These steps only need to be done once.

### Step 1 — Clone the repo

SSH into your server, then:

```bash
cd ~
git clone https://github.com/gillettdave/atlas.git
cd atlas
```

### Step 2 — Create your .env file

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Fill in these values (copy from your Windows `.env`):

| Key | What it is |
|---|---|
| `ATLAS_DB_PASSWORD` | Make up a strong password — you won't type it manually |
| `ATLAS_OPENAI_API_KEY` | Your OpenAI key |
| `ATLAS_JSEARCH_API_KEY` | RapidAPI key |
| `ATLAS_ADZUNA_APP_ID` / `ATLAS_ADZUNA_APP_KEY` | Adzuna credentials |
| `ATLAS_GMAIL_IMAP_USERNAME` / `ATLAS_GMAIL_IMAP_PASSWORD` | Gmail app password |

Save and exit (`Ctrl+X`, `Y`, `Enter` in nano).

### Step 3 — Make the deploy script executable

```bash
chmod +x deploy.sh
```

### Step 4 — Run the deploy script

```bash
./deploy.sh
```

This will:
1. Pull the latest `main` branch
2. Build the API Docker container
3. Start Postgres + API (both set to auto-restart on reboot)
4. Wait for the database to be healthy
5. Run all database migrations
6. Print a health check confirming everything is running

### Step 5 — Note your server's local IP

```bash
hostname -I
```

You'll need this IP to point the mobile app at the server. It'll look like `192.168.x.x`.

### Step 6 — Run the one-time seed script

```bash
docker compose exec api python scripts/seed_david_profile.py
```

That's it — the backend is live and will restart automatically if the server reboots.

---

## Part 2 — Point the Mobile App at the Server

Do this once after you have the server IP from Step 5 above.

### On your Windows dev machine:

**1. Update `mobile/eas.json`** — replace `YOUR_SERVER_LOCAL_IP` with your real IP:

```json
"preview": {
  "distribution": "internal",
  "env": {
    "EXPO_PUBLIC_API_BASE": "http://192.168.x.x:8000"
  }
}
```

**2. Commit and push:**

```powershell
cd "C:\Users\fishd\Dropbox\Apps and Bots\ATS Bot"
git add mobile/eas.json
git commit -m "Set server IP in preview build profile"
git push
```

**3. Rebuild the Android app:**

```powershell
cd mobile
eas build --profile preview --platform android --non-interactive
```

EAS will email you when done (~10 min). Install the new build on your phone — it will now talk to your live server.

---

## Part 3 — Ongoing Dev Workflow

### Making changes (on Windows)

```powershell
# Edit code, then:
git add -A
git commit -m "describe what you changed"
git push
```

### Deploying to the server

```powershell
# On Windows — merge dev into main
git checkout main
git merge dev
git push
git checkout dev
```

```bash
# On the server — pull and restart
cd ~/atlas
./deploy.sh
```

### Rebuilding the mobile app

Only needed when you change the mobile app code. Backend-only changes don't require a rebuild.

```powershell
cd "C:\Users\fishd\Dropbox\Apps and Bots\ATS Bot\mobile"
eas build --profile preview --platform android --non-interactive
```

---

## Part 4 — Useful Server Commands

```bash
# Check what's running
docker compose ps

# View live API logs
docker compose logs -f api

# View last 100 lines of logs
docker compose logs --tail=100 api

# Restart just the API (e.g. after editing .env)
docker compose restart api

# Stop everything
docker compose down

# Open a shell inside the API container
docker compose exec api bash

# Run ATS board discovery (weekly)
docker compose exec api python scripts/discover_ats_boards.py --max-searches 40

# Run database migrations manually (if needed)
docker compose exec api alembic upgrade head

# Stop and WIPE the database (DESTRUCTIVE — loses all data)
docker compose down -v
```

---

## Part 5 — Architecture

```
Your Windows PC (dev)
        │  git push
        ▼
   GitHub (dev/main)
        │  git pull (via deploy.sh)
        ▼
  Linux Home Server
  ┌──────────────────────────────┐
  │  docker compose              │
  │  ┌──────────┐  ┌──────────┐  │
  │  │  api     │  │   db     │  │
  │  │ FastAPI  │  │Postgres  │  │
  │  │ :8000    │  │          │  │
  │  └──────────┘  └──────────┘  │
  │   postgres_data (volume)     │
  └──────────────────────────────┘
        │  http://server-ip:8000
        ▼
  Android Phone
  (EAS preview build)
```

Both containers use `restart: unless-stopped` — they come back automatically after a server reboot.

---

## Part 6 — Troubleshooting

**App won't connect to server:**
- Confirm the server and phone are on the same WiFi network
- Check the IP in `eas.json` matches `hostname -I` on the server
- Confirm API is running: `docker compose ps`
- Test from server: `curl http://localhost:8000/health`

**API container won't start:**
```bash
docker compose logs api
```

**Database connection error:**
- Check `ATLAS_DB_PASSWORD` is set in `backend/.env`
- `docker compose ps` — confirm `db` shows as `healthy`

**Migrations failed:**
```bash
docker compose exec api alembic upgrade head
```

**Port 8000 already in use by another bot:**
- Edit `docker-compose.yml` — change `"8000:8000"` to `"8001:8000"`
- Update `eas.json` to use port 8001

**Get crash logs from Android phone (USB):**
```powershell
adb logcat -b crash -d
```

---

## Part 7 — EAS Build Reference

| Profile | API points at | Use for |
|---|---|---|
| `development` | localhost:8000 | Local dev with Expo Go |
| `preview` | your server's LAN IP | Your phone, daily use |
| `production` | public domain (HTTPS) | App Store / Play Store |

**Build commands (run from `mobile/` directory):**

```powershell
# Android preview (install via link/QR)
eas build --profile preview --platform android --non-interactive

# iOS preview
eas build --profile preview --platform ios --non-interactive

# Push a JS-only update (no full rebuild needed)
eas update --branch preview --message "what changed"
```

**App Store / Play Store (future):**
```powershell
eas build --profile production --platform ios
eas build --profile production --platform android
eas submit --platform ios
eas submit --platform android
```

> **Note:** App Store requires HTTPS. Set up Cloudflare Tunnel on the server first for a free domain + SSL certificate.
