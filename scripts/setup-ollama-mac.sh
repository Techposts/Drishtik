#!/usr/bin/env bash
# =============================================================================
# Ollama VLM Setup — Mac (Apple Silicon)
# =============================================================================
# Sets up Ollama with qwen2.5vl:7b on a Mac M-series machine so the
# Frigate bridge on the Debian server can call it over LAN for local
# vision analysis.
#
# Run:  bash setup-ollama-mac.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors & helpers  (matches setup-frigate-ai.sh)
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

ask() {
    local prompt="$1"
    local default="$2"
    local varname="$3"
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
    local prompt="$1"
    local default="$2"
    local varname="$3"
    echo -ne "  ${GREEN}?${NC}  ${prompt} ${YELLOW}[${default}]${NC}: "
    read -r input
    input="${input:-$default}"
    if [[ "$input" =~ ^[Yy] ]]; then
        printf -v "$varname" '%s' "yes"
    else
        printf -v "$varname" '%s' "no"
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
banner "Ollama VLM Setup — Mac (Apple Silicon)"

echo ""
echo -e "  This script sets up Ollama with the ${BOLD}qwen2.5vl:7b${NC} vision model"
echo -e "  on your Mac so the Frigate bridge can call it over LAN for"
echo -e "  local AI-powered security camera analysis."
echo ""
echo -e "  ${YELLOW}What it will do:${NC}"
echo -e "    1. Install Ollama (if not already installed)"
echo -e "    2. Pull the qwen2.5vl:7b vision model (~4.7 GB)"
echo -e "    3. Configure LAN access (so the bridge server can reach it)"
echo -e "    4. Set up auto-start on boot via launchd"
echo -e "    5. Verify the endpoint is working"
echo ""

# ── macOS check ────────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    fail "This script is for macOS only (detected: $(uname))"
    echo -e "       Use the Debian setup scripts on Linux."
    exit 1
fi
success "Running on macOS"

# ── Apple Silicon check ────────────────────────────────────────────────────
ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" ]]; then
    fail "Apple Silicon (arm64) required (detected: $ARCH)"
    echo -e "       qwen2.5vl:7b needs the Metal GPU on M1/M2/M3/M4 chips."
    exit 1
fi
success "Apple Silicon detected ($ARCH)"

# ── RAM check ──────────────────────────────────────────────────────────────
RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
RAM_GB=$(( RAM_BYTES / 1073741824 ))
if [[ $RAM_GB -lt 8 ]]; then
    fail "At least 8 GB RAM required (detected: ${RAM_GB} GB)"
    echo -e "       qwen2.5vl:7b needs ~5 GB VRAM; 8 GB is the minimum."
    exit 1
fi
success "${RAM_GB} GB RAM detected"

# ── curl check ─────────────────────────────────────────────────────────────
if ! command -v curl &>/dev/null; then
    fail "curl not found — install Xcode Command Line Tools:"
    echo -e "       ${YELLOW}xcode-select --install${NC}"
    exit 1
fi

ask_yn "Ready to begin?" "Y" READY
if [[ "$READY" != "yes" ]]; then
    echo "  Setup cancelled."
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 1 — Install Ollama
# ---------------------------------------------------------------------------
banner "Step 1/5 — Install Ollama"

OLLAMA_BIN=""
if command -v ollama &>/dev/null; then
    OLLAMA_BIN="$(command -v ollama)"
    OLLAMA_VER="$(ollama --version 2>/dev/null || echo "unknown")"
    success "Ollama already installed: $OLLAMA_BIN ($OLLAMA_VER)"
else
    info "Ollama not found — installing..."
    echo ""

    if command -v brew &>/dev/null; then
        info "Installing via Homebrew..."
        brew install ollama
        OLLAMA_BIN="$(command -v ollama)"
        success "Ollama installed via Homebrew: $OLLAMA_BIN"
    else
        info "Homebrew not found — downloading Ollama installer..."
        echo -e "       ${YELLOW}This will download and run the official Ollama installer.${NC}"
        echo ""
        curl -fsSL https://ollama.com/install.sh | sh
        OLLAMA_BIN="$(command -v ollama 2>/dev/null || echo "")"
        if [[ -z "$OLLAMA_BIN" ]]; then
            # Check common paths after install
            for p in /usr/local/bin/ollama /opt/homebrew/bin/ollama; do
                if [[ -x "$p" ]]; then
                    OLLAMA_BIN="$p"
                    break
                fi
            done
        fi
        if [[ -z "$OLLAMA_BIN" ]]; then
            fail "Ollama installation failed — install manually from https://ollama.com/download"
            exit 1
        fi
        success "Ollama installed: $OLLAMA_BIN"
    fi
fi

# ---------------------------------------------------------------------------
# Step 2 — Pull qwen2.5vl:7b
# ---------------------------------------------------------------------------
banner "Step 2/5 — Pull Vision Model"

MODEL="qwen2.5vl:7b"

# Make sure ollama server is running for model pull
OLLAMA_WAS_RUNNING=no
if pgrep -f "ollama serve" &>/dev/null; then
    OLLAMA_WAS_RUNNING=yes
    success "Ollama server already running"
else
    info "Starting Ollama server for model pull..."
    "$OLLAMA_BIN" serve &>/dev/null &
    OLLAMA_PID=$!
    sleep 3
    if kill -0 "$OLLAMA_PID" 2>/dev/null; then
        success "Ollama server started (PID $OLLAMA_PID)"
    else
        warn "Could not start Ollama server — model pull may fail"
    fi
fi

# Check if model already exists
if "$OLLAMA_BIN" list 2>/dev/null | grep -q "$MODEL"; then
    success "Model $MODEL already pulled"
else
    info "Pulling $MODEL (~4.7 GB) — this may take a while..."
    echo ""
    "$OLLAMA_BIN" pull "$MODEL"
    echo ""
    if "$OLLAMA_BIN" list 2>/dev/null | grep -q "$MODEL"; then
        success "Model $MODEL pulled successfully"
    else
        fail "Failed to pull $MODEL"
        exit 1
    fi
fi

# Stop the temporary server if we started it (launchd will manage it)
if [[ "$OLLAMA_WAS_RUNNING" == "no" ]] && [[ -n "${OLLAMA_PID:-}" ]]; then
    kill "$OLLAMA_PID" 2>/dev/null || true
    wait "$OLLAMA_PID" 2>/dev/null || true
    info "Stopped temporary Ollama server"
fi

# ---------------------------------------------------------------------------
# Step 3 — Configure LAN binding
# ---------------------------------------------------------------------------
banner "Step 3/5 — Configure LAN Access"

info "The Frigate bridge on your Debian server needs to reach Ollama over LAN."
info "Ollama defaults to 127.0.0.1 (localhost only). We'll bind it to 0.0.0.0"
info "so any machine on your network can connect on port 11434."
echo ""

# Detect LAN IP
LAN_IP=""
for iface in en0 en1; do
    ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
    if [[ -n "$ip" ]]; then
        LAN_IP="$ip"
        break
    fi
done

ask "This Mac's LAN IP" "$LAN_IP" LAN_IP

OLLAMA_PORT="11434"
ask "Ollama port" "$OLLAMA_PORT" OLLAMA_PORT

OLLAMA_HOST="0.0.0.0:${OLLAMA_PORT}"
OLLAMA_URL="http://${LAN_IP}:${OLLAMA_PORT}"

success "Ollama will listen on $OLLAMA_HOST (reachable at $OLLAMA_URL)"

# ---------------------------------------------------------------------------
# Step 4 — launchd auto-start service
# ---------------------------------------------------------------------------
banner "Step 4/5 — Auto-Start Service (launchd)"

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.ollama.serve.plist"
PLIST_LABEL="com.ollama.serve"

info "Creating launchd plist for Ollama server with LAN binding."
echo ""

# Stop Ollama.app login item if running (it binds to localhost only)
if launchctl list 2>/dev/null | grep -qi ollama; then
    warn "Existing Ollama launch agent detected — will be replaced"
fi

# Kill any running ollama serve processes
if pgrep -f "ollama serve" &>/dev/null; then
    info "Stopping existing Ollama server..."
    pkill -f "ollama serve" 2>/dev/null || true
    sleep 2
fi

# Unload existing plist if present
if [[ -f "$PLIST_FILE" ]]; then
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
fi

mkdir -p "$PLIST_DIR"

# Resolve ollama binary to absolute path
OLLAMA_ABS="$(command -v ollama)"
if [[ -z "$OLLAMA_ABS" ]]; then
    OLLAMA_ABS="/usr/local/bin/ollama"
fi

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

success "Created $PLIST_FILE"

# Load and start
launchctl load "$PLIST_FILE"
sleep 3

if pgrep -f "ollama serve" &>/dev/null; then
    success "Ollama server started via launchd"
else
    warn "Ollama server may not have started — check /tmp/ollama-serve.log"
fi

# ---------------------------------------------------------------------------
# Step 5 — Verify endpoint
# ---------------------------------------------------------------------------
banner "Step 5/5 — Verify Endpoint"

ERRORS=0

# ── /api/tags — model list ────────────────────────────────────────────────
info "Testing /api/tags endpoint..."
TAGS_RESP=$(curl -sf "http://127.0.0.1:${OLLAMA_PORT}/api/tags" 2>/dev/null || echo "")
if [[ -n "$TAGS_RESP" ]] && echo "$TAGS_RESP" | grep -q "$MODEL"; then
    success "/api/tags — $MODEL found"
else
    if [[ -z "$TAGS_RESP" ]]; then
        fail "/api/tags — Ollama not responding on port $OLLAMA_PORT"
    else
        fail "/api/tags — $MODEL not found in model list"
    fi
    ((ERRORS++)) || true
fi

# ── /api/generate — quick health check ────────────────────────────────────
info "Testing /api/generate health check (text-only, quick)..."
HEALTH_RESP=$(curl -sf "http://127.0.0.1:${OLLAMA_PORT}/api/generate" \
    -d "{\"model\":\"$MODEL\",\"prompt\":\"Say OK\",\"stream\":false,\"options\":{\"num_predict\":5}}" \
    2>/dev/null || echo "")
if [[ -n "$HEALTH_RESP" ]] && echo "$HEALTH_RESP" | grep -q '"response"'; then
    success "/api/generate — model responded"
else
    if [[ -z "$HEALTH_RESP" ]]; then
        fail "/api/generate — no response (model may still be loading)"
    else
        fail "/api/generate — unexpected response"
    fi
    warn "This is OK if the model is still loading for the first time."
    warn "Retry in a minute:  curl http://127.0.0.1:${OLLAMA_PORT}/api/tags"
    ((ERRORS++)) || true
fi

# ── LAN reachability ──────────────────────────────────────────────────────
info "Testing LAN reachability at $OLLAMA_URL..."
LAN_RESP=$(curl -sf "${OLLAMA_URL}/api/tags" --connect-timeout 5 2>/dev/null || echo "")
if [[ -n "$LAN_RESP" ]] && echo "$LAN_RESP" | grep -q "models"; then
    success "LAN endpoint reachable at $OLLAMA_URL"
else
    warn "Could not reach $OLLAMA_URL — check firewall settings"
    echo -e "       ${YELLOW}macOS firewall: System Settings > Network > Firewall${NC}"
    ((ERRORS++)) || true
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
banner "Setup Complete!"

if [[ $ERRORS -gt 0 ]]; then
    echo -e "  ${YELLOW}Completed with $ERRORS warning(s) — review messages above${NC}"
else
    echo -e "  ${GREEN}All steps completed successfully!${NC}"
fi

echo ""
echo -e "  ${BOLD}Ollama Configuration${NC}"
echo -e "    Binary:     $OLLAMA_ABS"
echo -e "    Model:      $MODEL"
echo -e "    Listen:     $OLLAMA_HOST"
echo -e "    LAN URL:    ${BOLD}$OLLAMA_URL${NC}"
echo -e "    Plist:      $PLIST_FILE"
echo -e "    Logs:       /tmp/ollama-serve.log"
echo ""
echo -e "  ${BOLD}Bridge Configuration${NC}"
echo -e "    Set the following in your ${YELLOW}bridge-runtime-config.json${NC}:"
echo ""
echo -e "      ${CYAN}\"ollama_api\": \"$OLLAMA_URL\"${NC}"
echo -e "      ${CYAN}\"ollama_model\": \"$MODEL\"${NC}"
echo ""
echo -e "  ${BOLD}Useful Commands${NC}"
echo ""
echo -e "    ${CYAN}Check Ollama status:${NC}"
echo -e "      curl $OLLAMA_URL/api/tags"
echo ""
echo -e "    ${CYAN}View server logs:${NC}"
echo -e "      tail -f /tmp/ollama-serve.log"
echo ""
echo -e "    ${CYAN}Restart Ollama:${NC}"
echo -e "      launchctl unload $PLIST_FILE && launchctl load $PLIST_FILE"
echo ""
echo -e "    ${CYAN}Stop Ollama:${NC}"
echo -e "      launchctl unload $PLIST_FILE"
echo ""
echo -e "    ${CYAN}Pull a different model:${NC}"
echo -e "      ollama pull <model-name>"
echo ""
echo -e "    ${CYAN}Test vision analysis:${NC}"
echo -e "      curl $OLLAMA_URL/api/generate \\"
echo -e "        -d '{\"model\":\"$MODEL\",\"prompt\":\"describe this image\",\"images\":[\"<base64>\"],\"stream\":false}'"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
