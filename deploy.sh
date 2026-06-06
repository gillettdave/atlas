#!/bin/bash
# Atlas deploy script — run on the Linux server.
# First run: full setup. Subsequent runs: pull + restart.
set -e

# ── Config ────────────────────────────────────────────────────────────────────
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="main"

echo "==> Atlas deploy starting in $APP_DIR"

# ── 1. Pull latest code ───────────────────────────────────────────────────────
echo "==> Pulling $BRANCH..."
git fetch origin
git checkout $BRANCH
git pull origin $BRANCH

# ── 2. Ensure .env exists ─────────────────────────────────────────────────────
if [ ! -f "$APP_DIR/backend/.env" ]; then
    echo ""
    echo "ERROR: backend/.env not found."
    echo "  Copy backend/.env.example to backend/.env and fill in your values."
    echo "  Then re-run this script."
    exit 1
fi

# ── 3. Ensure ATLAS_DB_PASSWORD is set ───────────────────────────────────────
if [ -z "$ATLAS_DB_PASSWORD" ]; then
    # Try loading it from .env as a fallback
    export $(grep -v '^#' "$APP_DIR/backend/.env" | grep ATLAS_DB_PASSWORD | xargs) 2>/dev/null || true
fi
if [ -z "$ATLAS_DB_PASSWORD" ]; then
    echo ""
    echo "ERROR: ATLAS_DB_PASSWORD is not set."
    echo "  Add it to backend/.env or export it in your shell before running deploy.sh"
    exit 1
fi

# ── 4. Build + start containers ───────────────────────────────────────────────
echo "==> Building and starting containers..."
docker compose pull db   # always get latest postgres patch
docker compose build api --no-cache
docker compose up -d

# ── 5. Wait for DB to be healthy ──────────────────────────────────────────────
echo "==> Waiting for database..."
until docker compose exec db pg_isready -U atlas -q; do
    sleep 2
done
echo "    Database ready."

# ── 6. Run migrations ─────────────────────────────────────────────────────────
echo "==> Running migrations..."
docker compose exec api alembic upgrade head

# ── 7. Health check ───────────────────────────────────────────────────────────
echo "==> Checking API health..."
sleep 2
curl -sf http://localhost:8000/health | python3 -m json.tool || {
    echo "WARNING: Health check failed — check logs with: docker compose logs api"
}

echo ""
echo "✓ Atlas is running."
echo "  API:  http://$(hostname -I | awk '{print $1}'):8000"
echo "  Logs: docker compose logs -f api"
echo "  Stop: docker compose down"
