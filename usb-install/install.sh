#!/bin/bash
# =============================================================================
# Atlas — USB Full Install Script
# =============================================================================
# What this does:
#   1. Installs the Atlas repo from the git bundle on this USB drive
#   2. Copies your .env file into place
#   3. Builds + starts Docker containers (Postgres + API)
#   4. Runs all database migrations
#   5. Restores the job database snapshot
#   6. Seeds your profile
#   7. Prints a summary with your server IP
#
# Requirements:
#   - Docker + Docker Compose already installed on the server
#   - This script, atlas.bundle, atlas.dump, and backend.env
#     all live in the same directory (the USB drive root)
#
# Usage:
#   sudo bash /media/<user>/ATLAS-USB/install.sh
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()    { echo -e "${CYAN}==>${NC} $*"; }
ok()     { echo -e "${GREEN}  ✓${NC} $*"; }
warn()   { echo -e "${YELLOW}  ⚠${NC} $*"; }
die()    { echo -e "${RED}  ✗ ERROR:${NC} $*"; exit 1; }
header() { echo -e "\n${BOLD}${CYAN}$*${NC}"; }

# ── Locate USB directory (where this script lives) ────────────────────────────
USB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log "USB source directory: $USB_DIR"

# ── Config ────────────────────────────────────────────────────────────────────
INSTALL_DIR="$HOME/atlas"
BUNDLE="$USB_DIR/atlas.bundle"
DUMP="$USB_DIR/atlas.dump"
ENV_FILE="$USB_DIR/backend.env"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
header "Step 0 — Pre-flight checks"

command -v docker &>/dev/null         || die "Docker is not installed."
docker compose version &>/dev/null    || die "Docker Compose plugin not found."

[ -f "$ENV_FILE" ] || die "backend.env not found in $USB_DIR"
[ -f "$DUMP" ]     || die "atlas.dump not found in $USB_DIR"
[ -f "$BUNDLE" ]   && ok "Git bundle found (offline install)" || log "No bundle — will clone from GitHub"

ok "Docker present"
ok "Required files found"

# ── Step 1 — Clone repo (bundle if present, else GitHub) ─────────────────────
header "Step 1 — Installing Atlas repo"

if [ -d "$INSTALL_DIR/.git" ]; then
    warn "Atlas already exists at $INSTALL_DIR — skipping clone."
    warn "To do a clean reinstall: rm -rf $INSTALL_DIR and re-run this script."
else
    if [ -f "$BUNDLE" ]; then
        log "Cloning from local bundle into $INSTALL_DIR..."
        git clone "$BUNDLE" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
        git remote set-url origin https://github.com/gillettdave/atlas.git
    else
        log "No bundle found — cloning from GitHub..."
        git clone https://github.com/gillettdave/atlas.git "$INSTALL_DIR"
    fi
    ok "Repo cloned"
fi

cd "$INSTALL_DIR"

# Ensure we're on main
git checkout main 2>/dev/null || true
ok "On branch: main"

# ── Step 2 — .env file ────────────────────────────────────────────────────────
header "Step 2 — Installing .env"

cp "$ENV_FILE" "$INSTALL_DIR/backend/.env"
ok "backend/.env installed"

# Validate ATLAS_DB_PASSWORD is present and not the placeholder
DB_PASS="$(grep -m1 '^ATLAS_DB_PASSWORD=' backend/.env | cut -d= -f2- | tr -d '[:space:]')"
if [ -z "$DB_PASS" ] || [[ "$DB_PASS" == *"CHANGEME"* ]]; then
    die "ATLAS_DB_PASSWORD in backend.env is missing or still set to CHANGEME. Fix it and re-run."
fi
ok "ATLAS_DB_PASSWORD looks good"

# Export for docker-compose
export ATLAS_DB_PASSWORD="$DB_PASS"

# ── Step 3 — Deploy (build + start + migrate) ─────────────────────────────────
header "Step 3 — Building and starting containers"

chmod +x deploy.sh
./deploy.sh

# deploy.sh prints its own status and runs migrations — we continue after it exits.

# ── Step 4 — Wait for DB healthy (extra safety margin post-deploy) ─────────────
header "Step 4 — Confirming database is healthy"

RETRIES=20
until docker compose exec db pg_isready -U atlas -q 2>/dev/null; do
    RETRIES=$((RETRIES - 1))
    [ $RETRIES -le 0 ] && die "Database never became healthy. Check: docker compose logs db"
    log "Waiting for database... ($RETRIES attempts left)"
    sleep 3
done
ok "Database is healthy"

# ── Step 5 — Restore DB dump ──────────────────────────────────────────────────
header "Step 5 — Restoring job database snapshot"

log "This may take a minute for large datasets..."

# Copy dump into container then restore (avoids piping issues with docker compose exec)
docker compose cp "$DUMP" db:/tmp/atlas.dump
docker compose exec db pg_restore \
    -U atlas \
    -d atlas \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    -v \
    /tmp/atlas.dump 2>&1 | tail -20

ok "Database snapshot restored"

# ── Step 6 — Seed profile ─────────────────────────────────────────────────────
header "Step 6 — Seeding user profile"

docker compose exec api python scripts/seed_david_profile.py
ok "Profile seeded"

# ── Step 7 — Final health check ───────────────────────────────────────────────
header "Step 7 — Final health check"

sleep 2
HEALTH=$(curl -sf http://localhost:8000/health 2>/dev/null || echo "FAILED")

if [[ "$HEALTH" == *'"status":"ok"'* ]] || [[ "$HEALTH" == *'"status": "ok"'* ]]; then
    ok "API is healthy"
    echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
else
    warn "Health check returned unexpected response — check logs."
    echo "$HEALTH"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
SERVER_IP="$(hostname -I | awk '{print $1}')"

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║           Atlas install complete!                   ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}API URL:${NC}    http://${SERVER_IP}:8000"
echo -e "  ${BOLD}Health:${NC}     http://${SERVER_IP}:8000/health"
echo -e "  ${BOLD}Logs:${NC}       docker compose -f $INSTALL_DIR/docker-compose.yml logs -f api"
echo ""
echo -e "  ${BOLD}Next step:${NC}  Update mobile/eas.json on your Windows machine:"
echo -e "            \"EXPO_PUBLIC_API_BASE\": \"http://${SERVER_IP}:8000\""
echo -e "            Then run: eas build --profile preview --platform android"
echo ""
echo -e "  ${BOLD}To deploy updates later:${NC}"
echo -e "            cd $INSTALL_DIR && ./deploy.sh"
echo ""
