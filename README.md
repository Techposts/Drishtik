# Drishtik — AI-Powered Security Camera System

> **Drishtik** (दृष्टिक) means "intelligent vision" 

Turn standard IP cameras into an AI security brain. Every person detection is analyzed by a local vision language model that describes who is there, what they're doing, and the threat level — then delivers structured alerts to your phone, smart speakers, and home dashboard.

<p align="center">
  <a href="https://www.youtube.com/watch?v=2Fwbpcf-HOM">
    <img src="https://img.youtube.com/vi/2Fwbpcf-HOM/maxresdefault.jpg" alt="Drishtik — AI Security Camera System" width="700">
  </a>
  <br>
  <em>Watch: Full project walkthrough and demo</em>
</p>

---

## What It Does

- Detects **person** events via **Google Coral TPU** on Frigate NVR
- Analyzes snapshots using **local Ollama VLM** (qwen2.5vl:7b) — no cloud dependency for vision
- Falls back to **OpenAI GPT-4o-mini** if local model unavailable
- **Rule-based severity scoring** adjusts AI risk using time, zone, home mode, and behavioral keywords
- **Professional structured WhatsApp alerts** with emoji severity, sections, and media attachments
- **Snapshot + clip** attached to WhatsApp for medium/high/critical alerts
- **Alexa** announces descriptive security briefings on Echo devices
- **Home Assistant** receives structured MQTT data for dashboard, mobile push, and automations
- **Event memory** tracks detection history for pattern awareness
- **Multi-step reasoning** re-confirms high/critical alerts with a second AI pass
- Filters WhatsApp to **medium+ risk only** — low-risk events go to HA/logs only
- **Web control panel** for managing all settings, running diagnostics, and viewing reports

---

## WhatsApp Alert

Real alert with snapshot, structured analysis, and video clip attached:

<p align="center">
  <img src="images/whatsapp-alert.png" alt="WhatsApp Security Alert" width="380">
  <br>
  <em>Structured WhatsApp alert — snapshot, AI analysis, severity, behavior, risk, and 15s video clip</em>
</p>

---

## Architecture

```
IP Cameras (RTSP)                    Mac M4 Mini
  |                                  +-----------------------+
  v                                  | Ollama                |
Frigate NVR (Coral TPU)             | qwen2.5vl:7b (local) |
  |  MQTT: frigate/events           +----------+------------+
  v                                            ^
Bridge Script (Python)                         | HTTP (vision)
  |                                            |
  +--------------------------------------------+
  |
  |  Structured JSON decision
  |  Rule-based severity scoring
  |  Professional WhatsApp formatting
  |
  +---> OpenClaw Gateway ---> WhatsApp (snapshot + alert + clip)
  |
  +---> MQTT: openclaw/frigate/analysis
           |
           +---> Home Assistant (mobile push + dashboard)
           +---> Alexa TTS (descriptive briefing, daytime only)
```

### Multi-Machine Setup

| Machine | Role | IP |
|---------|------|----|
| Debian Server | Frigate NVR, Bridge, OpenClaw Gateway | `192.168.1.10` |
| Mac M4 Mini | Ollama VLM (qwen2.5vl:7b) | `192.168.1.30` |
| Home Assistant | MQTT Broker, Alexa, Automations | `192.168.1.20` |

---

## 3-Pillar Alert System

### Pillar 1: Structured AI Output

The vision model outputs structured JSON with subject identity, behavior description, risk assessment (level + confidence + reason), event type, and recommended action.

### Pillar 2: Rule-Based Severity Scoring

A deterministic scoring engine adjusts the AI's risk assessment using:
- Time of day (night = higher)
- Camera zone (entry points = higher)
- Home mode (away = much higher)
- Behavioral keywords (loitering, concealment, tools = higher)
- Known faces (lower)

Score thresholds: 0-2 = LOW, 3-4 = MEDIUM, 5-6 = HIGH, 7+ = CRITICAL

### Pillar 3: Professional WhatsApp Formatter

Structured alerts with emoji severity indicators, organized sections (EVENT, SUBJECT, BEHAVIOR, RISK, CONTEXT, ACTION, MEDIA, ESCALATION), and automatic media attachment decisions.

### Smart Media Decisions

| Risk Level | Snapshot | Clip | Clip Length | Monitoring |
|-----------|----------|------|-------------|------------|
| LOW | Yes | No | - | No |
| MEDIUM | Yes | Yes | 15s | No |
| HIGH | Yes | Yes | 30s | Yes |
| CRITICAL | Yes | Yes | 60s | Yes |

---

## Drishtik Control Panel

A built-in web UI for managing all settings without SSH or config file editing.

### Overview & Diagnostics

<table>
<tr>
<td width="50%">
<img src="images/overview.png" alt="Control Panel Overview" width="100%">
<p align="center"><em>Overview — system health, synthetic events, Frigate config editor</em></p>
</td>
<td width="50%">
<img src="images/diagnostics.png" alt="Diagnostics & Policy Simulator" width="100%">
<p align="center"><em>Diagnostics — test suite, policy simulator with dry-run</em></p>
</td>
</tr>
</table>

### Features & Home Assistant

<table>
<tr>
<td width="50%">
<img src="images/features.png" alt="Feature Switches" width="100%">
<p align="center"><em>Feature toggles — Policy, Memory, Confirmation Gate, Reports</em></p>
</td>
<td width="50%">
<img src="images/home-assistant.png" alt="Home Assistant Settings" width="100%">
<p align="center"><em>HA settings — WhatsApp, known faces, zone lights, home mode</em></p>
</td>
</tr>
</table>

### AI Engine & Camera NVR

<table>
<tr>
<td width="50%">
<img src="images/openclaw-ai-agent.png" alt="OpenClaw AI Agent Settings" width="100%">
<p align="center"><em>OpenClaw AI — endpoints, model, WhatsApp policy, gateway</em></p>
</td>
<td width="50%">
<img src="images/frigate-nvr.png" alt="Frigate NVR Config" width="100%">
<p align="center"><em>Frigate NVR — config editor, validation, backups, restart</em></p>
</td>
</tr>
</table>

### Summaries & Performance

<table>
<tr>
<td width="50%">
<img src="images/summaries.png" alt="Summaries & Reports" width="100%">
<p align="center"><em>Reports — daily events, risk distribution, action breakdown</em></p>
</td>
<td width="50%">
<img src="images/performance.png" alt="Performance Metrics" width="100%">
<p align="center"><em>Performance — event rates, success rates, service health</em></p>
</td>
</tr>
</table>

### Audit Trail & Admin

<table>
<tr>
<td width="50%">
<img src="images/audits.png" alt="Audit Trail" width="100%">
<p align="center"><em>Activity history — timestamped config changes and actions</em></p>
</td>
<td width="50%">
<img src="images/admin-config.png" alt="Admin Configuration" width="100%">
<p align="center"><em>Admin — user management, auth, audit signing</em></p>
</td>
</tr>
</table>

### Service Logs

<p align="center">
  <img src="images/service-logs.png" alt="Service Logs" width="380">
  <br>
  <em>Live service logs viewer for bridge, OpenClaw, and Frigate</em>
</p>

---

## Hardware

### Reference Build

This system runs on a **12-year-old Lenovo S20-30 laptop** with:

- **Google Coral TPU (Half Mini PCIe)** replacing the WiFi card
- **TP-Link USB 3.0 to Gigabit Ethernet** for network
- **1TB Samsung EVO SSD**
- **8GB DDR3 RAM** (upgraded from 2GB)
- Debian 12

Vision AI runs on a separate **Mac M4 Mini** via Ollama (can also use cloud API).

### Build Video — WiFi Card to Coral TPU

<p align="center">
  <a href="https://www.youtube.com/watch?v=ePSMDSl6QvM">
    <img src="https://img.youtube.com/vi/ePSMDSl6QvM/hqdefault.jpg" alt="Replacing WiFi card with Coral TPU" width="480">
  </a>
  <br>
  <em>Watch: Replacing the Half Mini PCIe WiFi card with a Google Coral TPU</em>
</p>

---

## System Requirements

**Minimum:**
- Dual-core x86_64 CPU, 4GB RAM, SSD, Coral TPU (USB or PCIe)

**Recommended:**
- 8GB+ RAM, SSD, Coral TPU, Wired Ethernet
- Separate machine for Ollama VLM (any machine with 8GB+ RAM)

**Software:**
- Debian 12+ / Ubuntu 22.04+
- Docker, Python 3.10+, Node.js 20+
- Ollama (for local VLM) or OpenAI API key (for cloud)

---

## Setup Guide

### Step 1: Install Base System

```bash
sudo apt update && sudo apt install -y docker.io python3 python3-venv python3-full curl
```

### Step 2: Install OpenClaw

```bash
bash scripts/openclaw/install-openclaw.sh
```

### Step 3: Configure AI Model

**Option A — Local Ollama (recommended):**
```bash
# On a machine with enough RAM
ollama pull qwen2.5vl:7b
```

**Option B — Cloud (OpenAI):**
```bash
openclaw models auth paste-token --provider openai
openclaw models set openai/gpt-4o-mini
```

See [docs/OPENCLAW-API-KEYS.md](docs/OPENCLAW-API-KEYS.md) for details.

### Step 4: Install Frigate

```bash
docker compose up -d frigate
```

Use `config/docker-compose.yml` and `config/frigate-config.yml` as references.

### Step 5: Run Prerequisites Check

```bash
bash scripts/setup-frigate-ai-prereqs.sh
```

### Step 6: Run the Pipeline Installer

```bash
bash scripts/install.sh
```

### Step 7: Configure Home Assistant

Apply `config/ha-frigate-ai-automation.yaml` to your HA automations. See [docs/HOME-ASSISTANT-SETUP.md](docs/HOME-ASSISTANT-SETUP.md).

### Step 8: Configure Runtime Settings

Edit `bridge-runtime-config.json` for cameras, zones, Ollama endpoint, WhatsApp recipients, cooldowns, and phase toggles. See [config/bridge-runtime-config.json.example](config/bridge-runtime-config.json.example).

### Step 9: Enable Auto-Start & Test

```bash
sudo loginctl enable-linger $(whoami)
systemctl --user status frigate-openclaw-bridge.service
```

Walk in front of a camera and check WhatsApp + HA + Alexa.

---

## Phase System

The bridge implements capabilities in phases, each independently toggleable:

| Phase | Feature | Status | Config Key |
|-------|---------|--------|------------|
| 1 | Decision Engine (structured JSON) | Active | Always on |
| 2 | HA Tool Execution (lights, clips, alarm) | Active | Always on |
| 3 | Policy Layer (camera context, zones, time) | Active | `phase3_enabled` |
| 3.5 | Known Faces Recognition | Planned | — |
| 4 | Event Memory (JSONL history) | Active | `phase4_enabled` |
| 5 | Multi-Step Reasoning (re-confirm high+) | Active | `phase5_enabled` |
| 6 | Multi-Camera Correlation | Planned | — |
| 7 | Conversation Mode | Planned | — |
| 8 | Summaries & Reports | Active | `phase8_enabled` |

---

## Configuration

### Key Config Files

| File | Purpose |
|------|---------|
| `bridge-runtime-config.json` | All runtime settings (cameras, zones, model, recipients, phases) |
| `config.yml` | Frigate NVR config (cameras, RTSP, detection, MQTT) |
| `~/.openclaw/openclaw.json` | OpenClaw gateway, hooks, messaging channels |
| `SKILL.md` | AI analysis + delivery instructions for OpenClaw agent |

### Critical Settings

| Setting | Where | What |
|---------|-------|------|
| `ollama_api` | runtime config | Ollama VLM endpoint |
| `ollama_model` | runtime config | Vision model (e.g. `qwen2.5vl:7b`) |
| `whatsapp_to` | runtime config | Recipient phone numbers |
| `cooldown_seconds` | runtime config | Per-camera alert rate limit (default: 30) |
| `camera_context_notes` | runtime config | Security descriptions per camera |
| `camera_policy_zones` | runtime config | Zone type per camera |
| Webhook token | openclaw.json + runtime config | Must match on both sides |
| WhatsApp allowlist | openclaw.json | Numbers allowed to receive messages |

---

## Repository Layout

```
Drishtik/
+-- README.md                          # This file
+-- SECURITY.md                        # Sensitive files policy
+-- CHANGELOG.md                       # Version history
+-- images/                            # Screenshots and media
+-- config/
|   +-- bridge-runtime-config.json.example  # Runtime config template
|   +-- frigate-config.yml             # Frigate config (redacted)
|   +-- docker-compose.yml            # Docker services
|   +-- ha-frigate-ai-automation.yaml  # HA unified automation
|   +-- openclaw.json.example         # OpenClaw config template
+-- docs/
|   +-- SECURITY-AI-SYSTEM-COMPLETE.md # Full architecture & troubleshooting
|   +-- FRIGATE-OPENCLAW-BRIDGE.md     # Bridge logic & MQTT payloads
|   +-- HOME-ASSISTANT-SETUP.md        # HA setup instructions
|   +-- OPENCLAW-API-KEYS.md          # API key setup guide
|   +-- OPENCLAW-CONFIG.md            # OpenClaw gateway config
|   +-- CHEATSHEET.md                 # Quick reference commands
+-- scripts/
|   +-- install.sh                     # Combined installer
|   +-- setup-frigate-ai.sh           # Pipeline installer
|   +-- setup-frigate-ai-prereqs.sh   # Prerequisites checker
|   +-- frigate-openclaw-bridge.py    # Bridge script (template)
|   +-- openclaw/
|       +-- README.md                  # OpenClaw reference guide
|       +-- install-openclaw.sh        # OpenClaw installer
|       +-- setup-https-proxy.sh       # HTTPS reverse proxy
+-- plan/
    +-- README.md                      # Phase roadmap overview
    +-- phase-1/ through phase-8/      # Per-phase plans
    +-- phase-3-5/                     # Known faces plan
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [Full Architecture](docs/SECURITY-AI-SYSTEM-COMPLETE.md) | Hardware, data flow, components, troubleshooting |
| [Bridge Reference](docs/FRIGATE-OPENCLAW-BRIDGE.md) | Bridge logic, MQTT payloads, 3-pillar system |
| [HA Setup](docs/HOME-ASSISTANT-SETUP.md) | MQTT sensors, automations, Alexa |
| [API Keys](docs/OPENCLAW-API-KEYS.md) | OpenAI/Anthropic key setup |
| [OpenClaw Config](docs/OPENCLAW-CONFIG.md) | Gateway + messaging config |
| [Cheat Sheet](docs/CHEATSHEET.md) | Quick commands reference |
| [Phase Roadmap](plan/README.md) | Implementation phases |

---

## Sensitive Files

Real tokens, phone numbers, and auth profiles are **excluded** from this repo. See [SECURITY.md](SECURITY.md). Use the `.example` config files as templates.
