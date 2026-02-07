# Drishtik — AI-Powered Security Camera System

> Frigate (person detection) → Bridge → OpenClaw (GPT-4o-mini vision) → WhatsApp + MQTT → Home Assistant + Alexa

Turn standard IP cameras into an AI security brain. Every person detection is analyzed by a vision AI model that describes who is there, what they're doing, and the threat level — then delivers that analysis to your phone, smart speakers, and home dashboard.

---

## Table of Contents

- [What It Does](#what-it-does)
- [High-Level Data Flow](#high-level-data-flow)
- [Hardware](#hardware)
- [System Requirements](#system-requirements)
- [Setup Guide](#setup-guide)
  - [Step 1: Install Base System](#step-1-install-base-system)
  - [Step 2: Install OpenClaw](#step-2-install-openclaw)
  - [Step 3: Configure API Keys](#step-3-configure-api-keys)
  - [Step 4: Install Frigate](#step-4-install-frigate)
  - [Step 5: Run Prerequisites Check](#step-5-run-prerequisites-check)
  - [Step 6: Run the Pipeline Installer](#step-6-run-the-pipeline-installer)
  - [Step 7: Configure Home Assistant](#step-7-configure-home-assistant)
  - [Step 8: Enable Auto-Start](#step-8-enable-auto-start)
  - [Step 9: Test End-to-End](#step-9-test-end-to-end)
- [Implementation Details](#implementation-details)
- [Repository Layout](#repository-layout)
- [Documentation](#documentation)
- [Sensitive Files](#sensitive-files)

---

## What It Does

- Detects **person** events in Frigate via Coral TPU (MQTT)
- Downloads the event snapshot from Frigate API
- **Stages** the snapshot into OpenClaw workspace for WhatsApp media delivery
- Sends the snapshot to OpenClaw via webhook for **GPT-4o-mini vision** analysis
- WhatsApp receives **image + analysis** text
- Home Assistant receives **pending** immediately, then **final analysis** update via MQTT
- Alexa announces **medium/high risk** events on Echo devices

---

## High-Level Data Flow

```
IP Cameras (RTSP)
  │
  ▼
Frigate NVR (person detection via Coral TPU)
  │  MQTT: frigate/events
  ▼
Bridge Script (snapshot download + workspace staging)
  │  HTTP POST: /hooks/agent
  ▼
OpenClaw Gateway (GPT-4o-mini vision analysis)
  │
  ├── WhatsApp (snapshot image + analysis text)
  │
  └── MQTT: openclaw/frigate/analysis
         ├── Home Assistant (pending → final update)
         └── Alexa TTS (medium/high risk, daytime only)
```

---

## Hardware

### Reference Build

This system runs on a **12-year-old Lenovo S20-30 (59-436662) 11.6-inch laptop** with:

- **Google Coral TPU (Half Mini PCIe)** installed by **replacing the WiFi card**
- **TP-Link USB 3.0 to Gigabit Ethernet** for network access
- **1TB Samsung EVO SSD** replacing the hard drive
- **RAM upgraded from 2GB to 8GB DDR3**
- Debian 12 (Bookworm)
- Runs **Frigate** + **OpenClaw** on the same box
- AI vision analysis handled by **OpenAI GPT-4o-mini**

Other services on this same server: Plex, Jellyfin, Samba, Transmission.

### Build Video (WiFi Card → Coral TPU)

[![Coral TPU Half Mini PCIe install video](https://img.youtube.com/vi/ePSMDSl6QvM/0.jpg)](https://www.youtube.com/watch?v=ePSMDSl6QvM)

Video shows replacing the Half Mini PCIe WiFi card with a Coral TPU. Despite the old hardware, the TPU handles detection and GPT-4o-mini handles vision analysis reliably.

---

## System Requirements

**Minimum** (works, but tight):
- Dual-core x86_64 CPU
- 4 GB RAM
- SSD recommended
- Coral TPU (USB or PCIe)

**Recommended** (smoother):
- Dual-core or better CPU
- 8 GB RAM
- SSD
- Coral TPU (Half Mini PCIe or USB)
- Wired Ethernet (USB 3.0 Gigabit adapter ok)

**Software:**
- Debian 12+ / Ubuntu 22.04+ / Raspberry Pi OS (Bookworm)
- Docker
- Python 3.10+
- Node.js 20+

---

## Setup Guide

### Step 1: Install Base System

Install Debian (or Ubuntu/Raspberry Pi OS) with Docker and Python 3.10+.

```bash
sudo apt update && sudo apt install -y docker.io python3 python3-venv python3-full curl
```

### Step 2: Install OpenClaw

Use the bundled interactive installer:

```bash
bash scripts/openclaw/install-openclaw.sh
```

This handles Node.js, Chromium, OpenClaw, gateway config, messaging channels, and systemd service.

Optional HTTPS reverse proxy (self-signed cert, LAN access):

```bash
sudo bash scripts/openclaw/setup-https-proxy.sh
```

See [scripts/openclaw/README.md](scripts/openclaw/README.md) for the full OpenClaw reference guide.

### Step 3: Configure API Keys

**OpenAI GPT-4o-mini** is recommended for vision analysis in this pipeline.

```bash
# Set the API key
openclaw models auth paste-token --provider openai

# Set the model
openclaw models set openai/gpt-4o-mini
```

Anthropic is optional (for non-vision tasks):

```bash
openclaw models auth paste-token --provider anthropic
openclaw models set anthropic/claude-3-5-haiku-latest
```

See [docs/OPENCLAW-API-KEYS.md](docs/OPENCLAW-API-KEYS.md) for detailed steps.

### Step 4: Install Frigate

Install Frigate with Docker. Use `config/docker-compose.yml` as a starting point and `config/frigate-config.yml` as a reference config.

```bash
docker compose up -d frigate
```

Ensure:
- Coral TPU is detected: `ls /dev/apex_0` (PCIe) or `lsusb | grep -i coral` (USB)
- Snapshots are enabled in `config.yml`
- MQTT is configured to your broker

### Step 5: Run Prerequisites Check

This script verifies all system requirements without making changes:

```bash
bash scripts/setup-frigate-ai-prereqs.sh
```

It checks: Python, Docker, Frigate container, Frigate API, systemd, OpenClaw, gateway, workspace paths, Coral TPU.

Fix any warnings before proceeding.

### Step 6: Run the Pipeline Installer

Run the combined installer (prereqs + pipeline setup):

```bash
bash scripts/install.sh
```

Or run the pipeline setup directly:

```bash
bash scripts/setup-frigate-ai.sh
```

The installer will:
- Ask for MQTT, Frigate, OpenClaw, and notification settings
- Enable Frigate snapshots
- Add webhook hooks to OpenClaw config
- Create the bridge script with your settings
- Create the OpenClaw Frigate skill
- Create a systemd service for the bridge
- Generate Home Assistant YAML files

### Step 7: Configure Home Assistant

The installer generates two HA YAML files. Apply them to your Home Assistant:

1. **MQTT Sensors** — copy `ha-mqtt-sensors.yaml` contents into your HA `configuration.yaml` under the `mqtt:` section

2. **Automations** — copy `ha-frigate-ai-automation.yaml` contents into your HA `automations.yaml`

3. **Create Helpers** — in HA, go to Settings → Devices & Services → Helpers and create:
   - `input_datetime.frigate_ai_last_alexa` (Date and Time)
   - `input_datetime.frigate_ai_last_echo_show` (Date and Time)

4. **Restart HA** or reload YAML configs from Developer Tools

See [docs/HOME-ASSISTANT-SETUP.md](docs/HOME-ASSISTANT-SETUP.md) for details.

### Step 8: Enable Auto-Start

Enable lingering so user-level services start at boot:

```bash
sudo loginctl enable-linger $(whoami)
```

Verify services are running:

```bash
systemctl --user status frigate-openclaw-bridge.service
systemctl --user status openclaw-gateway.service
```

### Step 9: Test End-to-End

1. Walk in front of a camera
2. Watch the bridge logs: `journalctl --user -u frigate-openclaw-bridge.service -f`
3. Verify: WhatsApp receives **image + analysis**
4. Verify: HA shows **pending**, then updates with the final analysis
5. Verify: Alexa announces medium/high risk events (daytime only)

### What Happens During AI Analysis

When a person is detected, the bridge pulls a snapshot from Frigate and sends it to **OpenClaw**, which runs **GPT-4o-mini vision**. OpenClaw returns a short, structured security assessment, and the bridge publishes it to MQTT. That is why HA first shows **pending**, then updates the same alert when the final analysis arrives. WhatsApp receives the snapshot **plus** the analysis text.

---

## Implementation Details

### WhatsApp Media Path

OpenClaw blocks absolute paths in `MEDIA:`. The bridge stages snapshots into the OpenClaw workspace and uses a relative path:

```
MEDIA:./.openclaw/workspace/ai-snapshots/<event_id>.jpg
```

### Two-Phase MQTT Updates

Each event publishes twice to `openclaw/frigate/analysis`:

1. **Immediate** — pending message (so HA knows a detection happened)
2. **Final** — GPT-4o-mini analysis with risk level, TTS text, and event metadata

Notifications update by `event_id` so HA shows a single alert that gets updated in place.

### MQTT Payload Fields

| Field | Description |
|-------|-------------|
| `camera` | Camera name (e.g. `GarageCam`) |
| `label` | Detection label (`person`) |
| `analysis` | Full GPT-4o-mini analysis text |
| `risk` | Threat level: `low`, `medium`, or `high` |
| `tts` | Short spoken version for Alexa |
| `timestamp` | ISO 8601 UTC timestamp |
| `event_id` | Frigate event ID |
| `snapshot_path` | Local path to saved snapshot |

### Analysis-Only Mode

The bridge supports an analysis-only mode that generates AI analysis and publishes to MQTT without sending WhatsApp/Telegram messages. Useful for HA-only setups.

---

## Repository Layout

```
├── README.md                          # This file
├── SECURITY.md                        # Sensitive files policy
├── CHANGELOG.md                       # Version history
├── docs/
│   ├── SECURITY-AI-SYSTEM-COMPLETE.md # Full architecture & troubleshooting
│   ├── FRIGATE-OPENCLAW-BRIDGE.md     # Bridge logic & MQTT payloads
│   ├── HOME-ASSISTANT-SETUP.md        # HA MQTT entities & automations
│   ├── OPENCLAW-API-KEYS.md           # API key setup (OpenAI/Anthropic)
│   └── OpenClaw-and-Frigate.md        # Redacted planning summary
├── scripts/
│   ├── install.sh                     # Wrapper: prereqs + pipeline setup
│   ├── setup-frigate-ai.sh            # Interactive pipeline installer
│   ├── setup-frigate-ai-prereqs.sh    # System requirements checker
│   ├── frigate-openclaw-bridge.py     # Bridge script (template)
│   └── openclaw/
│       ├── README.md                  # OpenClaw reference guide
│       ├── install-openclaw.sh        # OpenClaw interactive installer
│       └── setup-https-proxy.sh       # nginx HTTPS reverse proxy
└── config/
    ├── frigate-config.yml             # Frigate config (redacted)
    ├── docker-compose.yml             # Docker services (Frigate + Plex + Transmission)
    ├── ha-frigate-ai-automation.yaml  # HA unified automation
    └── openclaw.json.example          # OpenClaw config template
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [SECURITY-AI-SYSTEM-COMPLETE](docs/SECURITY-AI-SYSTEM-COMPLETE.md) | Full architecture, hardware, data flow, component details, troubleshooting |
| [FRIGATE-OPENCLAW-BRIDGE](docs/FRIGATE-OPENCLAW-BRIDGE.md) | Bridge script logic, MQTT payloads, workspace staging |
| [HOME-ASSISTANT-SETUP](docs/HOME-ASSISTANT-SETUP.md) | MQTT sensors, automations, Alexa, Lovelace cards |
| [OPENCLAW-API-KEYS](docs/OPENCLAW-API-KEYS.md) | OpenAI/Anthropic API key creation and model setup |
| [OpenClaw-and-Frigate](docs/OpenClaw-and-Frigate.md) | Redacted planning summary |
| [OpenClaw Reference](scripts/openclaw/README.md) | OpenClaw CLI commands, gateway, channels, diagnostics |
| [Roadmap Plan](plan/README.md) | Phase-by-phase implementation plan (start with Phase 1) |

---

## Sensitive Files

Any real `openclaw.json`, auth profiles, session logs, or tokens are **excluded** from this repo. See [SECURITY.md](SECURITY.md) for the full exclusion policy.

Use `config/openclaw.json.example` as a template for your own config.
