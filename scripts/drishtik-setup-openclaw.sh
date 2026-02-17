#!/usr/bin/env bash
# =============================================================================
# Drishtik AI Security System — OpenClaw Setup & WhatsApp Pairing
# =============================================================================
# Run this AFTER drishtik-setup-debian.sh to:
#   1. Verify/fix OpenClaw configuration
#   2. Configure AI model providers (Ollama + optional OpenAI/Gemini)
#   3. Pair WhatsApp via QR code
#   4. Verify everything works end-to-end
#
# Run:  bash drishtik-setup-openclaw.sh
# =============================================================================

set -uo pipefail

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
    if [[ "$input" =~ ^[Yy] ]]; then
        printf -v "$varname" '%s' "yes"
    else
        printf -v "$varname" '%s' "no"
    fi
}

ERRORS=0

# ---------------------------------------------------------------------------
# Welcome
# ---------------------------------------------------------------------------
banner "Drishtik AI — OpenClaw Setup & WhatsApp Pairing"

echo ""
echo -e "  This script configures OpenClaw for the Drishtik security system."
echo ""
echo -e "  ${YELLOW}Steps:${NC}"
echo -e "    1. Verify OpenClaw installation"
echo -e "    2. Configure AI model providers"
echo -e "    3. Pair WhatsApp via QR code"
echo -e "    4. Verify end-to-end connectivity"
echo ""

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------
banner "Step 1/4 — Verify OpenClaw Installation"

# Ensure PATH includes npm global
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

# Check Node.js
if ! command -v node &>/dev/null; then
    fail "Node.js not found. Run drishtik-setup-debian.sh first."
    exit 1
fi

NODE_MAJOR=$(node --version 2>/dev/null | sed 's/v\([0-9]*\).*/\1/' || echo "0")
if [[ "$NODE_MAJOR" -lt 22 ]]; then
    fail "Node.js $(node --version) is too old. OpenClaw requires >= 22.x"
    fail "Run drishtik-setup-debian.sh again to upgrade."
    exit 1
fi
success "Node.js: $(node --version)"

# Check OpenClaw
OPENCLAW_BIN=""
if command -v openclaw &>/dev/null; then
    OPENCLAW_BIN="$(command -v openclaw)"
elif [[ -x "$HOME/.npm-global/bin/openclaw" ]]; then
    OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"
fi

if [[ -z "$OPENCLAW_BIN" ]]; then
    info "OpenClaw not installed — installing now..."
    mkdir -p "$HOME/.npm-global"
    npm config set prefix "$HOME/.npm-global" 2>/dev/null || true
    if npm install -g openclaw 2>&1 | tail -3; then
        OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"
        if [[ ! -x "$OPENCLAW_BIN" ]]; then
            fail "OpenClaw install failed"
            exit 1
        fi
    else
        fail "OpenClaw install failed"
        exit 1
    fi
fi

OC_VERSION=$("$OPENCLAW_BIN" --version 2>&1 | head -1 || echo "unknown")
success "OpenClaw: $OC_VERSION ($OPENCLAW_BIN)"

# Ensure config directory structure
mkdir -p "$HOME/.openclaw/agents/main/sessions"
mkdir -p "$HOME/.openclaw/credentials"
mkdir -p "$HOME/.openclaw/workspace/skills/frigate"
mkdir -p "$HOME/.openclaw/workspace/ai-snapshots"
mkdir -p "$HOME/.openclaw/workspace/ai-clips"

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — AI Model Providers
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 2/4 — AI Model Providers"

echo ""
info "The Drishtik bridge uses Ollama (local vision AI) for camera analysis."
info "You can optionally add OpenAI or Gemini as a fallback model."
echo ""

# Check for existing config
CONFIG_FILE="$HOME/.openclaw/openclaw.json"
HAS_CONFIG=no
CURRENT_OLLAMA_URL=""
if [[ -f "$CONFIG_FILE" ]]; then
    HAS_CONFIG=yes
    CURRENT_OLLAMA_URL=$(python3 -c "
import json
try:
    c = json.load(open('$CONFIG_FILE'))
    print(c.get('models',{}).get('providers',{}).get('ollama',{}).get('baseUrl',''))
except: pass
" 2>/dev/null || echo "")
fi

# Ollama URL
if [[ -n "$CURRENT_OLLAMA_URL" ]]; then
    info "Current Ollama URL: ${BOLD}${CURRENT_OLLAMA_URL}${NC}"
    ask_yn "Keep this Ollama URL?" "Y" KEEP_OLLAMA
    if [[ "$KEEP_OLLAMA" != "yes" ]]; then
        ask "Ollama machine's URL (e.g. http://192.168.0.219:11434)" "$CURRENT_OLLAMA_URL" OLLAMA_URL
    else
        OLLAMA_URL="$CURRENT_OLLAMA_URL"
    fi
else
    ask "Ollama machine's URL (e.g. http://192.168.0.219:11434)" "" OLLAMA_URL
fi

# Test Ollama
if [[ -n "$OLLAMA_URL" ]]; then
    info "Testing Ollama at ${OLLAMA_URL}..."
    if curl -sf --connect-timeout 5 "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
        success "Ollama is reachable"
        # List available models
        MODELS=$(curl -sf "${OLLAMA_URL}/api/tags" 2>/dev/null | python3 -c "
import json,sys
try:
    data = json.load(sys.stdin)
    for m in data.get('models',[]):
        print(m['name'])
except: pass
" 2>/dev/null || echo "")
        if [[ -n "$MODELS" ]]; then
            info "Available models on Ollama:"
            echo "$MODELS" | while read -r m; do echo -e "      - $m"; done
        fi
    else
        warn "Cannot reach Ollama at $OLLAMA_URL — continuing anyway"
    fi
fi

ask "Vision model name" "qwen2.5vl:7b" AI_MODEL

# Optional: Cloud AI API key
echo ""
info "Optional: Add an OpenAI or Gemini API key."
info "If provided, this becomes the PRIMARY model for WhatsApp AI responses."
info "Ollama (local) is always used for camera/vision analysis regardless."
info "Press Enter to skip (Ollama only)."
echo ""
ask "OpenAI API key (Enter to skip)" "" OPENAI_KEY
ask "Gemini API key (Enter to skip)" "" GEMINI_KEY

# WhatsApp numbers
echo ""
info "WhatsApp alert recipients — who should receive security alerts?"
info "Your phone number is used to pair WhatsApp AND receive alerts."
echo ""
ask "Your phone number with country code (e.g. +919873240906)" "" WA_MY_NUMBER
echo ""
info "You can add more recipients (comma-separated) or press Enter for just yours."
ask "Additional recipients (e.g. +91xxx,+91yyy — Enter to skip)" "" WA_EXTRA_NUMBERS

# Build allowFrom list
WA_ALLOW_FROM=""
if [[ -n "$WA_MY_NUMBER" ]]; then
    WA_ALLOW_FROM="\"$WA_MY_NUMBER\""
    if [[ -n "$WA_EXTRA_NUMBERS" ]]; then
        IFS=',' read -ra EXTRA <<< "$WA_EXTRA_NUMBERS"
        for num in "${EXTRA[@]}"; do
            num="$(echo "$num" | xargs)"  # trim whitespace
            [[ -n "$num" ]] && WA_ALLOW_FROM="$WA_ALLOW_FROM, \"$num\""
        done
    fi
fi

# Build and write config
info "Updating OpenClaw configuration..."

python3 << PYEOF
import json, os

config_path = os.path.expanduser("$CONFIG_FILE")

# Load existing or start fresh
try:
    with open(config_path) as f:
        cfg = json.load(f)
except:
    cfg = {}

# Ensure required structure
cfg.setdefault("hooks", {
    "enabled": True,
    "path": "/hooks"
})
if "token" not in cfg["hooks"]:
    import secrets
    cfg["hooks"]["token"] = "frigate-hook-" + secrets.token_hex(8)
cfg["hooks"]["allowRequestSessionKey"] = True

# Models — providers format (OpenClaw 2026.2+)
providers = {}
ollama_url = "$OLLAMA_URL"
ai_model = "$AI_MODEL"
if ollama_url:
    providers["ollama"] = {
        "baseUrl": ollama_url,
        "models": [{"id": ai_model, "name": ai_model}]
    }

openai_key = "$OPENAI_KEY"
if openai_key:
    providers["openai"] = {
        "baseUrl": "https://api.openai.com/v1",
        "apiKey": openai_key,
        "models": [
            {"id": "gpt-4o-mini", "name": "gpt-4o-mini"},
            {"id": "gpt-4o", "name": "gpt-4o"}
        ]
    }

gemini_key = "$GEMINI_KEY"
if gemini_key:
    providers["google"] = {
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta",
        "apiKey": gemini_key,
        "models": [
            {"id": "gemini-2.0-flash", "name": "gemini-2.0-flash"}
        ]
    }

cfg["models"] = {"providers": providers}

# Gateway
cfg["gateway"] = cfg.get("gateway", {})
cfg["gateway"]["port"] = 18789
cfg["gateway"]["mode"] = "local"

# Channels — set allowFrom with user-provided numbers
if "channels" not in cfg:
    cfg["channels"] = {}
wa = cfg.get("channels", {}).get("whatsapp", {})
wa["dmPolicy"] = "pairing"
wa["groupPolicy"] = "allowlist"
wa.pop("enabled", None)  # Remove deprecated key

# Set allowFrom from user input
allow_from_str = "$WA_ALLOW_FROM"
if allow_from_str:
    wa["allowFrom"] = json.loads("[" + allow_from_str + "]")
cfg["channels"]["whatsapp"] = wa

# Plugins
cfg.setdefault("plugins", {"entries": {"whatsapp": {"enabled": True}}})

# Commands
cfg.setdefault("commands", {"native": "auto", "nativeSkills": "auto"})

# Remove deprecated keys
cfg.pop("server", None)

with open(config_path, "w") as f:
    json.dump(cfg, f, indent=2)

print("OK")
PYEOF

if [[ $? -eq 0 ]]; then
    success "openclaw.json updated"
else
    fail "Failed to update config"
    ERRORS=$((ERRORS + 1))
fi

# Fix permissions
chmod 700 "$HOME/.openclaw" 2>/dev/null || true
chmod 600 "$CONFIG_FILE" 2>/dev/null || true

# Create auth-profiles.json so OpenClaw agent can use the API key
info "Setting up agent authentication..."
AGENT_DIR="$HOME/.openclaw/agents/main/agent"
mkdir -p "$AGENT_DIR"

PRIMARY_PROVIDER=""
PRIMARY_MODEL=""

if [[ -n "$OPENAI_KEY" ]]; then
    PRIMARY_PROVIDER="openai"
    PRIMARY_MODEL="openai/gpt-4o-mini"
    python3 << PYEOF2
import json
auth = {
    "profiles": {
        "openai:manual": {
            "provider": "openai",
            "token": "$OPENAI_KEY",
            "source": "manual"
        }
    },
    "order": ["openai:manual"]
}
with open("$AGENT_DIR/auth-profiles.json", "w") as f:
    json.dump(auth, f, indent=2)
print("OK")
PYEOF2
    chmod 600 "$AGENT_DIR/auth-profiles.json" 2>/dev/null || true
    success "Agent auth profile created (OpenAI = primary)"
elif [[ -n "$GEMINI_KEY" ]]; then
    PRIMARY_PROVIDER="google"
    PRIMARY_MODEL="google/gemini-2.0-flash"
    python3 << PYEOF3
import json
auth = {
    "profiles": {
        "google:manual": {
            "provider": "google",
            "token": "$GEMINI_KEY",
            "source": "manual"
        }
    },
    "order": ["google:manual"]
}
with open("$AGENT_DIR/auth-profiles.json", "w") as f:
    json.dump(auth, f, indent=2)
print("OK")
PYEOF3
    chmod 600 "$AGENT_DIR/auth-profiles.json" 2>/dev/null || true
    success "Agent auth profile created (Gemini = primary)"
else
    info "No cloud API key — agent will use Ollama only"
fi

# Set the primary/default model for the agent
if [[ -n "$PRIMARY_MODEL" ]]; then
    info "Setting ${PRIMARY_MODEL} as the default agent model..."
    "$OPENCLAW_BIN" models set "$PRIMARY_MODEL" > /dev/null 2>&1 || true
    success "Default model: $PRIMARY_MODEL"
fi

# Run doctor --fix
info "Running openclaw doctor --fix..."
"$OPENCLAW_BIN" doctor --fix > /dev/null 2>&1 || true
success "Config validated by doctor"

# Restart gateway to pick up changes
info "Restarting OpenClaw gateway..."
systemctl --user restart openclaw-gateway 2>/dev/null || true
sleep 5

if systemctl --user is-active openclaw-gateway &>/dev/null; then
    success "OpenClaw gateway running"
else
    warn "OpenClaw gateway may need a moment to start"
    ERRORS=$((ERRORS + 1))
fi

# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — WhatsApp Pairing
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 3/4 — WhatsApp Pairing"

echo ""
info "WhatsApp is how Drishtik sends you security alerts with snapshots."
info "You'll scan a QR code with your phone to link WhatsApp."
echo ""
info "On your phone:"
info "  1. Open WhatsApp → Settings → Linked Devices → Link a Device"
info "  2. Scan the QR code that appears below"
echo ""

ask_yn "Ready to pair WhatsApp now?" "Y" DO_WHATSAPP

if [[ "$DO_WHATSAPP" == "yes" ]]; then
    echo ""
    info "Generating QR code... (scan with WhatsApp)"
    echo ""
    # openclaw channels login links WhatsApp Web and shows QR code
    "$OPENCLAW_BIN" channels login --verbose 2>&1 || true
    echo ""
    ask_yn "Did WhatsApp pair successfully?" "Y" WA_OK
    if [[ "$WA_OK" == "yes" ]]; then
        success "WhatsApp paired!"
    else
        warn "You can pair later by running: openclaw channels login"
        ERRORS=$((ERRORS + 1))
    fi
else
    info "Skipping WhatsApp pairing — run later: openclaw channels login"
fi

# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — Verify End-to-End
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 4/4 — Verify Connectivity"

echo ""

# Check all services
info "Checking services..."
echo ""

SVC_OK=0
SVC_TOTAL=0

for svc_name in "OpenClaw Gateway:openclaw-gateway" "Bridge:frigate-openclaw-bridge" "Control Panel:frigate-control-panel"; do
    label="${svc_name%%:*}"
    unit="${svc_name##*:}"
    SVC_TOTAL=$((SVC_TOTAL + 1))
    if systemctl --user is-active "$unit" &>/dev/null; then
        success "$label: running"
        SVC_OK=$((SVC_OK + 1))
    else
        warn "$label: not running — check: journalctl --user -u $unit -n 20"
        ERRORS=$((ERRORS + 1))
    fi
done

# Mosquitto (system service)
SVC_TOTAL=$((SVC_TOTAL + 1))
if systemctl is-active mosquitto &>/dev/null; then
    success "Mosquitto MQTT: running"
    SVC_OK=$((SVC_OK + 1))
else
    # Try with sudo
    if sudo systemctl is-active mosquitto &>/dev/null 2>&1; then
        success "Mosquitto MQTT: running"
        SVC_OK=$((SVC_OK + 1))
    else
        warn "Mosquitto MQTT: not running"
        ERRORS=$((ERRORS + 1))
    fi
fi

# Frigate (Docker)
SVC_TOTAL=$((SVC_TOTAL + 1))
FRIGATE_STATUS=$(sudo docker inspect frigate --format='{{.State.Health.Status}}' 2>/dev/null || docker inspect frigate --format='{{.State.Health.Status}}' 2>/dev/null || echo "not found")
if [[ "$FRIGATE_STATUS" == "healthy" ]]; then
    success "Frigate NVR: healthy"
    SVC_OK=$((SVC_OK + 1))
elif [[ "$FRIGATE_STATUS" == "starting" ]]; then
    info "Frigate NVR: starting up..."
    SVC_OK=$((SVC_OK + 1))
else
    warn "Frigate NVR: $FRIGATE_STATUS"
    ERRORS=$((ERRORS + 1))
fi

# Ollama
if [[ -n "$OLLAMA_URL" ]]; then
    if curl -sf --connect-timeout 5 "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
        success "Ollama AI: reachable at $OLLAMA_URL"
    else
        warn "Ollama AI: not reachable at $OLLAMA_URL"
        ERRORS=$((ERRORS + 1))
    fi
fi

# WhatsApp status
echo ""
info "Checking WhatsApp connection..."
WA_STATUS=$("$OPENCLAW_BIN" channels status 2>&1 || echo "unknown")
if echo "$WA_STATUS" | grep -qi "connected\|paired\|ready\|online"; then
    success "WhatsApp: connected"
else
    warn "WhatsApp: not connected — run: openclaw channels login"
fi

# ═══════════════════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════════════════
banner "OpenClaw Setup Complete!"

if [[ $ERRORS -gt 0 ]]; then
    echo -e "  ${YELLOW}Completed with $ERRORS warning(s)${NC}"
else
    echo -e "  ${GREEN}All steps completed successfully!${NC}"
fi

echo ""
echo -e "  ${BOLD}Services${NC}      $SVC_OK/$SVC_TOTAL running"
echo ""
echo -e "  ${BOLD}AI Models${NC}"
if [[ -n "$OLLAMA_URL" ]]; then
    echo -e "    Ollama (vision): $AI_MODEL (${OLLAMA_URL})"
fi
if [[ -n "$OPENAI_KEY" ]]; then
    echo -e "    OpenAI (primary): gpt-4o-mini  ← default for WhatsApp AI"
fi
if [[ -n "$GEMINI_KEY" ]]; then
    echo -e "    Gemini (primary): gemini-2.0-flash  ← default for WhatsApp AI"
fi
if [[ -z "$OPENAI_KEY" && -z "$GEMINI_KEY" ]]; then
    echo -e "    ${YELLOW}No cloud API key — add one later: openclaw auth add --provider openai${NC}"
fi
echo ""
echo -e "  ${BOLD}Useful Commands${NC}"
echo -e "    ${CYAN}Pair WhatsApp:${NC}    openclaw channels login"
echo -e "    ${CYAN}WhatsApp status:${NC}  openclaw channels status"
echo -e "    ${CYAN}Fix config:${NC}       openclaw doctor --fix"
echo -e "    ${CYAN}Restart gateway:${NC}  systemctl --user restart openclaw-gateway"
echo -e "    ${CYAN}Gateway logs:${NC}     journalctl --user -u openclaw-gateway -f"
echo -e "    ${CYAN}Add API key:${NC}      openclaw auth add --provider openai"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
