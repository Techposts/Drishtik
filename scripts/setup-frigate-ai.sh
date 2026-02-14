#!/usr/bin/env bash
# =============================================================================
# Frigate → OpenClaw → AI Security Pipeline — Interactive Installer
# =============================================================================
# This script sets up the complete AI-powered security camera pipeline:
#   Frigate (person detection) → Bridge Script → OpenClaw (GPT-4o-mini vision)
#   → WhatsApp notifications + MQTT → Home Assistant → Alexa announcements
#
# Run: bash setup-frigate-ai.sh
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

ask_password() {
    local prompt="$1"
    local default="$2"
    local varname="$3"
    if [[ -n "$default" ]]; then
        echo -ne "  ${GREEN}?${NC}  ${prompt} ${YELLOW}[${default}]${NC}: "
        read -rs input
        echo ""
        printf -v "$varname" '%s' "${input:-$default}"
    else
        echo -ne "  ${GREEN}?${NC}  ${prompt}: "
        read -rs input
        echo ""
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
banner "Frigate → OpenClaw AI Security Pipeline — Setup"

echo ""
echo -e "  This script will set up the complete AI-powered security pipeline."
echo -e "  It will configure Frigate, OpenClaw, the bridge script, and generate"
echo -e "  Home Assistant YAML files for automations and MQTT sensors."
echo ""
echo -e "  ${YELLOW}Prerequisites:${NC}"
echo -e "    • Frigate running (Docker or native)"
echo -e "    • OpenClaw installed with gateway running"
echo -e "    • MQTT broker accessible"
echo -e "    • Python 3.10+"
echo ""
echo -e "  ${CYAN}Tip:${NC} Run ${YELLOW}setup-frigate-ai-prereqs.sh${NC} first to verify system requirements."

ask_yn "Ready to begin?" "Y" READY
if [[ "$READY" != "yes" ]]; then
    echo "  Setup cancelled."
    exit 0
fi

# ---------------------------------------------------------------------------
# Minimal local checks (full checks in setup-frigate-ai-prereqs.sh)
# ---------------------------------------------------------------------------
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
    exit 1
fi

if ! command -v curl &>/dev/null; then
    fail "curl not found — required for API calls"
    echo -e "       ${YELLOW}Install:${NC} sudo apt install curl"
    exit 1
fi

HAS_SYSTEMD=no
if command -v systemctl &>/dev/null; then
    HAS_SYSTEMD=yes
fi

HAS_DOCKER=no
if command -v docker &>/dev/null; then
    HAS_DOCKER=yes
fi

# ---------------------------------------------------------------------------
# Gather user inputs
# ---------------------------------------------------------------------------
banner "Step 1/8 — MQTT Broker Configuration"

info "The MQTT broker connects Frigate, the bridge, and Home Assistant."
echo ""
ask "MQTT broker host"         "192.168.1.20" MQTT_HOST
ask "MQTT broker port"         "1883"          MQTT_PORT
ask "MQTT username"            "<MQTT_USER>"     MQTT_USER
ask_password "MQTT password"   ""              MQTT_PASS

if [[ -z "$MQTT_PASS" ]]; then
    warn "No MQTT password set — will connect without authentication"
fi

# ---------------------------------------------------------------------------
banner "Step 2/8 — Frigate Configuration"

info "Frigate's API is used to download snapshots of detected persons."
echo ""
ask "Frigate API URL"          "http://localhost:5000"           FRIGATE_API
ask "Frigate config.yml path"  "$HOME/frigate/config.yml"       FRIGATE_CONFIG
ask "Snapshot storage directory" "$HOME/frigate/storage/ai-snapshots" SNAPSHOT_DIR

ask_yn "Enable snapshots in Frigate config? (modifies config.yml)" "Y" ENABLE_SNAPSHOTS
ask "Snapshot retention (days)" "7" SNAPSHOT_RETAIN

# ---------------------------------------------------------------------------
banner "Step 3/8 — OpenClaw Configuration"

info "OpenClaw receives snapshots via webhook and analyzes them with GPT-4o-mini."
echo ""
ask "OpenClaw gateway URL"          "http://localhost:18789"     OPENCLAW_URL
ask "OpenClaw gateway auth token"   ""                           OPENCLAW_GATEWAY_TOKEN
ask "OpenClaw config file path"     "$HOME/.openclaw/openclaw.json" OPENCLAW_CONFIG

WEBHOOK_TOKEN=$(head -c 16 /dev/urandom 2>/dev/null | xxd -p 2>/dev/null || echo "frigate-hook-$(date +%s)")
ask "Webhook token for bridge → OpenClaw" "$WEBHOOK_TOKEN"      WEBHOOK_TOKEN

ask_yn "Add hooks config to openclaw.json?" "Y" ADD_HOOKS
ask "AI model for vision analysis" "openai/gpt-4o-mini"         AI_MODEL

# ---------------------------------------------------------------------------
banner "Step 4/8 — Notification Channels"

info "Choose where you want alerts delivered (WhatsApp, Telegram, or both)."
info "OpenClaw must be configured for each channel you enable."
echo ""

ask_yn "Enable analysis-only mode? (no messaging, still generates AI analysis)" "N" ENABLE_ANALYSIS_ONLY
ask_yn "Enable WhatsApp alerts?" "Y" ENABLE_WHATSAPP
ask_yn "Enable Telegram alerts?" "N" ENABLE_TELEGRAM

WHATSAPP_NUMBERS=()
TELEGRAM_CHAT_IDS=()

if [[ "$ENABLE_WHATSAPP" == "yes" ]]; then
    info "The AI analysis + snapshot will be sent to these WhatsApp numbers."
    info "OpenClaw sends FROM its own registered WhatsApp number."
    echo ""
    echo -e "  ${YELLOW}Enter WhatsApp numbers (with country code, e.g. +1234567890).${NC}"
    echo -e "  ${YELLOW}Press Enter on an empty line when done.${NC}"
    echo ""
    while true; do
        echo -ne "  ${GREEN}+${NC}  WhatsApp number (blank to finish): "
        read -r num
        [[ -z "$num" ]] && break
        [[ "$num" != +* ]] && num="+$num"
        WHATSAPP_NUMBERS+=("$num")
        success "Added: $num"
    done

    if [[ ${#WHATSAPP_NUMBERS[@]} -eq 0 ]]; then
        warn "No WhatsApp numbers added — WhatsApp delivery will be disabled"
    fi
fi

if [[ "$ENABLE_TELEGRAM" == "yes" ]]; then
    info "The AI analysis + snapshot will be sent to these Telegram chat IDs."
    info "Use numeric chat IDs (e.g. 123456789) or group IDs (e.g. -1001234567890)."
    echo ""
    echo -e "  ${YELLOW}Press Enter on an empty line when done.${NC}"
    echo ""
    while true; do
        echo -ne "  ${GREEN}+${NC}  Telegram chat ID (blank to finish): "
        read -r chat
        [[ -z "$chat" ]] && break
        TELEGRAM_CHAT_IDS+=("$chat")
        success "Added: $chat"
    done

    if [[ ${#TELEGRAM_CHAT_IDS[@]} -eq 0 ]]; then
        warn "No Telegram chat IDs added — Telegram delivery will be disabled"
    fi
fi

if [[ "$ENABLE_ANALYSIS_ONLY" == "yes" ]]; then
    if [[ ${#WHATSAPP_NUMBERS[@]} -gt 0 || ${#TELEGRAM_CHAT_IDS[@]} -gt 0 ]]; then
        warn "Analysis-only mode enabled — message delivery targets will be ignored"
        WHATSAPP_NUMBERS=()
        TELEGRAM_CHAT_IDS=()
    else
        info "Analysis-only mode enabled — no message delivery targets configured."
    fi
fi

# ---------------------------------------------------------------------------
banner "Step 5/8 — Alexa Echo Devices (for Home Assistant)"

info "Enter Alexa device entity IDs from Home Assistant."
info "Find them in HA → Developer Tools → States → filter 'media_player.'"
echo ""

ALEXA_DEVICES=()
echo -e "  ${YELLOW}Enter Alexa entity IDs (e.g. media_player.living_room_echo).${NC}"
echo -e "  ${YELLOW}Press Enter on an empty line when done.${NC}"
echo ""
while true; do
    echo -ne "  ${GREEN}+${NC}  Alexa entity ID (blank to finish): "
    read -r dev
    [[ -z "$dev" ]] && break
    ALEXA_DEVICES+=("$dev")
    success "Added: $dev"
done

if [[ ${#ALEXA_DEVICES[@]} -eq 0 ]]; then
    warn "No Alexa devices added — Alexa automation will be commented out"
fi

# ---------------------------------------------------------------------------
banner "Step 6/8 — Bridge Settings"

ask "Cooldown between alerts per camera (seconds)" "30" COOLDOWN
ask "Snapshot download delay (seconds, wait for Frigate)" "3" SNAP_DELAY
ask "Bridge script location" "$HOME/frigate/frigate-openclaw-bridge.py" BRIDGE_SCRIPT
ask "Python venv location"   "$HOME/frigate/bridge-venv"              VENV_DIR

SKILL_DIR="$HOME/.openclaw/workspace/skills/frigate"
ask "OpenClaw skill directory" "$SKILL_DIR" SKILL_DIR

# ---------------------------------------------------------------------------
# Summary & confirm
# ---------------------------------------------------------------------------
banner "Step 7/8 — Review Configuration"

echo ""
echo -e "  ${BOLD}MQTT Broker${NC}"
echo -e "    Host:       $MQTT_HOST:$MQTT_PORT"
echo -e "    User:       $MQTT_USER"
echo ""
echo -e "  ${BOLD}Frigate${NC}"
echo -e "    API:        $FRIGATE_API"
echo -e "    Config:     $FRIGATE_CONFIG"
echo -e "    Snapshots:  $SNAPSHOT_DIR (${SNAPSHOT_RETAIN}d retention)"
echo ""
echo -e "  ${BOLD}OpenClaw${NC}"
echo -e "    URL:        $OPENCLAW_URL"
echo -e "    Config:     $OPENCLAW_CONFIG"
echo -e "    Webhook:    ${OPENCLAW_URL}/hooks/agent"
echo -e "    Model:      $AI_MODEL"
echo ""
echo -e "  ${BOLD}WhatsApp Recipients${NC}"
for n in "${WHATSAPP_NUMBERS[@]:-}"; do
    [[ -n "$n" ]] && echo -e "    • $n"
done
if [[ ${#WHATSAPP_NUMBERS[@]} -eq 0 ]]; then
    echo -e "    (none)"
fi
echo ""
echo -e "  ${BOLD}Telegram Recipients${NC}"
for t in "${TELEGRAM_CHAT_IDS[@]:-}"; do
    [[ -n "$t" ]] && echo -e "    • $t"
done
if [[ ${#TELEGRAM_CHAT_IDS[@]} -eq 0 ]]; then
    echo -e "    (none)"
fi
echo ""
echo -e "  ${BOLD}Analysis-Only Mode${NC}"
echo -e "    ${ENABLE_ANALYSIS_ONLY}"
echo ""
echo -e "  ${BOLD}Alexa Devices${NC}"
for d in "${ALEXA_DEVICES[@]:-}"; do
    [[ -n "$d" ]] && echo -e "    • $d"
done
echo ""
echo -e "  ${BOLD}Bridge${NC}"
echo -e "    Script:     $BRIDGE_SCRIPT"
echo -e "    Venv:       $VENV_DIR"
echo -e "    Cooldown:   ${COOLDOWN}s"
echo -e "    Snap Delay: ${SNAP_DELAY}s"
echo ""

ask_yn "Proceed with installation?" "Y" PROCEED
if [[ "$PROCEED" != "yes" ]]; then
    echo "  Setup cancelled."
    exit 0
fi

# ---------------------------------------------------------------------------
# Execute installation
# ---------------------------------------------------------------------------
banner "Step 8/8 — Installing"

ERRORS=0

# ── 9.1 Create directories ──────────────────────────────────────────────
info "Creating directories..."
mkdir -p "$SNAPSHOT_DIR"
mkdir -p "$SKILL_DIR"
mkdir -p "$(dirname "$BRIDGE_SCRIPT")"
mkdir -p "$HOME/.config/systemd/user"
success "Directories created"

# ── 9.2 Modify Frigate config ───────────────────────────────────────────
if [[ "$ENABLE_SNAPSHOTS" == "yes" ]]; then
    info "Updating Frigate config (enabling snapshots)..."
    if [[ -f "$FRIGATE_CONFIG" ]]; then
        # Backup
        cp "$FRIGATE_CONFIG" "${FRIGATE_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"

        if grep -q "snapshots:" "$FRIGATE_CONFIG"; then
            # Replace existing snapshots section
            # Use python for reliable multiline YAML editing
            $PYTHON_BIN -c "
import re, sys
with open('$FRIGATE_CONFIG', 'r') as f:
    content = f.read()
# Match snapshots block (up to next top-level key or EOF)
pattern = r'snapshots:\n(?:  .*\n)*'
replacement = '''snapshots:
  enabled: true
  retain:
    default: $SNAPSHOT_RETAIN
'''
new_content = re.sub(pattern, replacement, content)
if new_content == content:
    # Fallback: simple replace
    new_content = content.replace('snapshots:\n  enabled: false', 'snapshots:\n  enabled: true\n  retain:\n    default: $SNAPSHOT_RETAIN')
with open('$FRIGATE_CONFIG', 'w') as f:
    f.write(new_content)
"
            success "Frigate snapshots enabled (${SNAPSHOT_RETAIN}-day retention)"
        else
            # Add snapshots section before cameras
            sed -i '/^cameras:/i snapshots:\n  enabled: true\n  retain:\n    default: '"$SNAPSHOT_RETAIN"'\n' "$FRIGATE_CONFIG"
            success "Frigate snapshots section added"
        fi
    else
        warn "Frigate config not found at $FRIGATE_CONFIG — skipping"
        ((ERRORS++)) || true
    fi
fi

# ── 9.3 Modify OpenClaw config ──────────────────────────────────────────
if [[ "$ADD_HOOKS" == "yes" ]]; then
    info "Updating OpenClaw config (adding hooks)..."
    if [[ -f "$OPENCLAW_CONFIG" ]]; then
        cp "$OPENCLAW_CONFIG" "${OPENCLAW_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"

        WA_JSON=$(printf '%s\n' "${WHATSAPP_NUMBERS[@]:-}" | $PYTHON_BIN -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')

        if grep -q '"hooks"' "$OPENCLAW_CONFIG"; then
            info "hooks section already exists in openclaw.json — skipping"
            if [[ "${#WHATSAPP_NUMBERS[@]:-0}" -gt 0 ]]; then
                $PYTHON_BIN -c "
import json
with open('$OPENCLAW_CONFIG', 'r') as f:
    config = json.load(f)
wa_list = json.loads('''$WA_JSON''')
numbers = config.get('channels', {}).get('whatsapp', {}).get('allowFrom', [])
for num in wa_list:
    if num and num not in numbers:
        numbers.append(num)
if numbers:
    config.setdefault('channels', {}).setdefault('whatsapp', {})['allowFrom'] = numbers
with open('$OPENCLAW_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\\n')
"
                success "OpenClaw WhatsApp allowlist updated"
            fi
        else
            $PYTHON_BIN -c "
import json, sys
with open('$OPENCLAW_CONFIG', 'r') as f:
    config = json.load(f)
config['hooks'] = {
    'enabled': True,
    'token': '$WEBHOOK_TOKEN',
    'path': '/hooks'
}
# Add WhatsApp numbers to allowlist if not present
wa_list = json.loads('''$WA_JSON''')
numbers = config.get('channels', {}).get('whatsapp', {}).get('allowFrom', [])
for num in wa_list:
    if num and num not in numbers:
        numbers.append(num)
if numbers:
    config.setdefault('channels', {}).setdefault('whatsapp', {})['allowFrom'] = numbers
with open('$OPENCLAW_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
" 2>/dev/null || {
            # Fallback: simpler approach
            $PYTHON_BIN -c "
import json
with open('$OPENCLAW_CONFIG', 'r') as f:
    config = json.load(f)
config['hooks'] = {
    'enabled': True,
    'token': '$WEBHOOK_TOKEN',
    'path': '/hooks'
}
with open('$OPENCLAW_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
"
            }
            success "OpenClaw hooks config added (token: $WEBHOOK_TOKEN)"
        fi
    else
        warn "OpenClaw config not found at $OPENCLAW_CONFIG — skipping"
        ((ERRORS++)) || true
    fi
fi

if [[ "$ENABLE_TELEGRAM" == "yes" && -f "$OPENCLAW_CONFIG" ]]; then
    if ! grep -q '"telegram"' "$OPENCLAW_CONFIG"; then
        warn "Telegram enabled but no telegram channel config found in openclaw.json"
        echo -e "       ${YELLOW}Make sure OpenClaw has Telegram bot credentials configured.${NC}"
    fi
fi

# ── 9.4 Create Python venv & install dependencies ───────────────────────
info "Setting up Python virtual environment..."
if [[ ! -d "$VENV_DIR" ]]; then
    $PYTHON_BIN -m venv "$VENV_DIR"
    success "Created venv at $VENV_DIR"
else
    info "Venv already exists at $VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --quiet --upgrade pip 2>/dev/null
"$VENV_DIR/bin/pip" install --quiet paho-mqtt requests 2>/dev/null
success "Installed paho-mqtt and requests"

# ── 9.5 Build delivery list for Python ──────────────────────────────────
DELIVERY_PY_LIST=""
for n in "${WHATSAPP_NUMBERS[@]:-}"; do
    [[ -n "$n" ]] && DELIVERY_PY_LIST+="{\"channel\":\"whatsapp\",\"to\":\"$n\"}, "
done
for t in "${TELEGRAM_CHAT_IDS[@]:-}"; do
    [[ -n "$t" ]] && DELIVERY_PY_LIST+="{\"channel\":\"telegram\",\"to\":\"$t\"}, "
done
DELIVERY_PY_LIST="[${DELIVERY_PY_LIST%, }]"

# ── 9.6 Create bridge script ────────────────────────────────────────────
info "Creating bridge script..."
cat > "$BRIDGE_SCRIPT" << 'BRIDGE_SCRIPT_HEREDOC'
#!/usr/bin/env python3
"""
Frigate → OpenClaw Bridge
Auto-generated by setup-frigate-ai.sh

Listens for Frigate person-detection events via MQTT, downloads the snapshot,
sends it to OpenClaw for vision AI analysis, and publishes the analysis back
to MQTT for Home Assistant.
"""

import json
import logging
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import requests

# ---------------------------------------------------------------------------
# Configuration — auto-populated by installer
# ---------------------------------------------------------------------------
MQTT_HOST = "%%MQTT_HOST%%"
MQTT_PORT = %%MQTT_PORT%%
MQTT_USER = "%%MQTT_USER%%"
MQTT_PASS = "%%MQTT_PASS%%"
MQTT_TOPIC_SUBSCRIBE = "frigate/events"
MQTT_TOPIC_PUBLISH = "openclaw/frigate/analysis"

FRIGATE_API = "%%FRIGATE_API%%"
OPENCLAW_WEBHOOK = "%%OPENCLAW_URL%%/hooks/agent"
OPENCLAW_TOKEN = "%%WEBHOOK_TOKEN%%"

SNAPSHOT_DIR = Path("%%SNAPSHOT_DIR%%")
OPENCLAW_WORKSPACE = Path("~/.openclaw/workspace").expanduser()
OPENCLAW_MEDIA_DIR = OPENCLAW_WORKSPACE / "ai-snapshots"
OPENCLAW_SESSIONS_DIR = Path("~/.openclaw/agents/main/sessions").expanduser()
OPENCLAW_SESSIONS_INDEX = OPENCLAW_SESSIONS_DIR / "sessions.json"
DELIVERY_TARGETS = %%DELIVERY_TARGETS%%
ANALYSIS_ONLY = %%ANALYSIS_ONLY%%

AI_MODEL = "%%AI_MODEL%%"
COOLDOWN_SECONDS = %%COOLDOWN%%
SNAPSHOT_DELAY = %%SNAP_DELAY%%

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("frigate-bridge")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
last_alert: dict[str, float] = {}


def is_on_cooldown(camera: str) -> bool:
    now = time.time()
    if camera in last_alert and (now - last_alert[camera]) < COOLDOWN_SECONDS:
        return True
    last_alert[camera] = now
    return False


def download_snapshot(event_id: str) -> Path | None:
    """Download snapshot (or thumbnail fallback) from Frigate API."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    dest = SNAPSHOT_DIR / f"{event_id}.jpg"

    for endpoint in ("snapshot.jpg", "thumbnail.jpg"):
        url = f"{FRIGATE_API}/api/events/{event_id}/{endpoint}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                dest.write_bytes(resp.content)
                log.info("Saved %s (%d bytes) via %s", dest, len(resp.content), endpoint)
                return dest
        except requests.RequestException as exc:
            log.warning("Failed to fetch %s: %s", url, exc)

    log.error("Could not download snapshot for event %s", event_id)
    return None


def extract_risk(analysis: str) -> str:
    """Extract threat/risk level from the analysis text."""
    upper = analysis.upper()
    if "THREAT: HIGH" in upper or "THREAT:HIGH" in upper:
        return "high"
    if "THREAT: MEDIUM" in upper or "THREAT:MEDIUM" in upper:
        return "medium"
    return "low"


def make_tts(camera: str, analysis: str) -> str:
    """Create a short spoken version of the analysis for Alexa TTS."""
    sentences = analysis.replace("\n", " ").split(". ")
    short = ". ".join(sentences[:2]).strip()
    if short and not short.endswith("."):
        short += "."
    return f"Security alert, {camera}. {short}"


def stage_snapshot_for_openclaw(src: Path, event_id: str) -> Path | None:
    """Copy snapshot into OpenClaw workspace so MEDIA:./... works."""
    try:
        OPENCLAW_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        dest = OPENCLAW_MEDIA_DIR / f"{event_id}.jpg"
        shutil.copyfile(src, dest)
        return dest
    except Exception as exc:
        log.warning("Failed to stage snapshot for OpenClaw: %s", exc)
        return None


def read_openclaw_session_reply(session_key: str, timeout_seconds: int = 75) -> str | None:
    """Read the latest assistant reply from OpenClaw session logs for a session key."""
    if not OPENCLAW_SESSIONS_INDEX.exists():
        log.warning("OpenClaw sessions index not found: %s", OPENCLAW_SESSIONS_INDEX)
        return None

    norm_key = session_key.strip().lower()
    full_key = f"agent:main:{norm_key}"
    deadline = time.time() + timeout_seconds
    session_id = None

    while time.time() < deadline and not session_id:
        try:
            data = json.loads(OPENCLAW_SESSIONS_INDEX.read_text())
            entry = data.get(full_key)
            if entry and isinstance(entry, dict):
                session_id = entry.get("sessionId")
                if session_id:
                    break
        except Exception as exc:
            log.warning("Failed reading sessions index: %s", exc)
        time.sleep(1)

    if not session_id:
        log.warning("No OpenClaw session found for key %s", full_key)
        return None

    session_file = OPENCLAW_SESSIONS_DIR / f"{session_id}.jsonl"
    while time.time() < deadline:
        if not session_file.exists():
            time.sleep(1)
            continue
        try:
            last_reply = None
            with session_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if item.get("type") != "message":
                        continue
                    message = item.get("message") or {}
                    if message.get("role") != "assistant":
                        continue
                    content = message.get("content") or []
                    if not isinstance(content, list):
                        continue
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text = part.get("text")
                            if text:
                                text_parts.append(text)
                    if text_parts:
                        last_reply = "\n".join(text_parts).strip()
            if last_reply:
                lines = [ln for ln in last_reply.splitlines() if not ln.strip().startswith("MEDIA:")]
                cleaned = "\n".join(lines).strip()
                return cleaned or last_reply
        except Exception as exc:
            log.warning("Failed reading session file %s: %s", session_file, exc)
        time.sleep(1)

    if not session_file.exists():
        log.warning("OpenClaw session file missing after timeout: %s", session_file)
    else:
        log.warning("Timed out waiting for OpenClaw reply for %s", session_key)
    return None


def send_to_openclaw(camera: str, event_id: str) -> str | None:
    """POST the snapshot to OpenClaw webhook for vision AI analysis."""
    if not DELIVERY_TARGETS and not ANALYSIS_ONLY:
        log.warning("No delivery targets configured; skipping OpenClaw analysis")
        return None

    openclaw_rel_media = f"./.openclaw/workspace/ai-snapshots/{event_id}.jpg"
    openclaw_abs_media = str(OPENCLAW_MEDIA_DIR / f"{event_id}.jpg")

    prompt = (
        f"Security alert from camera '{camera}'. "
        f"Use the image tool to open and analyze the snapshot at: {openclaw_abs_media}\n\n"
        "IMPORTANT: You CAN and MUST use the image tool to view the snapshot. "
        "Do NOT say you cannot analyze the image — you have the image tool available. "
        "Open the image first, then respond.\n\n"
        "After viewing the image, your reply MUST have exactly two parts:\n\n"
        "PART 1 — Send the snapshot image using this exact line:\n"
        f"MEDIA:{openclaw_rel_media}\n\n"
        "PART 2 — Below the MEDIA line, provide a brief security assessment:\n"
        f"[{camera}] Threat: LOW/MEDIUM/HIGH\n"
        "Description of what you see. Recommended action if any.\n\n"
        "Rules:\n"
        "- 3-5 sentences max, this goes to a phone notification\n"
        "- Be factual and direct, no questions or disclaimers\n"
        "- Do NOT ask the user anything, just report what you see\n"
        "- Always include the MEDIA line BEFORE the text analysis"
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
    }

    # Analysis-only path (no delivery)
    if ANALYSIS_ONLY and not DELIVERY_TARGETS:
        payload = {
            "message": prompt,
            "model": AI_MODEL,
            "deliver": False,
            "name": "Frigate",
            "sessionKey": f"frigate:{camera}:{event_id}",
            "timeoutSeconds": 60,
        }
        try:
            resp = requests.post(
                OPENCLAW_WEBHOOK,
                json=payload,
                headers=headers,
                timeout=90,
            )
            if resp.status_code in (200, 201, 202):
                log.info("OpenClaw analysis-only (%d)", resp.status_code)
            else:
                log.error("OpenClaw analysis-only returned %d: %s", resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.error("OpenClaw analysis-only failed: %s", exc)
        return read_openclaw_session_reply(f"frigate:{camera}:{event_id}")

    # Delivery path (WhatsApp/Telegram/etc.)
    for target in DELIVERY_TARGETS:
        channel = target.get("channel")
        recipient = target.get("to")
        if not channel or not recipient:
            continue
        payload = {
            "message": prompt,
            "model": AI_MODEL,
            "deliver": True,
            "channel": channel,
            "to": recipient,
            "name": "Frigate",
            "sessionKey": f"frigate:{camera}:{event_id}",
            "timeoutSeconds": 60,
        }

        try:
            resp = requests.post(
                OPENCLAW_WEBHOOK,
                json=payload,
                headers=headers,
                timeout=90,
            )
            if resp.status_code in (200, 201, 202):
                log.info("OpenClaw → %s:%s (%d)", channel, recipient, resp.status_code)
            else:
                log.error("OpenClaw → %s:%s returned %d: %s", channel, recipient, resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.error("OpenClaw → %s:%s failed: %s", channel, recipient, exc)

    return read_openclaw_session_reply(f"frigate:{camera}:{event_id}")


def publish_analysis(client: mqtt.Client, camera: str, label: str,
                     analysis: str, event_id: str, snapshot_path: Path):
    """Publish the AI analysis to MQTT for Home Assistant."""
    risk = extract_risk(analysis)
    payload = {
        "camera": camera,
        "label": label,
        "analysis": analysis,
        "risk": risk,
        "tts": make_tts(camera, analysis),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id,
        "snapshot_path": str(snapshot_path),
    }
    result = client.publish(MQTT_TOPIC_PUBLISH, json.dumps(payload), qos=1, retain=True)
    log.info("Published analysis to %s (risk=%s, rc=%s)", MQTT_TOPIC_PUBLISH, risk, result.rc)


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to MQTT broker %s:%d", MQTT_HOST, MQTT_PORT)
        client.subscribe(MQTT_TOPIC_SUBSCRIBE)
        log.info("Subscribed to %s", MQTT_TOPIC_SUBSCRIBE)
    else:
        log.error("MQTT connection failed with code %d", rc)


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
    except (json.JSONDecodeError, ValueError):
        return

    after = data.get("after", {})
    event_type = data.get("type", "")

    if event_type != "new":
        return

    label = after.get("label", "")
    if label != "person":
        return

    camera = after.get("camera", "unknown")
    event_id = after.get("id", "")

    if not event_id:
        return

    log.info("Person detected on %s (event %s)", camera, event_id)

    if is_on_cooldown(camera):
        log.info("Skipping %s — cooldown active for %s", event_id, camera)
        return

    time.sleep(SNAPSHOT_DELAY)

    snapshot_path = download_snapshot(event_id)
    if not snapshot_path:
        return

    staged_path = stage_snapshot_for_openclaw(snapshot_path, event_id)
    if not staged_path:
        return

    # Publish immediate pending notice to HA
    publish_analysis(
        client, camera, label,
        f"Person detected on {camera} — vision analysis pending.",
        event_id, snapshot_path,
    )

    analysis = send_to_openclaw(camera, event_id)
    if analysis:
        publish_analysis(client, camera, label, analysis, event_id, snapshot_path)


def on_disconnect(client, userdata, rc, properties=None):
    log.warning("Disconnected from MQTT (rc=%d), will reconnect...", rc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("Frigate → OpenClaw bridge starting")
    log.info("MQTT: %s:%d | Frigate: %s | OpenClaw: %s", MQTT_HOST, MQTT_PORT, FRIGATE_API, OPENCLAW_WEBHOOK)
    log.info("Delivery targets: %s | Analysis-only: %s | Cooldown: %ds", DELIVERY_TARGETS, ANALYSIS_ONLY, COOLDOWN_SECONDS)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    client = mqtt.Client(
        client_id="frigate-openclaw-bridge",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    log.info("Connecting to MQTT %s:%d...", MQTT_HOST, MQTT_PORT)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
BRIDGE_SCRIPT_HEREDOC

# Replace placeholders with actual values
MQTT_HOST="$MQTT_HOST" \
MQTT_PORT="$MQTT_PORT" \
MQTT_USER="$MQTT_USER" \
MQTT_PASS="$MQTT_PASS" \
FRIGATE_API="$FRIGATE_API" \
OPENCLAW_URL="$OPENCLAW_URL" \
WEBHOOK_TOKEN="$WEBHOOK_TOKEN" \
SNAPSHOT_DIR="$SNAPSHOT_DIR" \
DELIVERY_TARGETS="$DELIVERY_PY_LIST" \
AI_MODEL="$AI_MODEL" \
COOLDOWN="$COOLDOWN" \
SNAP_DELAY="$SNAP_DELAY" \
ANALYSIS_ONLY="$ENABLE_ANALYSIS_ONLY" \
BRIDGE_SCRIPT="$BRIDGE_SCRIPT" \
$PYTHON_BIN - << 'PY'
import os

path = os.environ["BRIDGE_SCRIPT"]
repl = {
    "%%MQTT_HOST%%": os.environ["MQTT_HOST"],
    "%%MQTT_PORT%%": os.environ["MQTT_PORT"],
    "%%MQTT_USER%%": os.environ["MQTT_USER"],
    "%%MQTT_PASS%%": os.environ["MQTT_PASS"],
    "%%FRIGATE_API%%": os.environ["FRIGATE_API"],
    "%%OPENCLAW_URL%%": os.environ["OPENCLAW_URL"],
    "%%WEBHOOK_TOKEN%%": os.environ["WEBHOOK_TOKEN"],
    "%%SNAPSHOT_DIR%%": os.environ["SNAPSHOT_DIR"],
    "%%DELIVERY_TARGETS%%": os.environ["DELIVERY_TARGETS"],
    "%%AI_MODEL%%": os.environ["AI_MODEL"],
    "%%COOLDOWN%%": os.environ["COOLDOWN"],
    "%%SNAP_DELAY%%": os.environ["SNAP_DELAY"],
    "%%ANALYSIS_ONLY%%": "True" if os.environ.get("ANALYSIS_ONLY", "no").lower() in ("yes", "true", "1") else "False",
}
text = open(path, "r", encoding="utf-8").read()
for k, v in repl.items():
    text = text.replace(k, str(v))
open(path, "w", encoding="utf-8").write(text)
PY

chmod +x "$BRIDGE_SCRIPT"
success "Bridge script created at $BRIDGE_SCRIPT"

# ── 9.7 Create OpenClaw Frigate skill ───────────────────────────────────
info "Creating OpenClaw Frigate skill..."
cat > "$SKILL_DIR/SKILL.md" << 'SKILL_EOF'
# Frigate Security Camera Analysis

You are acting as a security camera AI analyst. When you receive a message from the Frigate bridge, follow these steps:

## How to Process

1. **Open the snapshot** using the `image` tool with the file path provided in the message.
2. **Analyze the image** for security-relevant details.
3. **Respond with a concise security assessment** suitable for a WhatsApp notification.

## What to Look For

- **People**: Count, approximate age/gender, clothing description, distinguishing features
- **Activity**: Walking, standing, carrying items, approaching door, loitering, running
- **Location context**: Match observations to the camera name
- **Time context**: Note if it appears to be day or night based on lighting
- **Vehicles or objects**: Packages, bags, tools, vehicles in frame
- **Threat indicators**: Unfamiliar person, unusual hour, suspicious behavior, face concealment

## Threat Level Guidelines

- **LOW**: Familiar-looking activity, delivery person, daytime, normal behavior
- **MEDIUM**: Unfamiliar person, unusual time, lingering near entry points
- **HIGH**: Attempted entry, face concealment, multiple unknown persons at night, suspicious tools

## Response Format

Keep the response to 3-5 sentences for WhatsApp readability:

```
[CameraName] Threat: LOW/MEDIUM/HIGH
Description of what you see. Recommended action if any.
```

## Important Notes

- Always use the `image` tool to view the snapshot — never guess without seeing it.
- Be factual and objective. Describe what you see, not assumptions.
- If the image is unclear or too dark, say so rather than speculating.
- Prioritize brevity — this goes to a phone notification.
SKILL_EOF
success "Frigate skill created at $SKILL_DIR/SKILL.md"

# ── 9.8 Create systemd service ──────────────────────────────────────────
if [[ "$HAS_SYSTEMD" == "yes" ]]; then
    info "Creating systemd service..."
    SERVICE_FILE="$HOME/.config/systemd/user/frigate-openclaw-bridge.service"
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Frigate → OpenClaw Vision AI Bridge
After=network-online.target openclaw-gateway.service
Wants=network-online.target

[Service]
ExecStart=$VENV_DIR/bin/python3 $BRIDGE_SCRIPT
Restart=always
RestartSec=10
KillMode=process
Environment="HOME=$HOME"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=default.target
EOF
    success "Systemd service created at $SERVICE_FILE"
else
    warn "systemd not available — skipping service creation"
fi

# ── 9.9 Generate HA YAML files ──────────────────────────────────────────
OUTPUT_DIR="$(dirname "$BRIDGE_SCRIPT")"

info "Generating Home Assistant YAML files..."

# ── HA MQTT Sensors ─────────────────────────────────────────────────────
cat > "$OUTPUT_DIR/ha-mqtt-sensors.yaml" << 'HA_MQTT_EOF'
# =============================================================================
# Frigate AI Security — MQTT Sensors for Home Assistant
# =============================================================================
# Add this to your HA configuration.yaml under the mqtt: section,
# or include it via: mqtt: !include ha-mqtt-sensors.yaml
#
# After adding, restart HA or reload MQTT entities:
#   Developer Tools → YAML → MQTT entities
# =============================================================================

sensor:
  - name: "Frigate AI Analysis"
    state_topic: "openclaw/frigate/analysis"
    value_template: "{{ value_json.camera }}"
    json_attributes_topic: "openclaw/frigate/analysis"
    json_attributes_template: "{{ value_json | tojson }}"
    icon: "mdi:cctv"

  - name: "Frigate AI Analysis Text"
    state_topic: "openclaw/frigate/analysis"
    value_template: "{{ value_json.analysis[:250] }}"
    icon: "mdi:text-box-outline"

  - name: "Frigate AI Risk Level"
    state_topic: "openclaw/frigate/analysis"
    value_template: "{{ value_json.risk | upper }}"
    icon: "mdi:shield-alert"

  - name: "Frigate AI Last Camera"
    state_topic: "openclaw/frigate/analysis"
    value_template: "{{ value_json.camera }}"
    icon: "mdi:camera"

  - name: "Frigate AI Timestamp"
    state_topic: "openclaw/frigate/analysis"
    value_template: "{{ value_json.timestamp }}"
    device_class: "timestamp"
    icon: "mdi:clock-outline"

  - name: "Frigate AI TTS"
    state_topic: "openclaw/frigate/analysis"
    value_template: "{{ value_json.tts[:250] }}"
    icon: "mdi:bullhorn"
HA_MQTT_EOF
success "Created $OUTPUT_DIR/ha-mqtt-sensors.yaml"

# ── HA Automations ──────────────────────────────────────────────────────
# Build Alexa target list
ALEXA_TARGET_YAML=""
for d in "${ALEXA_DEVICES[@]:-}"; do
    [[ -n "$d" ]] && ALEXA_TARGET_YAML+="          - ${d}\n"
done

if [[ ${#ALEXA_DEVICES[@]} -gt 0 ]]; then
    ALEXA_COMMENT=""
else
    ALEXA_COMMENT="# "
fi

cat > "$OUTPUT_DIR/ha-frigate-ai-automation.yaml" << HAUTO_EOF
# =============================================================================
# Frigate AI Security — Home Assistant Automations
# =============================================================================
# Copy into your HA automations.yaml or import via Settings → Automations
#
# MQTT topic: openclaw/frigate/analysis
# Payload fields: camera, label, analysis, risk, tts, timestamp,
#                 event_id, snapshot_path
# Risk values: "low", "medium", "high"
#
# Auto-generated by setup-frigate-ai.sh on $(date +%Y-%m-%d)
# =============================================================================
#
# Required Helpers (create once in HA):
#   input_datetime.frigate_ai_last_alexa
#   input_datetime.frigate_ai_last_echo
# You can create these via Settings → Devices & Services → Helpers.

# -----------------------------------------------------------------------------
# Single Automation — Alexa, Mobile, Echo Show, Persistent, Debug
# -----------------------------------------------------------------------------
- alias: "Frigate AI — Unified Automation"
  id: frigate_ai_unified
  description: "Unified handler for Alexa, mobile, Echo Show, persistent, and debug logging"
  mode: parallel
  max: 10
  max_exceeded: silent

  trigger:
    - platform: mqtt
      topic: "openclaw/frigate/analysis"

  condition:
    - condition: template
      value_template: "{{ trigger.payload_json is defined }}"

  action:
    - variables:
        risk: "{{ trigger.payload_json.risk | default('low') }}"
        camera: "{{ trigger.payload_json.camera | default('Camera') }}"
        analysis: "{{ trigger.payload_json.analysis | default('Detection event') }}"
        tts: "{{ trigger.payload_json.tts | default('Security alert detected') }}"
        event_id: "{{ trigger.payload_json.event_id | default('') }}"
        snapshot_path: "{{ trigger.payload_json.snapshot_path | default('') }}"

    # Alexa Announcement — MEDIUM/HIGH risk only, daytime, 60s cooldown
    - choose:
        - conditions:
            - condition: time
              after: "06:00:00"
              before: "23:00:00"
            - condition: template
              value_template: "{{ risk in ['medium', 'high'] }}"
            - condition: template
              value_template: >-
                {% set last = as_timestamp(states('input_datetime.frigate_ai_last_alexa')) or 0 %}
                {{ (as_timestamp(now()) - last) > 60 }}
          sequence:
            - service: notify.alexa_media
              data:
                message: >-
                  {{ tts }}
                target:
$(for d in "${ALEXA_DEVICES[@]:-}"; do [[ -n "$d" ]] && echo "                  - ${d}"; done)
                data:
                  type: announce
            - service: input_datetime.set_datetime
              target:
                entity_id: input_datetime.frigate_ai_last_alexa
              data:
                datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      default: []

    # Mobile Notification — all events with snapshot
    - service: notify.notify
      data:
        title: >-
          {{ camera }} — Person Detected
        message: >-
          {{ analysis }}
        data:
          image: >-
            {{ snapshot_path }}
          clickAction: "/lovelace/cameras"
          tag: "frigate-{{ event_id | default(camera | default('unknown')) }}"
          group: "frigate-security"

    # Echo Show — snapshot image with 45s cooldown
    - choose:
        - conditions:
            - condition: template
              value_template: "{{ event_id | length > 0 }}"
            - condition: template
              value_template: >-
                {% set last = as_timestamp(states('input_datetime.frigate_ai_last_echo')) or 0 %}
                {{ (as_timestamp(now()) - last) > 45 }}
          sequence:
            - service: media_player.play_media
              target:
                entity_id: media_player.echo_show_5
              data:
                media_content_type: image
                media_content_id: >-
                  ${FRIGATE_API}/api/events/{{ event_id }}/snapshot.jpg
            - service: input_datetime.set_datetime
              target:
                entity_id: input_datetime.frigate_ai_last_echo
              data:
                datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      default: []

    # Persistent Notification — HA sidebar
    - service: persistent_notification.create
      data:
        title: >-
          Security — {{ camera }}
        message: >-
          **Risk:** {{ risk | upper }}

          **Time:** {{ trigger.payload_json.timestamp | default('unknown') }}

          {{ analysis }}
        notification_id: "frigate_{{ camera | default('unknown') }}"

    # Debug Logger — Log raw MQTT payload
    - service: logbook.log
      data:
        name: "Frigate AI"
        message: >-
          {{ trigger.payload }}
HAUTO_EOF
success "Created $OUTPUT_DIR/ha-frigate-ai-automation.yaml"

# ── 9.10 Start services ─────────────────────────────────────────────────
echo ""
ask_yn "Start the bridge service now?" "Y" START_NOW

if [[ "$START_NOW" == "yes" ]]; then
    if [[ "$HAS_SYSTEMD" == "yes" ]]; then
        info "Reloading systemd and starting bridge..."
        systemctl --user daemon-reload

        # Restart Frigate if Docker available
        if command -v docker &>/dev/null && docker ps --filter name=frigate --format '{{.Names}}' 2>/dev/null | grep -q frigate; then
            info "Restarting Frigate container..."
            docker restart frigate >/dev/null 2>&1 && success "Frigate restarted" || warn "Failed to restart Frigate"
        fi

        # Restart OpenClaw if service exists
        if systemctl --user is-active openclaw-gateway.service &>/dev/null; then
            info "Restarting OpenClaw gateway..."
            systemctl --user restart openclaw-gateway.service && success "OpenClaw gateway restarted" || warn "Failed to restart OpenClaw"
        fi

        # Enable and start bridge
        systemctl --user enable frigate-openclaw-bridge.service 2>/dev/null
        systemctl --user restart frigate-openclaw-bridge.service
        sleep 2

        if systemctl --user is-active frigate-openclaw-bridge.service &>/dev/null; then
            success "Bridge service started and enabled"
        else
            fail "Bridge service failed to start. Check: journalctl --user -u frigate-openclaw-bridge.service"
            ((ERRORS++)) || true
        fi
    else
        warn "systemd not available — cannot start bridge service automatically"
    fi
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
echo -e "  ${BOLD}Files Created / Modified:${NC}"
echo -e "    ${GREEN}✔${NC}  $BRIDGE_SCRIPT"
echo -e "    ${GREEN}✔${NC}  $SKILL_DIR/SKILL.md"
if [[ "$HAS_SYSTEMD" == "yes" ]]; then
    echo -e "    ${GREEN}✔${NC}  $SERVICE_FILE"
fi
echo -e "    ${GREEN}✔${NC}  $OUTPUT_DIR/ha-mqtt-sensors.yaml"
echo -e "    ${GREEN}✔${NC}  $OUTPUT_DIR/ha-frigate-ai-automation.yaml"
echo ""
echo -e "  ${BOLD}What You Need to Do in Home Assistant:${NC}"
echo ""
echo -e "    ${CYAN}1.${NC} Add MQTT sensors to your HA configuration:"
echo -e "       Copy contents of: ${YELLOW}$OUTPUT_DIR/ha-mqtt-sensors.yaml${NC}"
echo -e "       Into your HA ${YELLOW}configuration.yaml${NC} under the ${YELLOW}mqtt:${NC} section"
echo ""
echo -e "    ${CYAN}2.${NC} Add automations to your HA:"
echo -e "       Copy contents of: ${YELLOW}$OUTPUT_DIR/ha-frigate-ai-automation.yaml${NC}"
echo -e "       Into your HA ${YELLOW}automations.yaml${NC}"
echo ""
echo -e "    ${CYAN}3.${NC} Restart Home Assistant or reload YAML configs"
echo ""
echo -e "  ${BOLD}Useful Commands:${NC}"
echo ""
echo -e "    ${CYAN}View bridge logs:${NC}"
echo -e "      journalctl --user -u frigate-openclaw-bridge.service -f"
echo ""
echo -e "    ${CYAN}Restart bridge:${NC}"
echo -e "      systemctl --user restart frigate-openclaw-bridge.service"
echo ""
echo -e "    ${CYAN}Test:${NC}"
echo -e "      Walk in front of a camera and watch the logs!"
echo ""
echo -e "  ${BOLD}MQTT Payload (published to openclaw/frigate/analysis):${NC}"
echo -e "    camera, label, analysis, risk, tts, timestamp, event_id, snapshot_path"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
