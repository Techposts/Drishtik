#!/usr/bin/env bash
#
# OpenClaw Interactive Installer
# Installs and configures OpenClaw on Debian/Ubuntu/Raspberry Pi OS systems.
# Supports: headless servers, desktop environments, x86_64, ARM (Raspberry Pi).
# Handles: Node.js, Chromium, OpenClaw, LLM API keys, web search,
#           messaging channels, browser config, gateway, and systemd daemon.
#
# Usage:  bash install-openclaw.sh
#         curl -fsSL https://your-url/install-openclaw.sh | bash
#
# Tested on:
#   - Debian 12 (Bookworm) x86_64 headless
#   - Debian 12 (Bookworm) x86_64 desktop
#   - Raspberry Pi OS (Bookworm) ARM64 headless
#   - Raspberry Pi OS (Bookworm) ARM64 desktop
#   - Ubuntu 22.04 / 24.04
#

set -euo pipefail

# ── Colors & helpers ──────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { printf "${CYAN}[INFO]${NC}  %s\n" "$*"; }
ok()    { printf "${GREEN}[OK]${NC}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$*"; }
err()   { printf "${RED}[ERROR]${NC} %s\n" "$*"; }
step()  { printf "\n${BOLD}── %s ──${NC}\n" "$*"; }

ask() {
    local prompt="$1" default="${2:-}"
    if [[ -n "$default" ]]; then
        printf "${BOLD}%s${NC} [%s]: " "$prompt" "$default"
    else
        printf "${BOLD}%s${NC}: " "$prompt"
    fi
    read -r REPLY
    REPLY="${REPLY:-$default}"
}

ask_yn() {
    local prompt="$1" default="${2:-y}"
    while true; do
        printf "${BOLD}%s${NC} [%s]: " "$prompt" "$default"
        read -r yn
        yn="${yn:-$default}"
        case "$yn" in
            [Yy]*) return 0 ;;
            [Nn]*) return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

ask_choice() {
    local prompt="$1"
    shift
    local options=("$@")
    echo ""
    printf "${BOLD}%s${NC}\n" "$prompt"
    for i in "${!options[@]}"; do
        printf "  ${CYAN}%d)${NC} %s\n" "$((i+1))" "${options[$i]}"
    done
    while true; do
        printf "${BOLD}Choice [1-%d]:${NC} " "${#options[@]}"
        read -r choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
            REPLY="${options[$((choice-1))]}"
            REPLY_INDEX=$((choice-1))
            return 0
        fi
        echo "Invalid choice. Try again."
    done
}

# Port check that works with ss or netstat
check_port() {
    local port="$1"
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":${port} "
    elif command -v netstat &>/dev/null; then
        netstat -tlnp 2>/dev/null | grep -q ":${port} "
    else
        # Last resort: try connecting
        (echo >/dev/tcp/127.0.0.1/"$port") 2>/dev/null
    fi
}

# Generate random hex token without requiring openssl
gen_token() {
    if command -v openssl &>/dev/null; then
        openssl rand -hex 24
    elif [[ -r /dev/urandom ]]; then
        head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 48
    else
        # Fallback: date-based (less secure but functional)
        echo "$(date +%s%N)$(shuf -i 100000-999999 -n 1)" | sha256sum | head -c 48
    fi
}

# Get LAN IP (handles 192.168.*, 10.*, 172.16-31.*)
get_lan_ip() {
    local ip=""
    if command -v ip &>/dev/null; then
        ip=$(ip -4 addr show 2>/dev/null \
            | grep -oP '(?<=inet\s)\d+\.\d+\.\d+\.\d+' \
            | grep -v '^127\.' \
            | grep -v '^172\.1[7-9]\.' \
            | grep -v '^172\.2[0-9]\.' \
            | grep -v '^172\.3[0-1]\.' \
            | grep -E '^(192\.168\.|10\.|172\.1[6-9]\.|172\.2[0-9]\.|172\.3[0-1]\.)' \
            | head -1)
    fi
    if [[ -z "$ip" ]] && command -v hostname &>/dev/null; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    echo "${ip:-localhost}"
}

# Build JSON object for plugins without python3
build_plugins_json() {
    local result="{"
    local first=true
    for ch in "$@"; do
        if [[ "$first" == "true" ]]; then
            first=false
        else
            result+=","
        fi
        result+="\"$ch\":{\"enabled\":true}"
    done
    result+="}"
    echo "$result"
}

# ── Banner ────────────────────────────────────────────────────────────────────

clear 2>/dev/null || true
cat << 'BANNER'

  ___                    ____ _
 / _ \ _ __   ___ _ __  / ___| | __ ___      __
| | | | '_ \ / _ \ '_ \| |   | |/ _` \ \ /\ / /
| |_| | |_) |  __/ | | | |___| | (_| |\ V  V /
 \___/| .__/ \___|_| |_|\____|_|\__,_| \_/\_/
      |_|
          Interactive Installer

BANNER
echo "This script will install and configure OpenClaw on your system."
echo "It will ask you questions to customize the setup."
echo ""

# ── Pre-flight: detect system ────────────────────────────────────────────────

step "Checking system"

DISTRO="unknown"
DISTRO_ID="unknown"
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    DISTRO="$PRETTY_NAME"
    DISTRO_ID="${ID:-unknown}"
    info "OS: $DISTRO"
else
    warn "Could not detect OS. Assuming Debian-based."
fi

ARCH=$(uname -m)
info "Architecture: $ARCH"

IS_ARM=false
case "$ARCH" in
    aarch64|arm64|armv7l|armv6l|armhf)
        IS_ARM=true
        ;;
esac

IS_RASPBERRY_PI=false
if [[ "$IS_ARM" == "true" ]]; then
    if [[ -f /proc/device-tree/model ]] && grep -qi "raspberry" /proc/device-tree/model 2>/dev/null; then
        IS_RASPBERRY_PI=true
        RPI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "unknown")
        info "Device: $RPI_MODEL"
    elif [[ "$DISTRO_ID" == "raspbian" ]] || echo "$DISTRO" | grep -qi "raspberry"; then
        IS_RASPBERRY_PI=true
        info "Device: Raspberry Pi (detected from OS)"
    fi
fi

if [[ "$IS_ARM" == "true" ]]; then
    info "Platform: ARM ($ARCH)"
fi

IS_HEADLESS=false
if [[ -z "${DISPLAY:-}" ]] && [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
    IS_HEADLESS=true
    info "Environment: headless (no display server)"
else
    info "Environment: desktop (display detected)"
fi

# Memory check (relevant for Pi and low-memory VPS)
TOTAL_MEM_MB=0
if [[ -f /proc/meminfo ]]; then
    TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    TOTAL_MEM_MB=$((TOTAL_MEM_KB / 1024))
    info "Memory: ${TOTAL_MEM_MB} MB"
    if (( TOTAL_MEM_MB < 1024 )); then
        warn "Low memory detected (${TOTAL_MEM_MB} MB). OpenClaw may run slowly."
        warn "Consider adding swap: sudo fallocate -l 2G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
    fi
fi

# Tune concurrency based on available memory
MAX_CONCURRENT=4
SUBAGENT_MAX=8
if (( TOTAL_MEM_MB > 0 && TOTAL_MEM_MB < 2048 )); then
    MAX_CONCURRENT=2
    SUBAGENT_MAX=4
    info "Tuned concurrency for low memory: maxConcurrent=$MAX_CONCURRENT"
elif (( TOTAL_MEM_MB >= 8192 )); then
    MAX_CONCURRENT=8
    SUBAGENT_MAX=16
fi

# Check for required tools
for tool in curl; do
    if ! command -v "$tool" &>/dev/null; then
        err "'$tool' is required but not installed."
        if command -v apt-get &>/dev/null; then
            info "Installing $tool..."
            sudo apt-get update && sudo apt-get install -y "$tool"
        else
            err "Install '$tool' and re-run this script."
            exit 1
        fi
    fi
done

# ── Step 1: Node.js ──────────────────────────────────────────────────────────

step "Step 1: Node.js"

NEED_NODE=false
if command -v node &>/dev/null; then
    NODE_VER=$(node --version)
    NODE_MAJOR="${NODE_VER%%.*}"
    NODE_MAJOR="${NODE_MAJOR#v}"
    ok "Node.js $NODE_VER found"
    if (( NODE_MAJOR < 20 )); then
        warn "Node.js 20+ is recommended. You have $NODE_VER."
        if ask_yn "Install/upgrade Node.js 22 LTS?" "y"; then
            NEED_NODE=true
        fi
    fi
else
    warn "Node.js not found."
    NEED_NODE=true
fi

if [[ "$NEED_NODE" == "true" ]]; then
    info "Installing Node.js 22 LTS ($ARCH)..."
    if command -v apt-get &>/dev/null; then
        # NodeSource supports ARM (aarch64, armv7l)
        curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
        sudo apt-get install -y nodejs
    elif command -v dnf &>/dev/null; then
        curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
        sudo dnf install -y nodejs
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm nodejs npm
    elif command -v apk &>/dev/null; then
        sudo apk add nodejs npm
    else
        err "Unsupported package manager. Install Node.js 22+ manually:"
        err "  https://nodejs.org/en/download/"
        exit 1
    fi
    ok "Node.js $(node --version) installed"
fi

# Ensure npm is available
if ! command -v npm &>/dev/null; then
    err "npm not found. Install it alongside Node.js."
    exit 1
fi

# ── Step 2: Chromium browser ─────────────────────────────────────────────────

step "Step 2: Chromium browser"

CHROMIUM_PATH=""
# Raspberry Pi OS uses 'chromium-browser', Debian uses 'chromium'
for candidate in chromium chromium-browser google-chrome-stable google-chrome; do
    if command -v "$candidate" &>/dev/null; then
        CHROMIUM_PATH=$(command -v "$candidate")
        break
    fi
done

if [[ -n "$CHROMIUM_PATH" ]]; then
    ok "Browser found: $CHROMIUM_PATH"
else
    warn "No Chromium/Chrome browser found."
    if ask_yn "Install Chromium? (needed for browser tool)" "y"; then
        if command -v apt-get &>/dev/null; then
            sudo apt-get update
            # Try 'chromium-browser' first (Raspberry Pi OS), then 'chromium' (Debian)
            if apt-cache show chromium-browser &>/dev/null 2>&1; then
                sudo apt-get install -y chromium-browser
            else
                sudo apt-get install -y chromium
            fi
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y chromium
        elif command -v pacman &>/dev/null; then
            sudo pacman -Sy --noconfirm chromium
        else
            err "Install chromium manually and re-run."
            exit 1
        fi
        CHROMIUM_PATH=$(command -v chromium 2>/dev/null || command -v chromium-browser 2>/dev/null || echo "")
        if [[ -n "$CHROMIUM_PATH" ]]; then
            ok "Chromium installed: $CHROMIUM_PATH"
        else
            warn "Chromium install may have failed. Browser tool will not work."
        fi
    else
        warn "Skipping browser install. Browser tool will not work."
    fi
fi

# ── Step 3: Install OpenClaw ─────────────────────────────────────────────────

step "Step 3: OpenClaw"

NPM_GLOBAL="$HOME/.npm-global"
export PATH="$NPM_GLOBAL/bin:$PATH"

if command -v openclaw &>/dev/null; then
    CURRENT_VER=$(openclaw --version 2>/dev/null || echo "unknown")
    ok "OpenClaw $CURRENT_VER already installed"
    if ask_yn "Update to latest version?" "n"; then
        info "Updating OpenClaw..."
        npm install -g openclaw@latest
        ok "Updated to $(openclaw --version)"
    fi
else
    info "Installing OpenClaw (this may take a moment on ARM)..."
    mkdir -p "$NPM_GLOBAL"
    npm config set prefix "$NPM_GLOBAL"
    npm install -g openclaw@latest
    ok "OpenClaw $(openclaw --version) installed"
fi

# Ensure PATH is in shell rc
SHELL_RC="$HOME/.bashrc"
[[ -f "$HOME/.zshrc" ]] && [[ "${SHELL:-}" == *zsh* ]] && SHELL_RC="$HOME/.zshrc"

if ! grep -q '.npm-global/bin' "$SHELL_RC" 2>/dev/null; then
    echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$SHELL_RC"
    ok "Added npm-global to PATH in $SHELL_RC"
fi

# ── Step 4: LLM Provider & API Key ──────────────────────────────────────────

step "Step 4: LLM model configuration"

ask_choice "Select your LLM provider:" \
    "Anthropic (Claude) — recommended" \
    "OpenRouter (multi-model gateway)" \
    "OpenAI" \
    "GitHub Copilot" \
    "Skip for now"

PROVIDER_CHOICE=$REPLY_INDEX

case $PROVIDER_CHOICE in
    0) # Anthropic
        PROVIDER="anthropic"
        echo ""
        info "Get your API key from: https://console.anthropic.com/settings/keys"
        echo ""
        ask "Paste your Anthropic API key (sk-ant-...)" ""
        API_KEY="$REPLY"
        if [[ -n "$API_KEY" ]]; then
            openclaw models auth paste-token --provider anthropic <<< "$API_KEY" 2>/dev/null || {
                mkdir -p "$HOME/.openclaw"
                cat > "$HOME/.openclaw/auth-profiles.json" << AUTHEOF
{
  "version": 1,
  "profiles": {
    "anthropic:manual": {
      "type": "token",
      "provider": "anthropic",
      "token": "$API_KEY"
    }
  }
}
AUTHEOF
                chmod 600 "$HOME/.openclaw/auth-profiles.json"
            }
            ok "Anthropic API key saved"
        else
            warn "No API key provided. Set it later: openclaw models auth paste-token --provider anthropic"
        fi

        ask_choice "Select default model:" \
            "claude-3-5-haiku-latest — fast & cheap (~\$0.80/1M input)" \
            "claude-sonnet-4 — balanced quality & cost" \
            "claude-opus-4-5 — most capable (expensive)"
        case $REPLY_INDEX in
            0) MODEL="anthropic/claude-3-5-haiku-latest" ;;
            1) MODEL="anthropic/claude-sonnet-4-20250514" ;;
            2) MODEL="anthropic/claude-opus-4-5" ;;
        esac
        ;;
    1) # OpenRouter
        PROVIDER="openrouter"
        echo ""
        info "Get your API key from: https://openrouter.ai/keys"
        echo ""
        ask "Paste your OpenRouter API key" ""
        API_KEY="$REPLY"
        if [[ -n "$API_KEY" ]]; then
            mkdir -p "$HOME/.openclaw"
            cat > "$HOME/.openclaw/auth-profiles.json" << AUTHEOF
{
  "version": 1,
  "profiles": {
    "openrouter:manual": {
      "type": "token",
      "provider": "openrouter",
      "token": "$API_KEY"
    }
  }
}
AUTHEOF
            chmod 600 "$HOME/.openclaw/auth-profiles.json"
            ok "OpenRouter API key saved"
        fi
        ask "Enter model identifier" "anthropic/claude-3-5-haiku-latest"
        MODEL="$REPLY"
        ;;
    2) # OpenAI
        PROVIDER="openai"
        echo ""
        info "Get your API key from: https://platform.openai.com/api-keys"
        echo ""
        ask "Paste your OpenAI API key (sk-...)" ""
        API_KEY="$REPLY"
        if [[ -n "$API_KEY" ]]; then
            mkdir -p "$HOME/.openclaw"
            cat > "$HOME/.openclaw/auth-profiles.json" << AUTHEOF
{
  "version": 1,
  "profiles": {
    "openai:manual": {
      "type": "token",
      "provider": "openai",
      "token": "$API_KEY"
    }
  }
}
AUTHEOF
            chmod 600 "$HOME/.openclaw/auth-profiles.json"
            ok "OpenAI API key saved"
        fi
        ask "Enter model identifier" "openai/gpt-4o"
        MODEL="$REPLY"
        ;;
    3) # GitHub Copilot
        PROVIDER="github-copilot"
        info "GitHub Copilot requires interactive login."
        info "Run after install: openclaw models auth login-github-copilot"
        MODEL="anthropic/claude-3-5-haiku-latest"
        ;;
    4) # Skip
        PROVIDER=""
        MODEL="anthropic/claude-3-5-haiku-latest"
        warn "Skipping LLM setup. Configure later: openclaw models auth add"
        ;;
esac

info "Default model: $MODEL"

# ── Step 5: Gateway configuration ────────────────────────────────────────────

step "Step 5: Gateway configuration"

ask "Gateway port" "18789"
GW_PORT="$REPLY"

ask_choice "Gateway bind mode:" \
    "loopback — localhost only (most secure)" \
    "lan — accessible on local network (recommended for remote access)" \
    "auto — let OpenClaw decide"
case $REPLY_INDEX in
    0) GW_BIND="loopback" ;;
    1) GW_BIND="lan" ;;
    2) GW_BIND="auto" ;;
esac

GW_TOKEN=$(gen_token)

info "Gateway will run on port $GW_PORT (bind: $GW_BIND)"

# ── Step 6: Web search ───────────────────────────────────────────────────────

step "Step 6: Web search"

echo "Web search lets your agent search the internet for real-time information."
echo ""

SEARCH_PROVIDER="brave"
SEARCH_API_KEY=""

ask_choice "Web search provider:" \
    "Brave Search — free tier: 2,000 queries/month (recommended)" \
    "Perplexity Sonar — AI-synthesized answers (paid)" \
    "Skip web search"

case $REPLY_INDEX in
    0)
        SEARCH_PROVIDER="brave"
        echo ""
        info "Get a free API key at: https://brave.com/search/api/"
        echo "  1. Sign up (free)"
        echo "  2. Go to dashboard > API Keys > create key"
        echo ""
        ask "Paste your Brave Search API key (or leave blank to set later)" ""
        SEARCH_API_KEY="$REPLY"
        if [[ -n "$SEARCH_API_KEY" ]]; then
            ok "Brave Search API key saved"
        else
            warn "No key yet. Add it later by editing ~/.openclaw/openclaw.json"
            warn "  Set tools.web.search.apiKey to your key, then restart gateway."
        fi
        ;;
    1)
        SEARCH_PROVIDER="perplexity"
        echo ""
        info "Perplexity can use a direct API key (pplx-...) or OpenRouter key (sk-or-...)"
        echo ""
        ask "Paste your Perplexity or OpenRouter API key" ""
        SEARCH_API_KEY="$REPLY"
        if [[ -n "$SEARCH_API_KEY" ]]; then
            ok "Perplexity API key saved"
        else
            warn "No key yet. Add it later in ~/.openclaw/openclaw.json"
        fi
        ;;
    2)
        SEARCH_PROVIDER=""
        info "Skipped. Enable later: edit tools.web.search in ~/.openclaw/openclaw.json"
        ;;
esac

# ── Step 7: Messaging channels ──────────────────────────────────────────────

step "Step 7: Messaging channels"

echo "OpenClaw can connect to messaging platforms so you can chat with your"
echo "AI assistant from your phone or other devices."
echo ""

CHANNELS_TO_SETUP=()

ask_choice "Which channels do you want to set up?" \
    "WhatsApp — QR code pairing (most popular)" \
    "Telegram — bot token" \
    "Discord — bot token" \
    "Slack — bot + app tokens" \
    "Multiple channels (select next)" \
    "None — skip channel setup"

case $REPLY_INDEX in
    0) CHANNELS_TO_SETUP=("whatsapp") ;;
    1) CHANNELS_TO_SETUP=("telegram") ;;
    2) CHANNELS_TO_SETUP=("discord") ;;
    3) CHANNELS_TO_SETUP=("slack") ;;
    4)
        echo ""
        info "Select channels to set up (answer y/n for each):"
        ask_yn "  WhatsApp?" "n" && CHANNELS_TO_SETUP+=("whatsapp")
        ask_yn "  Telegram?" "n" && CHANNELS_TO_SETUP+=("telegram")
        ask_yn "  Discord?" "n"  && CHANNELS_TO_SETUP+=("discord")
        ask_yn "  Slack?" "n"    && CHANNELS_TO_SETUP+=("slack")
        ask_yn "  Signal?" "n"   && CHANNELS_TO_SETUP+=("signal")
        ask_yn "  Matrix?" "n"   && CHANNELS_TO_SETUP+=("matrix")
        ;;
    5) CHANNELS_TO_SETUP=() ;;
esac

# ── Step 8: Write openclaw.json ──────────────────────────────────────────────

step "Step 8: Writing configuration"

mkdir -p "$HOME/.openclaw"
CONF="$HOME/.openclaw/openclaw.json"

# Back up existing config
if [[ -f "$CONF" ]]; then
    cp "$CONF" "$CONF.bak.$(date +%s)"
    info "Backed up existing config"
fi

# Build plugins JSON (no python3 dependency)
PLUGINS_JSON=$(build_plugins_json "${CHANNELS_TO_SETUP[@]}")

# Browser config: adapt for headless vs desktop
BROWSER_JSON='{}'
if [[ -n "$CHROMIUM_PATH" ]]; then
    if [[ "$IS_HEADLESS" == "true" ]]; then
        # Headless server: use headless Chromium with openclaw profile
        BROWSER_JSON=$(cat << BJEOF
{
    "headless": true,
    "noSandbox": true,
    "executablePath": "$CHROMIUM_PATH",
    "defaultProfile": "openclaw"
  }
BJEOF
)
    else
        # Desktop: non-headless, can use Chrome extension relay too
        BROWSER_JSON=$(cat << BJEOF
{
    "headless": false,
    "noSandbox": false,
    "executablePath": "$CHROMIUM_PATH"
  }
BJEOF
)
    fi
fi

# Web search config
SEARCH_ENABLED="false"
[[ -n "$SEARCH_PROVIDER" ]] && SEARCH_ENABLED="true"

cat > "$CONF" << CONFEOF
{
  "meta": {
    "lastTouchedVersion": "installer",
    "lastTouchedAt": "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)",
    "platform": "$ARCH",
    "os": "$DISTRO_ID",
    "headless": $IS_HEADLESS,
    "raspberryPi": $IS_RASPBERRY_PI
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "$MODEL"
      },
      "workspace": "$HOME/.openclaw/workspace",
      "compaction": {
        "mode": "safeguard"
      },
      "maxConcurrent": $MAX_CONCURRENT,
      "subagents": {
        "maxConcurrent": $SUBAGENT_MAX
      }
    }
  },
  "commands": {
    "native": "auto",
    "nativeSkills": "auto"
  },
  "gateway": {
    "port": $GW_PORT,
    "mode": "local",
    "bind": "$GW_BIND",
    "auth": {
      "mode": "token",
      "token": "$GW_TOKEN"
    },
    "tailscale": {
      "mode": "off",
      "resetOnExit": false
    }
  },
  "tools": {
    "sandbox": {
      "tools": {
        "allow": ["exec", "process", "read", "write", "edit", "apply_patch", "image", "browser", "canvas", "sessions_list", "sessions_history", "sessions_send", "sessions_spawn", "session_status"],
        "deny": []
      }
    },
    "elevated": {
      "enabled": true
    },
    "web": {
      "search": {
        "enabled": $SEARCH_ENABLED,
        "provider": "${SEARCH_PROVIDER:-brave}",
        "apiKey": "$SEARCH_API_KEY",
        "maxResults": 5
      }
    }
  },
  "skills": {
    "install": {
      "nodeManager": "npm"
    }
  },
  "browser": $BROWSER_JSON,
  "plugins": {
    "entries": $PLUGINS_JSON
  }
}
CONFEOF

chmod 600 "$CONF"
ok "Config written to $CONF"

# ── Step 9: Channel setup ────────────────────────────────────────────────────

if (( ${#CHANNELS_TO_SETUP[@]} > 0 )); then
    step "Step 9: Channel setup"

    for channel in "${CHANNELS_TO_SETUP[@]}"; do
        echo ""
        case "$channel" in
            whatsapp)
                info "WhatsApp setup"
                echo "  WhatsApp uses QR code pairing. After the gateway starts,"
                echo "  run: openclaw channels login --channel whatsapp --verbose"
                echo "  Then scan the QR code with your phone (WhatsApp > Linked Devices)."
                echo ""
                if ask_yn "  Set up WhatsApp now? (gateway must be running)" "n"; then
                    if ! check_port "$GW_PORT"; then
                        info "Starting gateway for WhatsApp pairing..."
                        nohup openclaw gateway --port "$GW_PORT" --bind "$GW_BIND" > /tmp/openclaw-gw-setup.log 2>&1 &
                        sleep 5
                    fi
                    openclaw channels login --channel whatsapp --verbose 2>&1 || {
                        warn "WhatsApp login failed. Try later: openclaw channels login --channel whatsapp --verbose"
                    }
                else
                    info "Set up later: openclaw channels login --channel whatsapp --verbose"
                fi
                ;;
            telegram)
                info "Telegram setup"
                echo "  1. Message @BotFather on Telegram"
                echo "  2. Send /newbot and follow prompts"
                echo "  3. Copy the bot token"
                echo ""
                ask "Paste your Telegram bot token" ""
                if [[ -n "$REPLY" ]]; then
                    openclaw channels add --channel telegram --token "$REPLY" 2>/dev/null && \
                        ok "Telegram configured" || \
                        warn "Failed. Try: openclaw channels add --channel telegram --token YOUR_TOKEN"
                else
                    warn "Skipped. Set up later: openclaw channels add --channel telegram --token YOUR_TOKEN"
                fi
                ;;
            discord)
                info "Discord setup"
                echo "  1. Go to https://discord.com/developers/applications"
                echo "  2. Create a new application > Bot > copy token"
                echo "  3. Enable Message Content Intent under Bot settings"
                echo "  4. Invite bot to your server with messages permissions"
                echo ""
                ask "Paste your Discord bot token" ""
                if [[ -n "$REPLY" ]]; then
                    openclaw channels add --channel discord --token "$REPLY" 2>/dev/null && \
                        ok "Discord configured" || \
                        warn "Failed. Try: openclaw channels add --channel discord --token YOUR_TOKEN"
                else
                    warn "Skipped. Set up later: openclaw channels add --channel discord --token YOUR_TOKEN"
                fi
                ;;
            slack)
                info "Slack setup"
                echo "  1. Create a Slack app at https://api.slack.com/apps"
                echo "  2. Enable Socket Mode and get an App-Level Token (xapp-...)"
                echo "  3. Install to workspace and get Bot Token (xoxb-...)"
                echo ""
                ask "Paste your Slack bot token (xoxb-...)" ""
                SLACK_BOT="$REPLY"
                ask "Paste your Slack app token (xapp-...)" ""
                SLACK_APP="$REPLY"
                if [[ -n "$SLACK_BOT" && -n "$SLACK_APP" ]]; then
                    openclaw channels add --channel slack --bot-token "$SLACK_BOT" --app-token "$SLACK_APP" 2>/dev/null && \
                        ok "Slack configured" || \
                        warn "Failed. Try manually: openclaw channels add --channel slack --bot-token xoxb-... --app-token xapp-..."
                else
                    warn "Skipped. Set up later with both tokens."
                fi
                ;;
            signal)
                info "Signal setup"
                echo "  Signal requires signal-cli to be installed separately."
                echo "  See: https://github.com/AsamK/signal-cli"
                echo ""
                ask "Signal phone number (E.164 format, e.g. +1234567890)" ""
                if [[ -n "$REPLY" ]]; then
                    openclaw channels add --channel signal --signal-number "$REPLY" 2>/dev/null && \
                        ok "Signal configured" || \
                        warn "Failed. Install signal-cli first."
                else
                    warn "Skipped."
                fi
                ;;
            matrix)
                info "Matrix setup"
                echo ""
                ask "Matrix homeserver URL (e.g. https://matrix.org)" ""
                MATRIX_HS="$REPLY"
                ask "Matrix user ID (e.g. @bot:matrix.org)" ""
                MATRIX_USER="$REPLY"
                ask "Matrix access token or password" ""
                MATRIX_AUTH="$REPLY"
                if [[ -n "$MATRIX_HS" && -n "$MATRIX_USER" && -n "$MATRIX_AUTH" ]]; then
                    openclaw channels add --channel matrix \
                        --homeserver "$MATRIX_HS" \
                        --user-id "$MATRIX_USER" \
                        --access-token "$MATRIX_AUTH" 2>/dev/null && \
                        ok "Matrix configured" || \
                        warn "Failed. Try manually."
                else
                    warn "Skipped."
                fi
                ;;
        esac
    done
fi

# ── Step 10: Start gateway ───────────────────────────────────────────────────

step "Step 10: Starting gateway"

# Stop any existing gateway
if check_port "$GW_PORT"; then
    info "Stopping existing gateway on port $GW_PORT..."
    openclaw gateway stop 2>/dev/null || true
    sleep 2
    # Force kill if still running
    if check_port "$GW_PORT"; then
        if command -v ss &>/dev/null; then
            PID=$(ss -tlnp 2>/dev/null | grep ":$GW_PORT " | grep -oP 'pid=\K[0-9]+' | head -1 || true)
        elif command -v netstat &>/dev/null; then
            PID=$(netstat -tlnp 2>/dev/null | grep ":$GW_PORT " | awk '{print $NF}' | cut -d/ -f1 || true)
        else
            PID=""
        fi
        [[ -n "${PID:-}" ]] && kill "$PID" 2>/dev/null && sleep 2
    fi
fi

info "Starting OpenClaw gateway..."
nohup openclaw gateway --port "$GW_PORT" --bind "$GW_BIND" --verbose > /tmp/openclaw-gateway.log 2>&1 &
GW_PID=$!

# Wait for gateway (Pi may need more time)
WAIT_SECS=5
[[ "$IS_ARM" == "true" ]] && WAIT_SECS=10
sleep "$WAIT_SECS"

if check_port "$GW_PORT"; then
    ok "Gateway running on port $GW_PORT (PID: $GW_PID)"
else
    warn "Gateway may still be starting. Check: tail -f /tmp/openclaw-gateway.log"
fi

# ── Step 11: Systemd daemon ──────────────────────────────────────────────────

step "Step 11: Auto-start on boot"

if ask_yn "Install OpenClaw as a systemd service (auto-start on boot)?" "y"; then
    openclaw onboard --install-daemon 2>/dev/null && \
        ok "Systemd service installed" || \
        warn "Failed to install daemon. Try: openclaw onboard --install-daemon"
else
    info "Skipped. Start manually: openclaw gateway --port $GW_PORT --bind $GW_BIND --verbose"
fi

# ── Step 12: Quick test ──────────────────────────────────────────────────────

step "Step 12: Testing"

info "Sending test message to agent..."
RESPONSE=$(timeout 30 openclaw agent --local --session-id install-test --message "Reply with exactly: OPENCLAW OK" 2>&1 || true)

if echo "$RESPONSE" | grep -qi "ok"; then
    ok "Agent responded successfully!"
else
    warn "Agent test returned: $RESPONSE"
    warn "Check your API key and model configuration."
fi

# ── Summary ──────────────────────────────────────────────────────────────────

LAN_IP=$(get_lan_ip)

step "Setup complete!"
echo ""
printf "  %-14s %s\n" "Gateway:" "ws://${LAN_IP}:$GW_PORT"
printf "  %-14s %s\n" "Canvas UI:" "http://${LAN_IP}:$GW_PORT/__openclaw__/canvas/"
printf "  %-14s %s\n" "Auth token:" "$GW_TOKEN"
printf "  %-14s %s\n" "Model:" "$MODEL"
printf "  %-14s %s\n" "Config:" "$CONF"
printf "  %-14s %s\n" "Platform:" "$ARCH ($( [[ "$IS_HEADLESS" == true ]] && echo "headless" || echo "desktop" ))"
[[ "$IS_RASPBERRY_PI" == "true" ]] && printf "  %-14s %s\n" "Device:" "$RPI_MODEL"
echo ""
echo "  Quick commands:"
echo "    openclaw agent --local --session-id chat --message \"Hello!\""
echo "    openclaw doctor"
echo "    openclaw channels list"
echo "    openclaw gateway stop"
echo ""

if (( ${#CHANNELS_TO_SETUP[@]} > 0 )); then
    echo "  Channels: ${CHANNELS_TO_SETUP[*]}"
fi

if [[ -n "$CHROMIUM_PATH" ]]; then
    echo "  Browser: $( [[ "$IS_HEADLESS" == true ]] && echo "headless" || echo "desktop" ) Chromium at $CHROMIUM_PATH"
fi

if [[ -n "$SEARCH_PROVIDER" ]]; then
    echo "  Web search: $SEARCH_PROVIDER$( [[ -z "$SEARCH_API_KEY" ]] && echo " (key needed)" || echo " (ready)" )"
fi

echo ""
echo "  Logs: tail -f /tmp/openclaw-gateway.log"
echo ""
ok "OpenClaw is ready!"
