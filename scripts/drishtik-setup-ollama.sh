#!/usr/bin/env bash
# =============================================================================
# Drishtik AI Security System — Ollama VLM Setup (Mac + Linux)
# =============================================================================
# Sets up Ollama with qwen2.5vl:7b on your AI machine so the Frigate bridge
# on the Debian server can call it over LAN for vision analysis.
#
# Works on: macOS (Apple Silicon), Linux (x86_64 / arm64)
#
# Run:  bash drishtik-setup-ollama.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors & helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

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

ask() {
    local prompt="$1" default="$2" varname="$3"
    if [[ -n "$default" ]]; then
        echo -ne "  ${GREEN}?${NC}  ${prompt} ${YELLOW}[${default}]${NC}: "
        read -r input
        printf -v "$varname" '%s' "${input:-$default}"
    else
        echo -ne "  ${GREEN}?${NC}  ${prompt}: "
        read -r input
        printf -v "$varname" '%s' "$input"
    fi
}

ask_yn() {
    local prompt="$1" default="$2" varname="$3"
    echo -ne "  ${GREEN}?${NC}  ${prompt} ${YELLOW}[${default}]${NC}: "
    read -r input
    input="${input:-$default}"
    [[ "$input" =~ ^[Yy] ]] && printf -v "$varname" '%s' "yes" || printf -v "$varname" '%s' "no"
}

# ---------------------------------------------------------------------------
# Detect platform
# ---------------------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"
IS_MAC=no
IS_LINUX=no

if [[ "$OS" == "Darwin" ]]; then
    IS_MAC=yes
    if [[ "$ARCH" != "arm64" ]]; then
        warn "Intel Mac detected — Apple Silicon (M1+) recommended for best performance"
    fi
elif [[ "$OS" == "Linux" ]]; then
    IS_LINUX=yes
else
    fail "Unsupported OS: $OS (need macOS or Linux)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Welcome
# ---------------------------------------------------------------------------
banner "Drishtik AI — Ollama Vision Model Setup"

echo ""
echo -e "  This script sets up Ollama with the ${BOLD}qwen2.5vl:7b${NC} vision model"
echo -e "  on this machine so the Frigate bridge can call it over LAN."
echo ""
echo -e "  ${BOLD}Detected:${NC} $OS ($ARCH)"
echo ""
echo -e "  ${YELLOW}Steps:${NC}"
echo -e "    1. Install Ollama"
echo -e "    2. Pull the vision model (~4.7 GB)"
echo -e "    3. Configure LAN access"
echo -e "    4. Set up auto-start on boot"
echo -e "    5. Verify the endpoint"
echo ""

# RAM check
if [[ "$IS_MAC" == "yes" ]]; then
    RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
else
    RAM_BYTES=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2 * 1024}' || echo 0)
fi
RAM_GB=$(( RAM_BYTES / 1073741824 ))

if [[ $RAM_GB -lt 8 ]]; then
    fail "At least 8 GB RAM required (detected: ${RAM_GB} GB)"
    exit 1
fi
success "${RAM_GB} GB RAM detected"

ask_yn "Ready to begin?" "Y" READY
[[ "$READY" != "yes" ]] && echo "  Cancelled." && exit 0

# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — Install Ollama
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 1/5 — Install Ollama"

ERRORS=0

if command -v ollama &>/dev/null; then
    OLLAMA_BIN="$(command -v ollama)"
    success "Ollama already installed: $OLLAMA_BIN"
else
    info "Installing Ollama..."
    if [[ "$IS_MAC" == "yes" ]] && command -v brew &>/dev/null; then
        brew install ollama
    else
        curl -fsSL https://ollama.com/install.sh | sh
    fi

    OLLAMA_BIN="$(command -v ollama 2>/dev/null || echo "")"
    if [[ -z "$OLLAMA_BIN" ]]; then
        for p in /usr/local/bin/ollama /opt/homebrew/bin/ollama; do
            [[ -x "$p" ]] && OLLAMA_BIN="$p" && break
        done
    fi
    if [[ -z "$OLLAMA_BIN" ]]; then
        fail "Ollama install failed — install manually: https://ollama.com/download"
        exit 1
    fi
    success "Ollama installed: $OLLAMA_BIN"
fi

OLLAMA_ABS="$(readlink -f "$OLLAMA_BIN" 2>/dev/null || echo "$OLLAMA_BIN")"

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — Pull model
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 2/5 — Pull Vision Model"

MODEL="qwen2.5vl:7b"

# Start server temporarily if not running
OLLAMA_WAS_RUNNING=no
if pgrep -f "ollama serve" &>/dev/null; then
    OLLAMA_WAS_RUNNING=yes
    success "Ollama server already running"
else
    info "Starting Ollama server..."
    "$OLLAMA_BIN" serve &>/dev/null &
    OLLAMA_PID=$!
    sleep 3
fi

if "$OLLAMA_BIN" list 2>/dev/null | grep -q "$MODEL"; then
    success "Model $MODEL already pulled"
else
    info "Pulling $MODEL (~4.7 GB)..."
    echo ""
    "$OLLAMA_BIN" pull "$MODEL"
    echo ""
    if "$OLLAMA_BIN" list 2>/dev/null | grep -q "$MODEL"; then
        success "Model $MODEL pulled"
    else
        fail "Failed to pull $MODEL"
        exit 1
    fi
fi

# Stop temp server
if [[ "$OLLAMA_WAS_RUNNING" == "no" && -n "${OLLAMA_PID:-}" ]]; then
    kill "$OLLAMA_PID" 2>/dev/null || true
    wait "$OLLAMA_PID" 2>/dev/null || true
fi

# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — LAN access
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 3/5 — Configure LAN Access"

info "Ollama defaults to localhost. We'll bind it to 0.0.0.0 for LAN access."
echo ""

# Detect LAN IP
LAN_IP=""
if [[ "$IS_MAC" == "yes" ]]; then
    for iface in en0 en1; do
        ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
        [[ -n "$ip" ]] && LAN_IP="$ip" && break
    done
else
    LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
fi

ask "This machine's LAN IP" "$LAN_IP" LAN_IP
OLLAMA_PORT=11434
ask "Ollama port" "$OLLAMA_PORT" OLLAMA_PORT

OLLAMA_HOST="0.0.0.0:${OLLAMA_PORT}"
OLLAMA_URL="http://${LAN_IP}:${OLLAMA_PORT}"
success "Ollama will listen on $OLLAMA_HOST (reachable at $OLLAMA_URL)"

# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — Auto-start
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 4/5 — Auto-Start Service"

if [[ "$IS_MAC" == "yes" ]]; then
    # ── macOS: launchd ──
    PLIST_DIR="$HOME/Library/LaunchAgents"
    PLIST_FILE="$PLIST_DIR/com.ollama.serve.plist"
    PLIST_LABEL="com.ollama.serve"

    # Stop existing
    if pgrep -f "ollama serve" &>/dev/null; then
        pkill -f "ollama serve" 2>/dev/null || true
        sleep 2
    fi
    [[ -f "$PLIST_FILE" ]] && launchctl unload "$PLIST_FILE" 2>/dev/null || true

    mkdir -p "$PLIST_DIR"
    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${OLLAMA_ABS}</string>
        <string>serve</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_HOST</key>
        <string>${OLLAMA_HOST}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/ollama-serve.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ollama-serve.err</string>
</dict>
</plist>
EOF
    launchctl load "$PLIST_FILE"
    sleep 3
    success "launchd service created and started"

else
    # ── Linux: systemd ──
    info "Configuring Ollama systemd service for LAN access..."

    # Ollama's install script creates /etc/systemd/system/ollama.service
    if [[ -f /etc/systemd/system/ollama.service ]]; then
        # Add OLLAMA_HOST environment override
        sudo mkdir -p /etc/systemd/system/ollama.service.d
        sudo tee /etc/systemd/system/ollama.service.d/lan-access.conf > /dev/null << EOF
[Service]
Environment="OLLAMA_HOST=${OLLAMA_HOST}"
EOF
        sudo systemctl daemon-reload
        sudo systemctl restart ollama
        sudo systemctl enable ollama > /dev/null 2>&1
        sleep 3
        success "systemd override created — Ollama listening on $OLLAMA_HOST"
    else
        warn "Ollama systemd service not found — setting OLLAMA_HOST in .bashrc"
        echo "export OLLAMA_HOST=\"$OLLAMA_HOST\"" >> "$HOME/.bashrc"
        # Start manually
        OLLAMA_HOST="$OLLAMA_HOST" "$OLLAMA_BIN" serve &>/dev/null &
        sleep 3
        success "Ollama started manually (add to startup yourself)"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════
# STEP 5 — Verify
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 5/5 — Verify Endpoint"

# Local check
info "Testing local endpoint..."
TAGS_RESP=$(curl -sf "http://127.0.0.1:${OLLAMA_PORT}/api/tags" 2>/dev/null || echo "")
if [[ -n "$TAGS_RESP" ]] && echo "$TAGS_RESP" | grep -q "$MODEL"; then
    success "Local: $MODEL found"
else
    warn "Local endpoint not responding yet — may still be starting"
    ((ERRORS++)) || true
fi

# LAN check
info "Testing LAN endpoint at $OLLAMA_URL..."
LAN_RESP=$(curl -sf "${OLLAMA_URL}/api/tags" --connect-timeout 5 2>/dev/null || echo "")
if [[ -n "$LAN_RESP" ]] && echo "$LAN_RESP" | grep -q "models"; then
    success "LAN: reachable at $OLLAMA_URL"
else
    warn "LAN endpoint not reachable — check firewall"
    ((ERRORS++)) || true
fi

# ═══════════════════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════════════════
banner "Ollama Setup Complete!"

if [[ $ERRORS -gt 0 ]]; then
    echo -e "  ${YELLOW}Completed with $ERRORS warning(s)${NC}"
else
    echo -e "  ${GREEN}All steps completed successfully!${NC}"
fi

echo ""
echo -e "  ${BOLD}Ollama Configuration${NC}"
echo -e "    Model:     $MODEL"
echo -e "    LAN URL:   ${BOLD}$OLLAMA_URL${NC}"
echo ""
echo -e "  ${BOLD}On Your Debian Server${NC}"
echo -e "    Verify:  ${CYAN}curl ${OLLAMA_URL}/api/tags${NC}"
echo ""
echo -e "    The bridge config (bridge-runtime-config.json) needs:"
echo -e "      ${CYAN}\"ollama_api\": \"$OLLAMA_URL\"${NC}"
echo -e "      ${CYAN}\"ollama_model\": \"$MODEL\"${NC}"
echo -e "    Or set it via the Control Panel UI."
echo ""
echo -e "  ${BOLD}Useful Commands${NC}"
if [[ "$IS_MAC" == "yes" ]]; then
    echo -e "    ${CYAN}Restart:${NC}  launchctl unload ~/Library/LaunchAgents/com.ollama.serve.plist && launchctl load ~/Library/LaunchAgents/com.ollama.serve.plist"
    echo -e "    ${CYAN}Logs:${NC}     tail -f /tmp/ollama-serve.log"
else
    echo -e "    ${CYAN}Restart:${NC}  sudo systemctl restart ollama"
    echo -e "    ${CYAN}Logs:${NC}     journalctl -u ollama -f"
fi
echo -e "    ${CYAN}Test:${NC}     curl ${OLLAMA_URL}/api/tags"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
