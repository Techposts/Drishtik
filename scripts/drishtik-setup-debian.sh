#!/usr/bin/env bash
# =============================================================================
# Drishtik AI Security System — Debian Server Setup
# =============================================================================
# Sets up the complete AI security pipeline on Debian 12.
#
# Usage:
#   git clone https://github.com/techposts/drishtik.git ~/frigate
#   cd ~/frigate
#   bash scripts/drishtik-setup-debian.sh
#
# The script uses files from the cloned repo. If run standalone, it will
# clone the repo first.
#
# Home Assistant is OPTIONAL — the system works standalone with WhatsApp.
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
        while [[ -z "$input" ]]; do
            echo -ne "  ${RED}!${NC}  This field is required: "
            read -r input
        done
        printf -v "$varname" '%s' "$input"
    fi
}

ask_password() {
    local prompt="$1" default="$2" varname="$3"
    if [[ -n "$default" ]]; then
        echo -ne "  ${GREEN}?${NC}  ${prompt} ${YELLOW}[${default}]${NC}: "
        read -rs input; echo ""
        printf -v "$varname" '%s' "${input:-$default}"
    else
        echo -ne "  ${GREEN}?${NC}  ${prompt}: "
        read -rs input; echo ""
        while [[ -z "$input" ]]; do
            echo -ne "  ${RED}!${NC}  Password is required: "
            read -rs input; echo ""
        done
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
REPO_URL="https://github.com/techposts/drishtik.git"

# ---------------------------------------------------------------------------
# Detect repo context — are we running from inside a clone?
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT=""

# Check if we're in a git repo with the right files
for candidate in "$SCRIPT_DIR/.." "$SCRIPT_DIR" "$(pwd)" "$(pwd)/.."; do
    if [[ -f "$candidate/frigate-openclaw-bridge.py" || -f "$candidate/scripts/drishtik-setup-debian.sh" ]]; then
        REPO_ROOT="$(cd "$candidate" && pwd)"
        break
    fi
done

# ---------------------------------------------------------------------------
# Welcome
# ---------------------------------------------------------------------------
banner "Drishtik AI Security System — Debian Server Setup"
echo ""
echo -e "  This script sets up the complete AI security pipeline:"
echo ""
echo -e "    ${CYAN}1.${NC}  Gather your network & camera info"
echo -e "    ${CYAN}2.${NC}  Install system packages (Docker, Coral, Python, Node.js)"
echo -e "    ${CYAN}3.${NC}  Install & configure Mosquitto MQTT broker"
echo -e "    ${CYAN}4.${NC}  Deploy Frigate NVR with your cameras"
echo -e "    ${CYAN}5.${NC}  Install OpenClaw gateway + AI skill"
echo -e "    ${CYAN}6.${NC}  Deploy Bridge + Control Panel + systemd services"
echo ""
echo -e "  ${YELLOW}Home Assistant is optional${NC} — system works with just WhatsApp."
echo -e "  ${YELLOW}Ollama (AI model)${NC} — run ${BOLD}drishtik-setup-ollama.sh${NC} on your AI machine first."
echo ""

if [[ -n "$REPO_ROOT" ]]; then
    success "Running from cloned repo: $REPO_ROOT"
else
    info "Not running from a repo clone — will clone from GitHub during setup."
fi

# OS check
if [[ ! -f /etc/debian_version ]]; then
    fail "This script is for Debian/Ubuntu only (detected: $(uname -s))"
    exit 1
fi
success "Debian $(cat /etc/debian_version) detected"

ask_yn "Ready to begin?" "Y" READY
[[ "$READY" != "yes" ]] && echo "  Cancelled." && exit 0

# ═══════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT — Install essential prerequisites
# ═══════════════════════════════════════════════════════════════════════════
banner "Pre-Flight — Installing Prerequisites"

PREREQS_NEEDED=()
for cmd in curl git jq; do
    if ! command -v "$cmd" &>/dev/null; then
        PREREQS_NEEDED+=("$cmd")
    fi
done

if [[ ${#PREREQS_NEEDED[@]} -gt 0 ]]; then
    info "Installing: ${PREREQS_NEEDED[*]}..."
    sudo apt update -qq
    sudo apt install -y -qq "${PREREQS_NEEDED[@]}" > /dev/null 2>&1
    for cmd in "${PREREQS_NEEDED[@]}"; do
        if command -v "$cmd" &>/dev/null; then
            success "$cmd installed"
        else
            fail "$cmd failed to install"
            exit 1
        fi
    done
else
    success "All prerequisites already installed (curl, git, jq)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — GATHER ALL USER INPUTS
# ═══════════════════════════════════════════════════════════════════════════
banner "Step 1 — Your Server"

SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")

ask "This server's LAN IP address" "$SERVER_IP" SERVER_IP
ask "Where to install Drishtik" "$HOME/frigate" PROJECT_DIR
LINUX_USER="$(whoami)"
info "Running as user: $LINUX_USER"

# ---------------------------------------------------------------------------
banner "Step 2 — Your Cameras"

echo ""
info "Enter your camera RTSP URLs. One per line."
info "Format:  CameraName=rtsp://user:pass@IP:554/stream"
info "Example: GarageCam=rtsp://admin:mypass@192.168.0.235:554/stream1/1"
echo ""
info "The RTSP URL includes the camera's username and password."
info "Check your camera manual or app if you don't know the URL."
echo ""

declare -A CAMERAS=()
CAM_ORDER=()
while true; do
    echo -ne "  ${GREEN}+${NC}  Camera (blank line when done): "
    read -r cam_input
    [[ -z "$cam_input" ]] && break
    cam_name="${cam_input%%=*}"
    cam_url="${cam_input#*=}"
    if [[ -z "$cam_name" || -z "$cam_url" || "$cam_name" == "$cam_url" ]]; then
        warn "Format must be: CameraName=rtsp://... — try again"
        continue
    fi
    CAMERAS["$cam_name"]="$cam_url"
    CAM_ORDER+=("$cam_name")
    success "Added: $cam_name → $cam_url"
done

if [[ ${#CAM_ORDER[@]} -eq 0 ]]; then
    fail "You need at least one camera. Re-run the script when you have RTSP URLs ready."
    exit 1
fi

echo ""
ask "Coral TPU type — pci (Mini PCIe) or usb" "pci" CORAL_TYPE

# ---------------------------------------------------------------------------
banner "Step 3 — MQTT Broker"

info "Mosquitto MQTT will be installed on this server."
info "Pick a username and password — all services use these to communicate."
echo ""
ask "MQTT username" "mqtt-user" MQTT_USER
ask_password "MQTT password (choose a new one)" "" MQTT_PASS
ask "MQTT port" "1883" MQTT_PORT

# ---------------------------------------------------------------------------
banner "Step 4 — Ollama (AI Model)"

info "Ollama runs the vision AI model on a separate machine."
info "You should have already run drishtik-setup-ollama.sh on that machine."
echo ""
ask "Ollama machine's LAN IP address" "" OLLAMA_IP
ask "Ollama port" "11434" OLLAMA_PORT
OLLAMA_URL="http://${OLLAMA_IP}:${OLLAMA_PORT}"
ask "Vision model name" "qwen2.5vl:7b" AI_MODEL

echo ""
info "Testing Ollama reachability..."
if curl -sf --connect-timeout 5 "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
    success "Ollama is reachable at $OLLAMA_URL"
else
    warn "Cannot reach Ollama at $OLLAMA_URL — make sure it's running and LAN-accessible"
    ask_yn "Continue anyway?" "Y" CONTINUE_OLLAMA
    [[ "$CONTINUE_OLLAMA" != "yes" ]] && echo "  Run drishtik-setup-ollama.sh on the AI machine first." && exit 0
fi

# ---------------------------------------------------------------------------
banner "Step 5 — WhatsApp Alerts"

echo ""
info "WhatsApp numbers that will receive security alerts."
info "Include country code (e.g. +919958040437)."
info "At least one number is recommended."
echo ""

WHATSAPP_NUMBERS=()
info "Enter one number per line, or comma-separated (e.g. +91xxx,+1xxx)."
echo ""
while true; do
    echo -ne "  ${GREEN}+${NC}  WhatsApp number (blank line when done): "
    read -r num_input
    [[ -z "$num_input" ]] && break
    # Split comma-separated numbers
    IFS=',' read -ra nums <<< "$num_input"
    for num in "${nums[@]}"; do
        num="$(echo "$num" | tr -d ' ')"  # trim spaces
        [[ -z "$num" ]] && continue
        [[ "$num" != +* ]] && num="+$num"
        WHATSAPP_NUMBERS+=("$num")
        success "Added: $num"
    done
done

if [[ ${#WHATSAPP_NUMBERS[@]} -eq 0 ]]; then
    warn "No WhatsApp numbers — you can add them later in the Control Panel."
fi

# ---------------------------------------------------------------------------
banner "Step 6 — Home Assistant (Optional)"

echo ""
info "Home Assistant adds: Alexa announcements, mobile push, dashboard."
info "The system works without it — WhatsApp + lights still work via the bridge."
echo ""
ask_yn "Do you have Home Assistant set up?" "N" HAS_HA
HA_URL=""
HA_TOKEN=""
if [[ "$HAS_HA" == "yes" ]]; then
    ask "Home Assistant URL" "" HA_URL
    echo ""
    info "You need a Long-Lived Access Token from HA."
    info "Get it: HA → Profile → Long-Lived Access Tokens → Create Token"
    info "Or press Enter to set it later via the Control Panel UI."
    echo ""
    ask "HA Long-Lived Access Token (Enter to skip)" "" HA_TOKEN
    [[ -z "$HA_TOKEN" ]] && HA_TOKEN="REPLACE_WITH_HA_LONG_LIVED_TOKEN"
fi

# ═══════════════════════════════════════════════════════════════════════════
# REVIEW EVERYTHING
# ═══════════════════════════════════════════════════════════════════════════
banner "Review — Confirm Before Installing"

echo ""
echo -e "  ${BOLD}Server${NC}"
echo -e "    IP:             $SERVER_IP"
echo -e "    Install path:   $PROJECT_DIR"
echo -e "    User:           $LINUX_USER"
echo ""
echo -e "  ${BOLD}Cameras (${#CAM_ORDER[@]})${NC}"
for cam in "${CAM_ORDER[@]}"; do
    echo -e "    $cam → ${CAMERAS[$cam]}"
done
echo -e "    Coral TPU:      $CORAL_TYPE"
echo ""
echo -e "  ${BOLD}MQTT Broker${NC}"
echo -e "    ${MQTT_USER}@${SERVER_IP}:${MQTT_PORT}"
echo ""
echo -e "  ${BOLD}Ollama AI${NC}"
echo -e "    $OLLAMA_URL ($AI_MODEL)"
echo ""
echo -e "  ${BOLD}WhatsApp${NC}"
if [[ ${#WHATSAPP_NUMBERS[@]} -gt 0 ]]; then
    for n in "${WHATSAPP_NUMBERS[@]}"; do echo -e "    $n"; done
else
    echo -e "    (none — configure later in Control Panel)"
fi
echo ""
echo -e "  ${BOLD}Home Assistant${NC}"
if [[ "$HAS_HA" == "yes" ]]; then
    echo -e "    $HA_URL"
else
    echo -e "    Not configured (optional)"
fi
echo ""

ask_yn "Everything correct? Proceed with installation?" "Y" PROCEED
[[ "$PROCEED" != "yes" ]] && echo "  Cancelled." && exit 0

# ═══════════════════════════════════════════════════════════════════════════
# INSTALL — SYSTEM PACKAGES
# ═══════════════════════════════════════════════════════════════════════════
banner "Installing — System Packages"

# Remove broken Coral repo entry if present (prevents apt update errors)
if [[ -f /etc/apt/sources.list.d/coral-edgetpu.list ]]; then
    # Check if it's the old unsigned version
    if ! grep -q "signed-by" /etc/apt/sources.list.d/coral-edgetpu.list 2>/dev/null; then
        info "Removing old unsigned Coral TPU repo entry..."
        sudo rm -f /etc/apt/sources.list.d/coral-edgetpu.list
    fi
fi

info "Updating package lists..."
sudo apt update -qq 2>/dev/null

info "Installing base packages..."
sudo apt install -y -qq ca-certificates curl gnupg git python3 python3-venv python3-full \
    mosquitto mosquitto-clients jq > /dev/null 2>&1
success "Base packages installed"

# ── Docker ──
if command -v docker &>/dev/null; then
    success "Docker already installed: $(docker --version 2>&1 | head -1)"
else
    info "Installing Docker..."
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt update -qq 2>/dev/null
    sudo apt install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin > /dev/null 2>&1
fi
# Ensure current user is in docker group
if ! groups "$LINUX_USER" 2>/dev/null | grep -qw docker; then
    sudo usermod -aG docker "$LINUX_USER"
    info "Added $LINUX_USER to docker group"
fi
success "Docker ready: $(docker --version 2>&1 | head -1)"

# ── Coral TPU driver ──
CORAL_READY=no
if [[ -e /dev/apex_0 ]]; then
    success "Coral PCIe TPU detected at /dev/apex_0"
    CORAL_READY=yes
elif lsusb 2>/dev/null | grep -qi "google.*coral\|1a6e:089a\|18d1:9302"; then
    success "Coral USB TPU detected"
    CORAL_READY=yes
fi

if [[ "$CORAL_READY" == "no" ]]; then
    # Check if PCIe Coral hardware is present but driver not loaded
    CORAL_PCI_PRESENT=no
    if lspci 2>/dev/null | grep -qi "coral\|global unichip\|089a"; then
        CORAL_PCI_PRESENT=yes
        info "Coral PCIe hardware detected — installing drivers..."
    else
        info "Installing Coral Edge TPU runtime..."
    fi

    # Add Coral repo with proper signing
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
        | sudo gpg --yes --dearmor -o /etc/apt/keyrings/coral-edgetpu.gpg 2>/dev/null || true
    echo "deb [signed-by=/etc/apt/keyrings/coral-edgetpu.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main" \
        | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list > /dev/null
    sudo apt update -qq 2>/dev/null

    # Install Edge TPU runtime
    if sudo apt install -y -qq libedgetpu1-std 2>/dev/null; then
        success "Edge TPU runtime installed"
    else
        warn "Could not install Edge TPU runtime — install manually: https://coral.ai/docs/accelerator/get-started/"
    fi

    # For PCIe Coral: need gasket/apex kernel driver to create /dev/apex_0
    if [[ "$CORAL_PCI_PRESENT" == "yes" || "$CORAL_TYPE" == "pci" ]]; then
        info "Installing PCIe Coral kernel driver..."
        sudo apt install -y -qq linux-headers-$(uname -r) dkms 2>/dev/null || true

        # Build gasket driver from Google's upstream source
        # The packaged gasket-dkms is broken on kernel 6.x+ (API changes)
        info "Building gasket driver from source (kernel $(uname -r))..."
        sudo rm -rf /tmp/gasket-driver
        if git clone --quiet https://github.com/google/gasket-driver.git /tmp/gasket-driver 2>/dev/null; then
            cd /tmp/gasket-driver

            # Patch for kernel 6.x compatibility: no_llseek was removed
            sudo sed -i 's/no_llseek/noop_llseek/g' src/gasket_core.c

            # Build
            if sudo make -C "/lib/modules/$(uname -r)/build" M="$(pwd)/src" modules 2>/dev/null; then
                sudo make -C "/lib/modules/$(uname -r)/build" M="$(pwd)/src" modules_install 2>/dev/null
                sudo depmod -a 2>/dev/null
                success "Gasket driver built and installed"
            else
                warn "Gasket driver build failed — check kernel headers"
            fi
            cd - > /dev/null
        else
            warn "Could not clone gasket driver repo"
        fi

        # Set up udev rules for apex device
        if [[ ! -f /etc/udev/rules.d/65-apex.rules ]]; then
            echo 'SUBSYSTEM=="apex", MODE="0660", GROUP="apex"' | sudo tee /etc/udev/rules.d/65-apex.rules > /dev/null
        fi
        sudo groupadd -f apex 2>/dev/null || true
        sudo usermod -aG apex "$LINUX_USER" 2>/dev/null || true

        # Load the modules
        sudo modprobe gasket 2>/dev/null || true
        sudo modprobe apex 2>/dev/null || true
        sudo udevadm control --reload-rules 2>/dev/null || true
        sudo udevadm trigger 2>/dev/null || true
        sleep 2

        if [[ -e /dev/apex_0 ]]; then
            success "Coral PCIe ready at /dev/apex_0"
            CORAL_READY=yes
        else
            warn "Coral PCIe driver installed but /dev/apex_0 not yet available"
            warn "A reboot may be required — run: sudo reboot"
            warn "After reboot, re-run this script or just start Frigate"
        fi
    fi
fi

# ── Node.js + npm ──
NODE_OK=no
# OpenClaw requires Node >= 22.12.0
NODE_MAJOR=$(node --version 2>/dev/null | sed 's/v\([0-9]*\).*/\1/' || echo "0")
if [[ "$NODE_MAJOR" -ge 22 ]] && command -v npm &>/dev/null; then
    success "Node.js already installed: $(node --version), npm: $(npm --version)"
    NODE_OK=yes
else
    [[ "$NODE_MAJOR" -gt 0 ]] && info "Node.js $(node --version) found but OpenClaw needs >= 22.x — upgrading..."
    info "Installing Node.js 22.x (required by OpenClaw)..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - > /dev/null 2>&1
    sudo apt install -y -qq nodejs > /dev/null 2>&1
    if command -v node &>/dev/null && command -v npm &>/dev/null; then
        success "Node.js installed: $(node --version), npm: $(npm --version)"
        NODE_OK=yes
    else
        warn "Node.js/npm install had issues — OpenClaw gateway may not work"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════
# INSTALL — PROJECT FILES
# ═══════════════════════════════════════════════════════════════════════════
banner "Installing — Project Files"

mkdir -p "$PROJECT_DIR/storage"/{ai-snapshots,ai-clips,clips,recordings}

# If we're not already in a repo clone, clone now
if [[ -z "$REPO_ROOT" ]]; then
    info "Cloning Drishtik repository..."
    if git clone --quiet "$REPO_URL" "/tmp/drishtik-$$" 2>/dev/null; then
        REPO_ROOT="/tmp/drishtik-$$"
        success "Repository cloned"
    else
        warn "Could not clone repo — will download files individually"
    fi
fi

# Copy core scripts from repo to project dir
CORE_FILES=(frigate-openclaw-bridge.py frigate-control-panel.py phase8-summary.py ha-frigate-ai-automation.yaml)
for f in "${CORE_FILES[@]}"; do
    src=""
    if [[ -n "$REPO_ROOT" ]]; then
        for dir in "$REPO_ROOT" "$REPO_ROOT/scripts" "$REPO_ROOT/config"; do
            [[ -f "$dir/$f" ]] && src="$dir/$f" && break
        done
    fi
    if [[ -n "$src" && -f "$src" ]]; then
        cp "$src" "$PROJECT_DIR/$f"
        # Replace <HOME_USER> placeholder with actual username
        if [[ "$f" == *.py ]]; then
            sed -i "s|<HOME_USER>|${LINUX_USER}|g" "$PROJECT_DIR/$f"
        fi
        success "Deployed $f"
    elif [[ -n "$REPO_ROOT" ]]; then
        warn "$f not found in repo — download from GitHub manually"
    else
        # Try direct download as fallback
        if curl -fsSL "https://raw.githubusercontent.com/techposts/drishtik/main/$f" -o "$PROJECT_DIR/$f" 2>/dev/null; then
            if [[ "$f" == *.py ]]; then
                sed -i "s|<HOME_USER>|${LINUX_USER}|g" "$PROJECT_DIR/$f"
            fi
            success "Downloaded $f"
        else
            warn "Could not get $f — download from GitHub: $REPO_URL"
            ERRORS=$((ERRORS + 1))
        fi
    fi
done

# ═══════════════════════════════════════════════════════════════════════════
# INSTALL — MOSQUITTO MQTT
# ═══════════════════════════════════════════════════════════════════════════
banner "Installing — MQTT Broker"

info "Configuring Mosquitto..."
sudo tee /etc/mosquitto/conf.d/drishtik.conf > /dev/null << EOF
# Drishtik AI Security — Mosquitto config
listener ${MQTT_PORT}
allow_anonymous false
password_file /etc/mosquitto/passwd_drishtik
EOF

sudo mosquitto_passwd -b -c /etc/mosquitto/passwd_drishtik "$MQTT_USER" "$MQTT_PASS" 2>/dev/null
sudo chown mosquitto:mosquitto /etc/mosquitto/passwd_drishtik
sudo chmod 640 /etc/mosquitto/passwd_drishtik
sudo systemctl restart mosquitto
sudo systemctl enable mosquitto > /dev/null 2>&1
sleep 1

if mosquitto_pub -h 127.0.0.1 -p "$MQTT_PORT" -u "$MQTT_USER" -P "$MQTT_PASS" -t "drishtik/test" -m "ok" 2>/dev/null; then
    success "Mosquitto MQTT running and verified on port $MQTT_PORT"
else
    warn "Mosquitto may not be responding — check: sudo systemctl status mosquitto"
    ERRORS=$((ERRORS + 1))
fi

# ═══════════════════════════════════════════════════════════════════════════
# INSTALL — FRIGATE NVR
# ═══════════════════════════════════════════════════════════════════════════
banner "Installing — Frigate NVR"

# Build cameras YAML from user input
CAMERAS_YAML=""
for cam in "${CAM_ORDER[@]}"; do
    CAMERAS_YAML+="
  ${cam}:
    enabled: true
    ffmpeg:
      inputs:
        - path: ${CAMERAS[$cam]}
          roles: [detect, record]
    detect:
      width: 1280
      height: 720
      fps: 5
    motion:
      threshold: 25
    snapshots:
      enabled: true
    record:
      enabled: true
      retain:
        days: 3
      events:
        retain:
          default: 7"
done

info "Generating config.yml with your ${#CAM_ORDER[@]} camera(s)..."
cat > "$PROJECT_DIR/config.yml" << EOF
# Drishtik — Frigate NVR Config (auto-generated)

detectors:
  coral:
    type: edgetpu
    device: ${CORAL_TYPE}

mqtt:
  enabled: true
  topic_prefix: frigate
  host: ${SERVER_IP}
  port: ${MQTT_PORT}
  user: ${MQTT_USER}
  password: "${MQTT_PASS}"

objects:
  track:
    - person
    - cat
    - dog

record:
  enabled: true
  retain:
    days: 3

snapshots:
  enabled: true
  retain:
    default: 7

cameras:${CAMERAS_YAML}
EOF
success "config.yml created with ${#CAM_ORDER[@]} camera(s)"

info "Generating docker-compose.yml..."

# Build device line — only add if device actually exists
DEVICE_SECTION=""
if [[ "$CORAL_TYPE" == "pci" && -e /dev/apex_0 ]]; then
    DEVICE_SECTION="    devices:
      - /dev/apex_0:/dev/apex_0"
elif [[ "$CORAL_TYPE" == "usb" ]]; then
    DEVICE_SECTION="    devices:
      - /dev/bus/usb:/dev/bus/usb"
else
    warn "Coral TPU device not available — Frigate will use CPU detection (slower)"
    warn "After reboot (if Coral PCIe), re-run or manually add device to docker-compose.yml"
    # Switch config.yml to CPU detector if Coral not ready
    info "Configuring Frigate for CPU detection as fallback..."
fi

# If Coral is not ready, update config.yml to use cpu detector
if [[ -z "$DEVICE_SECTION" ]]; then
    cat > "$PROJECT_DIR/config.yml" << EOF
# Drishtik — Frigate NVR Config (auto-generated)
# NOTE: Using CPU detector — switch to edgetpu after Coral is available

detectors:
  cpu:
    type: cpu
    num_threads: 4

mqtt:
  enabled: true
  topic_prefix: frigate
  host: ${SERVER_IP}
  port: ${MQTT_PORT}
  user: ${MQTT_USER}
  password: "${MQTT_PASS}"

objects:
  track:
    - person
    - cat
    - dog

record:
  enabled: true
  retain:
    days: 3

snapshots:
  enabled: true
  retain:
    default: 7

cameras:${CAMERAS_YAML}
EOF
    success "config.yml updated with CPU detector (switch to Coral after reboot)"
fi

cat > "$PROJECT_DIR/docker-compose.yml" << EOF
# Drishtik — Docker Compose (auto-generated)
services:
  frigate:
    container_name: frigate
    image: ghcr.io/blakeblackshear/frigate:0.15.1
    restart: unless-stopped
    privileged: true
    shm_size: "256mb"
${DEVICE_SECTION}
    volumes:
      - ${PROJECT_DIR}/config.yml:/config/config.yml
      - ${PROJECT_DIR}/storage:/media/frigate
      - type: tmpfs
        target: /tmp/cache
        tmpfs:
          size: 1000000000
    ports:
      - "5000:5000"
      - "8554:8554"
      - "8555:8555/tcp"
      - "8555:8555/udp"
EOF
success "docker-compose.yml created"

info "Starting Frigate container (this pulls the image on first run — may take a few minutes)..."
cd "$PROJECT_DIR"
# Use sg to pick up docker group without requiring logout, fall back to sudo
if sg docker -c "docker compose up -d" 2>/dev/null || sudo docker compose up -d 2>/dev/null; then
    info "Waiting for Frigate to become healthy..."
    FRIGATE_OK=no
    for i in $(seq 1 12); do
        sleep 5
        HEALTH=$(sudo docker inspect frigate --format='{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
        if [[ "$HEALTH" == "healthy" ]]; then
            FRIGATE_OK=yes
            break
        elif [[ "$HEALTH" == "unhealthy" ]]; then
            break
        fi
        echo -ne "  ${BLUE}ℹ${NC}  Frigate: $HEALTH ($((i*5))s)...\r"
    done
    echo ""
    if [[ "$FRIGATE_OK" == "yes" ]]; then
        success "Frigate running and healthy — UI at http://${SERVER_IP}:5000"
    else
        # Check if it's a config validation error causing restart loop
        CONFIG_ERR=$(sudo docker logs frigate 2>&1 | grep -c "Config Validation Errors" || true)
        if [[ "$CONFIG_ERR" -gt 0 ]]; then
            fail "Frigate has config validation errors — check: sudo docker logs frigate | grep -A5 'Config Validation'"
            ERRORS=$((ERRORS + 1))
        else
            warn "Frigate container started but may still be initializing — check: sudo docker logs frigate"
        fi
    fi
else
    warn "Could not start Frigate — if Docker group issue, log out/in and run: cd $PROJECT_DIR && docker compose up -d"
    ERRORS=$((ERRORS + 1))
fi

# ═══════════════════════════════════════════════════════════════════════════
# INSTALL — OPENCLAW
# ═══════════════════════════════════════════════════════════════════════════
banner "Installing — OpenClaw Gateway"

# Ensure npm is available
if ! command -v npm &>/dev/null; then
    warn "npm not found — cannot install OpenClaw"
    warn "Fix: sudo apt install -y npm && then re-run this script"
    ERRORS=$((ERRORS + 1))
else
    # Set up npm global directory (avoids needing sudo for npm -g)
    mkdir -p "$HOME/.npm-global"
    npm config set prefix "$HOME/.npm-global" 2>/dev/null || true
    export PATH="$HOME/.npm-global/bin:$PATH"

    if command -v openclaw &>/dev/null || [[ -f "$HOME/.npm-global/bin/openclaw" ]]; then
        success "OpenClaw already installed"
    else
        info "Installing OpenClaw (this may take a minute)..."
        if npm install -g openclaw 2>&1 | tail -3; then
            if [[ -f "$HOME/.npm-global/bin/openclaw" ]]; then
                success "OpenClaw installed"
            else
                warn "OpenClaw binary not found after install"
                ERRORS=$((ERRORS + 1))
            fi
        else
            warn "OpenClaw npm install failed"
            ERRORS=$((ERRORS + 1))
        fi
    fi

    # Add to PATH permanently
    if ! grep -q '.npm-global/bin' "$HOME/.bashrc" 2>/dev/null; then
        echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$HOME/.bashrc"
        info "Added ~/.npm-global/bin to PATH in .bashrc"
    fi
fi

# Workspace + skill
mkdir -p "$HOME/.openclaw/workspace/skills/frigate"
mkdir -p "$HOME/.openclaw/workspace/ai-snapshots"
mkdir -p "$HOME/.openclaw/workspace/ai-clips"

# Generate webhook token
WEBHOOK_TOKEN=$(head -c 16 /dev/urandom 2>/dev/null | xxd -p 2>/dev/null || echo "frigate-hook-$(date +%s)")

# Build WhatsApp JSON arrays
WA_JSON="["
WA_RECIPIENTS_JSON="["
if [[ ${#WHATSAPP_NUMBERS[@]} -gt 0 ]]; then
    for i in "${!WHATSAPP_NUMBERS[@]}"; do
        [[ $i -gt 0 ]] && WA_JSON+="," && WA_RECIPIENTS_JSON+=","
        WA_JSON+="\"${WHATSAPP_NUMBERS[$i]}\""
        WA_RECIPIENTS_JSON+="\"${WHATSAPP_NUMBERS[$i]}\""
    done
fi
WA_JSON+="]"
WA_RECIPIENTS_JSON+="]"

# openclaw.json
if [[ -f "$HOME/.openclaw/openclaw.json" ]]; then
    info "openclaw.json already exists — preserving"
    WEBHOOK_TOKEN=$(python3 -c "import json; print(json.load(open('$HOME/.openclaw/openclaw.json')).get('hooks',{}).get('token','$WEBHOOK_TOKEN'))" 2>/dev/null || echo "$WEBHOOK_TOKEN")
else
    info "Creating openclaw.json..."
    cat > "$HOME/.openclaw/openclaw.json" << EOF
{
  "hooks": {
    "enabled": true,
    "token": "${WEBHOOK_TOKEN}",
    "path": "/hooks",
    "allowRequestSessionKey": true
  },
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "${OLLAMA_URL}",
        "models": [{"id": "${AI_MODEL}", "name": "${AI_MODEL}"}]
      }
    }
  },
  "channels": {
    "whatsapp": {
      "dmPolicy": "pairing",
      "allowFrom": ${WA_JSON},
      "groupPolicy": "allowlist"
    }
  },
  "gateway": {
    "port": 18789,
    "mode": "local"
  },
  "plugins": {
    "entries": {
      "whatsapp": { "enabled": true }
    }
  }
}
EOF
    success "openclaw.json created"
fi

# Fix permissions and run doctor
chmod 700 "$HOME/.openclaw" 2>/dev/null || true
chmod 600 "$HOME/.openclaw/openclaw.json" 2>/dev/null || true
mkdir -p "$HOME/.openclaw/agents/main/sessions" "$HOME/.openclaw/credentials" 2>/dev/null

# Run doctor --fix if openclaw is available
if [[ -f "$HOME/.npm-global/bin/openclaw" ]]; then
    info "Running openclaw doctor --fix..."
    PATH="$HOME/.npm-global/bin:$PATH" openclaw doctor --fix > /dev/null 2>&1 || true
    success "OpenClaw config validated"
fi

# Deploy SKILL.md — check repo first, then create
SKILL_SRC=""
if [[ -n "$REPO_ROOT" ]]; then
    for p in "$REPO_ROOT/skills/frigate/SKILL.md" "$REPO_ROOT/config/SKILL.md" "$REPO_ROOT/SKILL.md"; do
        [[ -f "$p" ]] && SKILL_SRC="$p" && break
    done
fi
SKILL_DEST="$HOME/.openclaw/workspace/skills/frigate/SKILL.md"

if [[ -n "$SKILL_SRC" ]]; then
    cp "$SKILL_SRC" "$SKILL_DEST"
    success "SKILL.md deployed from repo"
elif [[ -f "$SKILL_DEST" ]]; then
    success "SKILL.md already exists"
else
    cat > "$SKILL_DEST" << 'SKILL_EOF'
# Frigate Security Camera Analysis

You are acting as a security camera AI analyst for a home security system.

## TWO MODES OF OPERATION

### Mode 1: ANALYSIS (when message contains "Security alert from camera" or snapshot path)

1. **Open the snapshot** using the `image` tool with the file path provided.
2. **Analyze** for security-relevant details.
3. **Respond** with structured assessment.

#### What to Look For
- **People**: Count, clothing, build, distinguishing features
- **Activity**: Walking, standing, reaching, carrying items
- **Location context**: Match to camera name
- **Time context**: Day or night based on lighting
- **Threat indicators**: Unfamiliar person, unusual hour, suspicious behavior

#### Response Format
```
MEDIA:<path>

[CAMERA] Threat: LOW/MEDIUM/HIGH/CRITICAL
3-5 sentence security assessment.

JSON: {"risk":"low|medium|high|critical","type":"unknown_person|known_person|delivery|vehicle|animal|loitering|other","confidence":0.00,"action":"notify_only|notify_and_save_clip|notify_and_light|notify_and_alarm","reason":"short explanation"}
```

### Mode 2: DELIVERY (message starts with "MEDIA:" or has formatted alert)

**Forward the message EXACTLY as provided.** Do not rewrite, summarize, or modify.
Preserve all line breaks, bold markers, emoji, bullet points, and MEDIA: lines.
SKILL_EOF
    success "SKILL.md created"
fi

# ═══════════════════════════════════════════════════════════════════════════
# INSTALL — BRIDGE + CONTROL PANEL
# ═══════════════════════════════════════════════════════════════════════════
banner "Installing — Bridge + Control Panel"

VENV_DIR="$PROJECT_DIR/bridge-venv"

info "Setting up Python virtual environment..."
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip 2>/dev/null
"$VENV_DIR/bin/pip" install --quiet paho-mqtt==2.1.0 requests==2.32.5 2>/dev/null
success "Python venv ready (paho-mqtt + requests)"

# Generate bridge-runtime-config.json
info "Generating bridge-runtime-config.json..."

# Build per-camera JSON objects
ZONE_LIGHTS="{"
ZONE_NOTES="{"
ZONE_POLICY="{"
for i in "${!CAM_ORDER[@]}"; do
    cam="${CAM_ORDER[$i]}"
    [[ $i -gt 0 ]] && ZONE_LIGHTS+="," && ZONE_NOTES+="," && ZONE_POLICY+=","
    ZONE_LIGHTS+="\"${cam}\":[\"light.${cam,,}\"]"
    ZONE_NOTES+="\"${cam}\":\"Update this in Control Panel — describe what this camera sees\""
    ZONE_POLICY+="\"${cam}\":\"zone-${cam,,}\""
done
ZONE_LIGHTS+="}"; ZONE_NOTES+="}"; ZONE_POLICY+="}"

AUDIT_KEY=$(head -c 16 /dev/urandom 2>/dev/null | xxd -p 2>/dev/null || echo "change-me-audit-key")

cat > "$PROJECT_DIR/bridge-runtime-config.json" << EOF
{
  "mqtt_host": "${SERVER_IP}",
  "mqtt_port": ${MQTT_PORT},
  "mqtt_user": "${MQTT_USER}",
  "mqtt_pass": "${MQTT_PASS}",
  "mqtt_topic_subscribe": "frigate/events",
  "mqtt_topic_publish": "openclaw/frigate/analysis",
  "frigate_api": "http://localhost:5000",
  "openclaw_analysis_webhook": "http://127.0.0.1:18789/hooks/agent",
  "openclaw_delivery_webhook": "http://127.0.0.1:18789/hooks/agent",
  "openclaw_token": "${WEBHOOK_TOKEN}",
  "openclaw_analysis_agent_name": "main",
  "openclaw_delivery_agent_name": "main",
  "openclaw_analysis_model": "litellm/${AI_MODEL}",
  "openclaw_analysis_model_fallback": "openai/gpt-4o-mini",
  "openclaw_analysis_webhook_fallback": "http://127.0.0.1:18789/hooks/agent",
  "ollama_api": "${OLLAMA_URL}",
  "ollama_model": "${AI_MODEL}",
  "whatsapp_to": ${WA_RECIPIENTS_JSON},
  "whatsapp_enabled": true,
  "cooldown_seconds": 30,
  "ha_url": "${HA_URL:-http://localhost:8123}",
  "ha_token": "${HA_TOKEN:-REPLACE_WITH_HA_LONG_LIVED_TOKEN}",
  "camera_zone_lights": ${ZONE_LIGHTS},
  "camera_zone_lights_default": ["light.default"],
  "alarm_entity": "switch.security_siren",
  "quiet_hours_start": 23,
  "quiet_hours_end": 6,
  "ha_home_mode_entity": "input_select.home_mode",
  "ha_known_faces_entity": "binary_sensor.known_faces_present",
  "exclude_known_faces": false,
  "camera_context_notes": ${ZONE_NOTES},
  "camera_policy_zones": ${ZONE_POLICY},
  "camera_policy_zone_default": "entry",
  "recent_events_window_seconds": 600,
  "event_history_file": "${PROJECT_DIR}/storage/events-history.jsonl",
  "event_history_window_seconds": 1800,
  "event_history_max_lines": 5000,
  "phase3_enabled": true,
  "phase4_enabled": true,
  "phase5_enabled": true,
  "phase8_enabled": true,
  "phase5_confirm_delay_seconds": 4,
  "phase5_confirm_timeout_seconds": 90,
  "phase5_confirm_risks": ["high", "critical"],
  "ui_auth_enabled": true,
  "ui_users": {
    "admin": {"password": "changeme-admin", "role": "admin"},
    "operator": {"password": "changeme-operator", "role": "operator"},
    "viewer": {"password": "changeme-viewer", "role": "viewer"}
  },
  "approval_required_high_impact": true,
  "audit_signing_key": "${AUDIT_KEY}",
  "cluster_node_id": "node-1",
  "cluster_peers": []
}
EOF
success "bridge-runtime-config.json created"

# ═══════════════════════════════════════════════════════════════════════════
# INSTALL — SYSTEMD SERVICES
# ═══════════════════════════════════════════════════════════════════════════
banner "Installing — Systemd Services"

SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

NODE_BIN="$(command -v node 2>/dev/null || echo "/usr/bin/node")"

# Find OpenClaw's JS entry point
OPENCLAW_JS=""
for p in "$HOME/.npm-global/lib/node_modules/openclaw/dist/index.js" \
         "/usr/lib/node_modules/openclaw/dist/index.js" \
         "/usr/local/lib/node_modules/openclaw/dist/index.js"; do
    [[ -f "$p" ]] && OPENCLAW_JS="$p" && break
done

if [[ -z "$OPENCLAW_JS" ]]; then
    warn "Could not find OpenClaw JS entry — gateway service may need manual fix"
    OPENCLAW_JS="/usr/lib/node_modules/openclaw/dist/index.js"
fi

# ── OpenClaw Gateway ──
info "Creating openclaw-gateway.service..."
cat > "$SYSTEMD_DIR/openclaw-gateway.service" << EOF
[Unit]
Description=OpenClaw Gateway
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${NODE_BIN} ${OPENCLAW_JS} gateway --port 18789
Restart=always
RestartSec=5
KillMode=process
Environment="HOME=$HOME"
Environment="PATH=$HOME/.npm-global/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment=OPENCLAW_GATEWAY_PORT=18789
Environment=OPENCLAW_GATEWAY_TOKEN=${WEBHOOK_TOKEN}

[Install]
WantedBy=default.target
EOF

# ── Bridge ──
info "Creating frigate-openclaw-bridge.service..."
cat > "$SYSTEMD_DIR/frigate-openclaw-bridge.service" << EOF
[Unit]
Description=Drishtik AI Security Bridge
After=network-online.target openclaw-gateway.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_DIR}/bin/python3 ${PROJECT_DIR}/frigate-openclaw-bridge.py
Restart=always
RestartSec=10
KillMode=process
Environment="HOME=$HOME"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=default.target
EOF

# ── Control Panel ──
info "Creating frigate-control-panel.service..."
cat > "$SYSTEMD_DIR/frigate-control-panel.service" << EOF
[Unit]
Description=Drishtik Control Panel (Web UI)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_DIR}/bin/python3 ${PROJECT_DIR}/frigate-control-panel.py --host 0.0.0.0 --port 18777
Restart=always
RestartSec=5
Environment="HOME=$HOME"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=default.target
EOF

# ── Enable & start all services ──
info "Enabling and starting services..."
systemctl --user daemon-reload

for svc in openclaw-gateway frigate-openclaw-bridge frigate-control-panel; do
    systemctl --user enable "$svc.service" 2>/dev/null
    systemctl --user start "$svc.service" 2>/dev/null
    sleep 2
    if systemctl --user is-active "$svc.service" &>/dev/null; then
        success "$svc: running"
    else
        warn "$svc: not running — check: journalctl --user -u $svc.service -n 20"
        ERRORS=$((ERRORS + 1))
    fi
done

# Lingering — services survive logout
sudo loginctl enable-linger "$LINUX_USER" 2>/dev/null
success "Lingering enabled — services survive SSH logout"

# Clean up temp clone if we made one
if [[ "$REPO_ROOT" == /tmp/drishtik-* && -d "$REPO_ROOT" ]]; then
    rm -rf "$REPO_ROOT"
fi

# ═══════════════════════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════════════════════
banner "Setup Complete!"

if [[ $ERRORS -gt 0 ]]; then
    echo -e "  ${YELLOW}Completed with $ERRORS warning(s) — review messages above${NC}"
else
    echo -e "  ${GREEN}All steps completed successfully!${NC}"
fi

echo ""
echo -e "  ${BOLD}Services Running${NC}"
echo -e "    Frigate NVR:        ${BOLD}http://${SERVER_IP}:5000${NC}"
echo -e "    Control Panel:      ${BOLD}http://${SERVER_IP}:18777${NC}  (admin / changeme-admin)"
echo -e "    OpenClaw Gateway:   http://127.0.0.1:18789"
echo -e "    Mosquitto MQTT:     ${SERVER_IP}:${MQTT_PORT}"
echo ""
echo -e "  ${BOLD}Next Steps${NC}"
echo ""
echo -e "    ${CYAN}1.${NC} Connect WhatsApp (required for alerts):"
echo -e "       ${BOLD}bash ~/drishtik/scripts/drishtik-setup-openclaw.sh${NC}"
echo -e "       This links your WhatsApp via QR code and configures AI models."
echo ""
echo -e "    ${CYAN}2.${NC} Open the Control Panel in your browser:"
echo -e "       ${BOLD}http://${SERVER_IP}:18777${NC}"
echo -e "       Login: admin / changeme-admin"
echo -e "       Fine-tune camera context, light entities, run diagnostics."
echo ""
if [[ "$HAS_HA" == "yes" ]]; then
    echo -e "    ${CYAN}3.${NC} Import the HA automation:"
    echo -e "       File: ${BOLD}${PROJECT_DIR}/ha-frigate-ai-automation.yaml${NC}"
    echo -e "       HA → Settings → Automations → ⋯ → Edit in YAML → paste"
else
    echo -e "    ${CYAN}3.${NC} Home Assistant is optional — add it later via Control Panel."
fi
echo ""
echo -e "  ${BOLD}Useful Commands${NC}"
echo -e "    ${CYAN}Bridge logs:${NC}     journalctl --user -u frigate-openclaw-bridge -f"
echo -e "    ${CYAN}Restart all:${NC}     systemctl --user restart openclaw-gateway frigate-openclaw-bridge frigate-control-panel"
echo -e "    ${CYAN}Frigate logs:${NC}    docker logs frigate -f --tail 50"
echo -e "    ${CYAN}MQTT test:${NC}       mosquitto_sub -h 127.0.0.1 -p ${MQTT_PORT} -u ${MQTT_USER} -P '***' -t 'frigate/events' -v"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
