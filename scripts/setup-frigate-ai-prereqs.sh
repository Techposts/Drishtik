#!/usr/bin/env bash
# =============================================================================
# Frigate → OpenClaw → AI Security Pipeline — Prerequisites Check
# =============================================================================
# This script verifies system requirements and provides install guidance.
# It does NOT modify your system.
#
# Run: bash setup-frigate-ai-prereqs.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors & helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

banner() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${BLUE}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

info()    { echo -e "  ${BLUE}ℹ${NC}  $1"; }
success() { echo -e "  ${GREEN}✔${NC}  $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC}  $1"; }
fail()    { echo -e "  ${RED}✖${NC}  $1"; }

ask_yn() {
    local prompt="$1"
    local default="$2"
    local varname="$3"
    echo -ne "  ${GREEN}?${NC}  ${prompt} ${YELLOW}[${default}]${NC}: "
    read -r input
    input="${input:-$default}"
    if [[ "$input" =~ ^[Yy] ]]; then
        eval "$varname=yes"
    else
        eval "$varname=no"
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
banner "Frigate → OpenClaw AI Security Pipeline — Prerequisites"

echo ""
echo -e "  This script checks required components and prints install guidance."
echo -e "  It does NOT make any changes."
echo ""

ask_yn "Run checks now?" "Y" READY
if [[ "$READY" != "yes" ]]; then
    echo "  Cancelled."
    exit 0
fi

banner "Checking Requirements"

PREFLIGHT_PASS=0
PREFLIGHT_WARN=0

# ── Python ──
PYTHON_BIN=""
for py in python3.12 python3.11 python3.10 python3; do
    if command -v "$py" &>/dev/null; then
        PYTHON_BIN="$py"
        break
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    fail "Python 3.10+ not found."
    echo -e "       ${YELLOW}Install:${NC} sudo apt install python3 python3-venv python3-full"
else
    PY_VERSION=$($PYTHON_BIN --version 2>&1)
    success "Python: $PY_VERSION ($PYTHON_BIN)"
    ((PREFLIGHT_PASS++))

    if $PYTHON_BIN -m venv --help &>/dev/null; then
        success "python3-venv module available"
        ((PREFLIGHT_PASS++))
    else
        fail "python3-venv not installed."
        echo -e "       ${YELLOW}Install:${NC} sudo apt install python3-venv python3-full"
        ((PREFLIGHT_WARN++))
    fi
fi

# ── curl ──
if command -v curl &>/dev/null; then
    success "curl available"
    ((PREFLIGHT_PASS++))
else
    fail "curl not found — required for API calls"
    echo -e "       ${YELLOW}Install:${NC} sudo apt install curl"
    ((PREFLIGHT_WARN++))
fi

# ── Docker ──
HAS_DOCKER=no
if command -v docker &>/dev/null; then
    success "Docker: $(docker --version 2>&1 | head -1)"
    HAS_DOCKER=yes
    ((PREFLIGHT_PASS++))
else
    warn "Docker not found — required for Frigate Docker install"
    echo -e "       ${YELLOW}Install:${NC} https://docs.docker.com/engine/install/"
    ((PREFLIGHT_WARN++))
fi

# ── Frigate container ──
FRIGATE_RUNNING=no
if [[ "$HAS_DOCKER" == "yes" ]]; then
    FRIGATE_STATUS=$(docker ps --filter name=frigate --format '{{.Names}} {{.Status}}' 2>/dev/null || true)
    if [[ -n "$FRIGATE_STATUS" ]]; then
        success "Frigate container: $FRIGATE_STATUS"
        FRIGATE_RUNNING=yes
        ((PREFLIGHT_PASS++))
    else
        warn "Frigate container is NOT running."
        echo -e "       ${YELLOW}Start:${NC} docker start frigate"
        echo -e "       ${YELLOW}Install:${NC} https://docs.frigate.video/installation"
        ((PREFLIGHT_WARN++))
    fi
fi

# ── Frigate API reachable ──
if [[ "$FRIGATE_RUNNING" == "yes" ]]; then
    if curl -s --max-time 5 http://localhost:5000/api/version &>/dev/null; then
        FRIGATE_VER=$(curl -s --max-time 5 http://localhost:5000/api/version 2>/dev/null || echo "unknown")
        success "Frigate API reachable at :5000 (version: $FRIGATE_VER)"
        ((PREFLIGHT_PASS++))
    else
        warn "Frigate API not responding at http://localhost:5000"
        echo -e "       ${YELLOW}Check:${NC} docker logs frigate --tail 20"
        ((PREFLIGHT_WARN++))
    fi
fi

# ── systemd ──
if command -v systemctl &>/dev/null; then
    success "systemd available"
    ((PREFLIGHT_PASS++))
else
    warn "systemd not found — service auto-start will be skipped"
    ((PREFLIGHT_WARN++))
fi

# ── OpenClaw ──
if command -v openclaw &>/dev/null || [[ -f "$HOME/.npm-global/lib/node_modules/openclaw/dist/index.js" ]]; then
    success "OpenClaw installed"
    ((PREFLIGHT_PASS++))
else
    warn "OpenClaw not found."
    echo -e "       ${YELLOW}Install:${NC} npm install -g openclaw"
    ((PREFLIGHT_WARN++))
fi

# ── OpenClaw gateway running ──
if command -v systemctl &>/dev/null; then
    if systemctl --user is-active openclaw-gateway.service &>/dev/null; then
        success "OpenClaw gateway service: active"
        ((PREFLIGHT_PASS++))
    else
        warn "OpenClaw gateway service is NOT running."
        echo -e "       ${YELLOW}Start:${NC} systemctl --user start openclaw-gateway.service"
        ((PREFLIGHT_WARN++))
    fi
fi

# Check gateway port reachable
if curl -s --max-time 5 http://localhost:18789/ &>/dev/null; then
    success "OpenClaw gateway reachable at :18789"
    ((PREFLIGHT_PASS++))
else
    warn "OpenClaw gateway not responding at http://localhost:18789"
    echo -e "       ${YELLOW}The gateway must be running for the pipeline to work.${NC}"
    ((PREFLIGHT_WARN++))
fi

# ── OpenClaw config exists ──
if [[ -f "$HOME/.openclaw/openclaw.json" ]]; then
    success "OpenClaw config found: ~/.openclaw/openclaw.json"
    ((PREFLIGHT_PASS++))
else
    warn "OpenClaw config not found at ~/.openclaw/openclaw.json"
    echo -e "       ${YELLOW}Run:${NC} openclaw doctor  (to initialize config)"
    ((PREFLIGHT_WARN++))
fi

# ── OpenClaw workspace/media paths ──
OPENCLAW_WS="$HOME/.openclaw/workspace"
OPENCLAW_MEDIA="$HOME/.openclaw/workspace/ai-snapshots"
OPENCLAW_SESSIONS="$HOME/.openclaw/agents/main/sessions"
OPENCLAW_SESSIONS_INDEX="$OPENCLAW_SESSIONS/sessions.json"

if [[ -d "$OPENCLAW_WS" ]]; then
    success "OpenClaw workspace: $OPENCLAW_WS"
    ((PREFLIGHT_PASS++))
else
    warn "OpenClaw workspace missing: $OPENCLAW_WS"
    echo -e "       ${YELLOW}Fix:${NC} openclaw doctor  (initializes workspace)"
    ((PREFLIGHT_WARN++))
fi

if [[ -d "$OPENCLAW_MEDIA" ]]; then
    success "OpenClaw media path exists: $OPENCLAW_MEDIA"
    ((PREFLIGHT_PASS++))
else
    warn "OpenClaw media path missing: $OPENCLAW_MEDIA"
    echo -e "       ${YELLOW}Fix:${NC} mkdir -p $OPENCLAW_MEDIA"
    ((PREFLIGHT_WARN++))
fi

if [[ -d "$OPENCLAW_SESSIONS" ]]; then
    success "OpenClaw sessions dir: $OPENCLAW_SESSIONS"
    ((PREFLIGHT_PASS++))
else
    warn "OpenClaw sessions dir missing: $OPENCLAW_SESSIONS"
    echo -e "       ${YELLOW}Fix:${NC} openclaw doctor  (initializes sessions)"
    ((PREFLIGHT_WARN++))
fi

if [[ -f "$OPENCLAW_SESSIONS_INDEX" ]]; then
    success "OpenClaw sessions index: $OPENCLAW_SESSIONS_INDEX"
    ((PREFLIGHT_PASS++))
else
    warn "OpenClaw sessions index missing: $OPENCLAW_SESSIONS_INDEX"
    echo -e "       ${YELLOW}Fix:${NC} openclaw doctor  (creates sessions.json)"
    ((PREFLIGHT_WARN++))
fi

# ── MQTT test tools ──
if command -v mosquitto_pub &>/dev/null; then
    success "mosquitto-clients available (for MQTT testing)"
    ((PREFLIGHT_PASS++))
else
    info "mosquitto-clients not installed (optional, for manual MQTT testing)"
    echo -e "       ${YELLOW}Install:${NC} sudo apt install mosquitto-clients"
fi

# ── Coral TPU hint ──
if ls /dev/apex_0 &>/dev/null; then
    success "Coral TPU detected at /dev/apex_0"
    ((PREFLIGHT_PASS++))
else
    warn "Coral TPU not detected at /dev/apex_0"
    echo -e "       ${YELLOW}Check:${NC} lsusb | grep -i coral  (USB) or lspci | grep -i coral (PCIe)"
    ((PREFLIGHT_WARN++))
fi

# ── Summary ──
echo ""
echo -e "  ${BOLD}Preflight: ${GREEN}$PREFLIGHT_PASS passed${NC}, ${YELLOW}$PREFLIGHT_WARN warnings${NC}"
echo ""
echo -e "  Next: Run ${YELLOW}setup-frigate-ai.sh${NC} to configure the pipeline."
