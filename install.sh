#!/usr/bin/env bash
# =============================================================================
# AIM-Node — Quick Installer (Mac & Linux)
# =============================================================================
# Usage:
#   curl -fsSL https://get.ai.market/aim-node | bash
#
# What it does:
#   1. Checks Docker is installed
#   2. Downloads docker-compose.aim-node.yml into ./aim-node
#   3. Pulls ghcr.io/aidotmarket/aim-node:latest
#   4. Runs `docker compose up -d`
# =============================================================================
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "  ${CYAN}▸${NC} $*"; }
pass() { echo -e "  ${GREEN}✔${NC} $*"; }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }
die()  { echo -e "\n  ${RED}✘${NC} $*\n"; exit 1; }

REPO_RAW="https://raw.githubusercontent.com/aidotmarket/aim-node/main"
COMPOSE_URL="${REPO_RAW}/docker-compose.aim-node.yml"
IMAGE="ghcr.io/aidotmarket/aim-node:latest"
INSTALL_DIR="${AIM_NODE_INSTALL_DIR:-$HOME/aim-node}"

echo
echo -e "${BOLD}  ⚡ AIM-Node Installer${NC}"
echo

# --- Docker check -----------------------------------------------------------
if ! command -v docker &>/dev/null; then
  die "Docker is not installed. Install Docker Desktop or Docker Engine, then re-run this script.
      https://docs.docker.com/get-docker/"
fi

if ! docker info &>/dev/null; then
  die "Docker is installed but the daemon is not running. Start Docker Desktop / the service, then re-run."
fi
pass "Docker is ready"

# --- Install dir ------------------------------------------------------------
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
pass "Install dir: $INSTALL_DIR"

# --- Compose file -----------------------------------------------------------
info "Downloading docker-compose.aim-node.yml..."
if command -v curl &>/dev/null; then
  curl -fsSL "$COMPOSE_URL" -o docker-compose.aim-node.yml
elif command -v wget &>/dev/null; then
  wget -q "$COMPOSE_URL" -O docker-compose.aim-node.yml
else
  die "Neither curl nor wget is available."
fi
pass "Downloaded compose file"

# --- .env -------------------------------------------------------------------
if [[ ! -f .env ]]; then
  cat > .env <<EOF
# AIM-Node configuration
AIM_NODE_VERSION=latest
AIM_NODE_PORT=8080
AIM_API_URL=https://api.ai.market
AIM_NODE_NAME=my-node
EOF
  pass "Generated .env"
else
  info ".env already exists — keeping it"
fi

# --- Pull image -------------------------------------------------------------
info "Pulling $IMAGE..."
docker pull "$IMAGE" || die "Failed to pull $IMAGE"
pass "Image pulled"

# --- Start ------------------------------------------------------------------
info "Starting AIM-Node..."
docker compose -f docker-compose.aim-node.yml up -d || die "docker compose up failed"
pass "Containers started"

# --- Health -----------------------------------------------------------------
PORT=$(grep '^AIM_NODE_PORT=' .env | cut -d= -f2)
PORT="${PORT:-8080}"
URL="http://localhost:${PORT}/api/mgmt/health"

info "Waiting for health check at ${URL}..."
for i in $(seq 1 30); do
  if curl -fsS "$URL" >/dev/null 2>&1; then
    pass "AIM-Node is healthy"
    echo
    echo -e "${GREEN}${BOLD}  ✅ AIM-Node is running${NC}"
    echo -e "     Health:  ${URL}"
    echo -e "     Dir:     ${INSTALL_DIR}"
    echo -e "     Logs:    docker compose -f ${INSTALL_DIR}/docker-compose.aim-node.yml logs -f"
    echo
    exit 0
  fi
  sleep 2
done

warn "Health check did not pass within 60s — check logs:"
echo "    docker compose -f ${INSTALL_DIR}/docker-compose.aim-node.yml logs --tail=50"
exit 1
