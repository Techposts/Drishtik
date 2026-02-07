# Frigate → OpenClaw AI Security System

This repo contains the full, working setup for an AI-powered security camera pipeline:

Frigate (person detection) → Bridge → OpenClaw (GPT-4o-mini vision) → WhatsApp + MQTT → Home Assistant + Alexa

It includes detailed documentation, install scripts, and example config files.

---

## Docs Map

1. `docs/SECURITY-AI-SYSTEM-COMPLETE.md` — full architecture, hardware, flow, troubleshooting
2. `docs/FRIGATE-OPENCLAW-BRIDGE.md` — bridge logic + MQTT payloads
3. `docs/HOME-ASSISTANT-SETUP.md` — MQTT entities + automations in HA
4. `docs/OPENCLAW-API-KEYS.md` — OpenAI/Anthropic keys + model setup
5. `docs/OpenClaw-and-Frigate.md` — redacted planning summary

## Actions

1. OpenClaw install: `scripts/openclaw/install-openclaw.sh`
2. Pipeline install: `scripts/install.sh`
3. HA automations: `config/ha-frigate-ai-automation.yaml`

---

## Hardware

### Reference Build (My System)

This system runs on a **12-year-old Lenovo S20-30 (59-436662) 11.6-inch laptop** with:

- **Google Coral TPU (Half Mini PCIe)** installed by **replacing the WiFi card**
- **TP-Link USB 3.0 to Gigabit Ethernet** for network access
- **1TB Samsung EVO SSD** replacing the hard drive
- **RAM upgraded from 2GB to 8GB DDR3**
- Debian 12 (Bookworm)
- Runs **Frigate** + **OpenClaw** on the same box
- AI vision analysis handled by **OpenAI GPT-4o-mini**

Other services on this same server:
- Plex Media Server
- Samba (NAS/SMB shares)

### Build Video (Placeholder)

```
https://www.youtube.com/watch?v=ePSMDSl6QvM
```

Despite the old hardware, the TPU handles detection and GPT-4o-mini handles vision analysis reliably.

---

## What It Does

- Detects **person** events in Frigate (MQTT)
- Downloads the event snapshot
- **Stages** the snapshot into OpenClaw workspace for WhatsApp media
- Sends the snapshot to OpenClaw via webhook
- OpenClaw runs GPT-4o-mini vision analysis
- WhatsApp receives **image + analysis**
- Home Assistant receives **pending** immediately, then **final analysis** update
- Alexa announces high-risk events

---

## Repository Layout

```
github/
├── README.md
├── SECURITY.md
├── CHANGELOG.md
├── docs/
│   ├── FRIGATE-OPENCLAW-BRIDGE.md
│   ├── HOME-ASSISTANT-SETUP.md
│   ├── SECURITY-AI-SYSTEM-COMPLETE.md
│   ├── OPENCLAW-API-KEYS.md
│   └── OpenClaw-and-Frigate.md
├── scripts/
│   ├── install.sh
│   ├── setup-frigate-ai.sh
│   ├── setup-frigate-ai-prereqs.sh
│   └── frigate-openclaw-bridge.py
│   └── openclaw/
│       ├── README.md
│       ├── install-openclaw.sh
│       └── setup-https-proxy.sh
└── config/
    ├── frigate-config.yml
    ├── docker-compose.yml
    └── ha-frigate-ai-automation.yaml
    └── openclaw.json.example
```

---

## Quick Start (New System)

1. **Run prerequisite checks**

```bash
bash scripts/setup-frigate-ai-prereqs.sh
```

2. **Run the interactive installer**

```bash
bash scripts/install.sh
```

3. **Apply Home Assistant automation**

- Use `config/ha-frigate-ai-automation.yaml`
- Or see `docs/HOME-ASSISTANT-SETUP.md`

4. **Test**

- Walk in front of a camera
- WhatsApp should receive **image + analysis**
- HA should show **pending**, then update with the final analysis

---

## OpenClaw Install (Recommended)

Use the bundled OpenClaw installer if this is a new system:

```bash
bash scripts/openclaw/install-openclaw.sh
```

Optional HTTPS reverse proxy (self-signed cert, LAN access):

```bash
sudo bash scripts/openclaw/setup-https-proxy.sh
```

**Security note:** real OpenClaw configs and tokens are not included in this repo.
Use `config/openclaw.json.example` as a template.

---

## API Keys And Models

OpenClaw supports multiple providers. For this pipeline, **OpenAI GPT-4o-mini** is recommended for vision.

### OpenAI (Recommended)

1. Create an API key in the OpenAI console (API Keys section).
2. Paste it into OpenClaw:

```bash
openclaw models auth paste-token --provider openai
```

3. Set the model:

```bash
openclaw models set openai/gpt-4o-mini
```

### Anthropic (Optional)

1. Create an API key in the Anthropic console (API Keys section).
2. Paste it into OpenClaw:

```bash
openclaw models auth paste-token --provider anthropic
```

3. Suggested models:

```bash
openclaw models set anthropic/claude-3-5-haiku-latest
openclaw models set anthropic/claude-sonnet-4-20250514
```

---

## New System Checklist

1. Install Debian + Docker + Python 3.10+.
2. Install OpenClaw and complete WhatsApp login.
3. Ensure OpenClaw gateway is running on `:18789`.
4. Ensure OpenClaw workspace exists: `~/.openclaw/workspace`.
5. Create OpenClaw media path: `~/.openclaw/workspace/ai-snapshots`.
6. Ensure sessions index exists: `~/.openclaw/agents/main/sessions/sessions.json`.
7. Install Frigate and enable snapshots in `config.yml`.
8. Run `scripts/setup-frigate-ai-prereqs.sh` and fix any warnings.
9. Run `scripts/install.sh` and follow prompts.
10. Apply Home Assistant automation YAML.
11. Enable lingering so services start at boot: `sudo loginctl enable-linger <user>`.
12. Test end-to-end by walking in front of a camera.

---

## Recommended System Configuration

Minimum (works, but tight):
- Dual-core x86_64 CPU
- 4 GB RAM
- SSD recommended
- Coral TPU (USB or PCIe)

Recommended (smoother):
- Dual-core or better CPU
- 8 GB RAM
- SSD
- Coral TPU (Half Mini PCIe or USB)
- Wired Ethernet (USB 3.0 Gigabit adapter ok)

---

## Setup Sequence (Clean Install)

1. Install Debian + Docker + Python 3.10+.
2. Install OpenClaw using `scripts/openclaw/install-openclaw.sh`.
3. Add OpenAI API key and set model to `openai/gpt-4o-mini`.
4. Configure WhatsApp/Telegram/Discord if desired (I use WhatsApp).
5. Install Frigate and confirm snapshots are enabled.
6. Ensure Coral TPU works (USB or PCIe).
7. Run `scripts/setup-frigate-ai-prereqs.sh` and fix warnings.
8. Run `scripts/install.sh` to wire the pipeline end-to-end.
9. Apply Home Assistant automation YAML.
10. Test end-to-end by walking in front of a camera.

---

## Sensitive Files

Any real `openclaw.json`, auth profiles, session logs, or tokens are **excluded**.
If you need the original transcript, it was moved to `github_sensitive/` on the server.

---

## Important Implementation Details

### WhatsApp Media Path
OpenClaw blocks absolute paths in `MEDIA:`. The bridge stages snapshots into OpenClaw workspace and uses:

```
MEDIA:./.openclaw/workspace/ai-snapshots/<event_id>.jpg
```

### Home Assistant Updates
Each event publishes twice to MQTT:

- **Immediate** pending message
- **Final** GPT-4o-mini analysis

Notifications update by `event_id` so HA shows a single alert that gets updated.

---

## Documentation

Start here:

- `docs/SECURITY-AI-SYSTEM-COMPLETE.md` — complete system docs
- `docs/FRIGATE-OPENCLAW-BRIDGE.md` — bridge behavior + troubleshooting
- `docs/HOME-ASSISTANT-SETUP.md` — HA MQTT + automation
- `docs/OPENCLAW-API-KEYS.md` — OpenAI/Anthropic API keys + model selection
- `docs/OpenClaw-and-Frigate.md` — original planning notes

---

## Notes

- OpenClaw uses **GPT-4o-mini** for vision analysis.
- The system is optimized to keep latency low on older hardware.
- All services run as **user-level systemd services**.
