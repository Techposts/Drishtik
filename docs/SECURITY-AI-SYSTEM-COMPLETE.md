# AI-Powered Security Camera System — Complete Documentation

**Version:** 1.0
**Date:** 2026-02-07
**Author:** Ravi (<HOME_USER>)
**Server:** 192.168.1.10 (Debian 12, Linux 6.1.0-37-amd64)
**Hardware:** 12-year-old laptop with Coral TPU (Half Mini PCIe) replacing the WiFi card

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Component Map](#3-component-map)
4. [Network Topology](#4-network-topology)
5. [Data Flow — Step by Step](#5-data-flow--step-by-step)
6. [Component Details](#6-component-details)
   - 6.1 [Frigate NVR](#61-frigate-nvr)
   - 6.2 [OpenClaw AI Gateway](#62-openclaw-ai-gateway)
   - 6.3 [Bridge Script](#63-bridge-script)
   - 6.4 [OpenClaw Frigate Skill](#64-openclaw-frigate-skill)
   - 6.5 [Home Assistant](#65-home-assistant)
   - 6.6 [Alexa Echo Devices](#66-alexa-echo-devices)
7. [File Map](#7-file-map)
8. [Configuration Reference](#8-configuration-reference)
9. [MQTT Topics & Payloads](#9-mqtt-topics--payloads)
10. [Notification Channels](#10-notification-channels)
11. [Service Management](#11-service-management)
12. [Security & Access Control](#12-security--access-control)
13. [Adding Future Channels](#13-adding-future-channels)
14. [New System Checklist](#14-new-system-checklist)
15. [Troubleshooting Guide](#15-troubleshooting-guide)
16. [Appendix — All File Contents](#16-appendix--all-file-contents)

---

## 1. System Overview

This system turns standard security cameras into an **AI-powered security brain**. Instead of just recording motion, every person detection is analyzed by a vision AI model (GPT-4o-mini) that describes what it sees — who is there, what they're doing, and the threat level — then delivers that analysis instantly to your phone, your smart speakers, and your home dashboard.

### Hardware Reality Check

This runs on a **12-year-old laptop**. The performance is viable because:
- **Person detection** runs on a **Google Coral TPU (Half Mini PCIe)**
- The TPU is installed by **replacing the laptop WiFi card**
- **Vision analysis** is offloaded to **OpenAI GPT-4o-mini** via OpenClaw

### What It Does

- Detects **people** on 3 security cameras using a **Google Coral TPU**
- Captures a **snapshot** of every detection
- Sends the snapshot to **GPT-4o-mini** (vision model) for intelligent analysis
- Delivers the **snapshot image + AI analysis** to **WhatsApp**
- **Announces** a short spoken summary on **4 Alexa Echo devices**
- Publishes structured data to **Home Assistant** for dashboard display and automations
- **Rate-limits** alerts to prevent notification spam (30-second cooldown per camera)

### Key Numbers

| Metric | Value |
|--------|-------|
| Cameras | 3 (GarageCam, TopStairCam, TerraceCam) |
| Detection FPS | 5 per camera |
| AI Model | GPT-4o-mini (vision capable) |
| Detection Hardware | Google Coral TPU (PCI) |
| Alert Latency | ~2-5s (pending) / ~15-40s (full analysis) |
| Cooldown | 30 seconds per camera |
| Snapshot Retention | 7 days |
| Recording Retention | 15 days |
| Alexa Devices | 4 Echo devices |
| WhatsApp Recipients | 1 (configurable list) |

---

## 2. Architecture Diagram

### High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        192.168.1.10 (Debian Server)                        │
│                                                                             │
│  ┌─────────────┐    MQTT     ┌──────────────────┐   HTTP    ┌───────────┐  │
│  │   Frigate    │───events──→│  Bridge Script    │─webhook──→│  OpenClaw  │  │
│  │   (Docker)   │            │  (Python/systemd) │          │  Gateway   │  │
│  │              │            │                    │          │  (Node.js) │  │
│  │ Coral TPU    │            │  Downloads snap    │          │            │  │
│  │ 3 cameras    │            │  Saves to disk     │          │ GPT-4o-mini│  │
│  │ Port 5000    │            │  Posts to OpenClaw  │          │ Port 18789 │  │
│  └──────┬───────┘            │  Publishes MQTT    │          └─────┬──────┘  │
│         │                    └────────┬───────────┘                │         │
│         │                             │                            │         │
│         │ RTSP                        │ MQTT                       │         │
│         │                             │ (analysis)                 │         │
└─────────┼─────────────────────────────┼────────────────────────────┼─────────┘
          │                             │                            │
          │                             ▼                            ▼
┌─────────┴──────┐           ┌──────────────────┐          ┌──────────────┐
│   IP Cameras   │           │  Home Assistant   │          │   WhatsApp   │
│                │           │  192.168.1.20    │          │              │
│ .235 GarageCam │           │                   │          │ FROM:        │
│ .187 StairCam  │           │  MQTT Broker      │          │ +1234567890  │
│ .244 TerraceCam│           │  Port 1885        │          │ (OpenClaw)   │
└────────────────┘           │                   │          │              │
                             │  Alexa Media      │          │ TO:          │
                             │  Player ──────────┼──→ Alexa │ +1234567890  │
                             └──────────────────┘          └──────────────┘
```

### Detailed Data Flow Diagram

```
    ┌──────────┐
    │ CAMERA   │ RTSP stream
    │ detects  │─────────────────────┐
    │ person   │                     │
    └──────────┘                     ▼
                              ┌──────────────┐
                              │   FRIGATE     │
                              │              │
                              │ Coral TPU    │
                              │ processes    │
                              │ frame        │
                              │              │
                              │ label=person │
                              │ confidence>  │
                              │ threshold    │
                              └──────┬───────┘
                                     │
                          MQTT: frigate/events
                          {type:"new", after:{label:"person"}}
                                     │
                                     ▼
                              ┌──────────────┐
                              │   BRIDGE     │
                              │   SCRIPT     │
                              │              │
                              │ 1. Filter    │
                              │    person    │
                              │    events    │
                              │              │
                              │ 2. Cooldown  │
                              │    check     │
                              │    (30s)     │
                              │              │
                              │ 3. Wait 3s   │
                              │              │
                              │ 4. Download  │
                              │    snapshot  │──→ /frigate/storage/ai-snapshots/
                              │    from API  │    {event_id}.jpg
                              │ 5. Stage copy│──→ /home/<HOME_USER>/.openclaw/workspace/ai-snapshots/
                              │    for media │    {event_id}.jpg
                              │              │
                              └──────┬───────┘
                                     │
                          HTTP POST /hooks/agent
                          {message, model, deliver,
                           channel, to, sessionKey}
                                     │
                                     ▼
                              ┌──────────────┐
                              │  OPENCLAW    │
                              │  GATEWAY     │
                              │              │
                              │ 1. Receives  │
                              │    webhook   │
                              │              │
                              │ 2. Spawns    │
                              │    agent     │
                              │    session   │
                              │              │
                              │ 3. Agent     │
                              │    opens     │
                              │    image     │
                              │    (image    │
                              │    tool)     │
                              │              │
                              │ 4. GPT-4o-   │
                              │    mini      │
                              │    analyzes  │
                              │    snapshot  │
                              │              │
                              │ 5. Returns   │
                              │    MEDIA:./.openclaw/workspace/ai-snapshots/{event_id}.jpg │
                              │    + text    │
                              │    analysis  │
                              └──────┬───────┘
                                     │
                    ┌────────────────┬┘
                    │                │
                    ▼                ▼
          ┌──────────────┐  ┌──────────────┐
          │  WHATSAPP    │  │   BRIDGE     │
          │              │  │  (continued) │
          │ Snapshot     │  │              │
          │ image +      │  │ Publishes    │
          │ AI analysis  │  │ to MQTT:     │
          │ text         │  │ openclaw/    │
          │ Delivered to │  │ frigate/     │
          │ +1234567890  │  │ analysis     │
          │              │  │ (pending →   │
          │              │  │ final)       │
          └──────────────┘  └──────┬───────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
          ┌──────────────┐ ┌────────────┐ ┌────────────┐
          │  ALEXA TTS   │ │  HA MOBILE │ │ HA DASH-   │
          │              │ │  APP       │ │ BOARD      │
          │ Short spoken │ │            │ │            │
          │ announcement │ │ Push notif │ │ Persistent │
          │ on 4 Echos   │ │ + snapshot │ │ notif +    │
          │ (6AM-11PM)   │ │ image      │ │ sensors    │
          └──────────────┘ └────────────┘ └────────────┘
```

---

## 3. Component Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PHYSICAL INFRASTRUCTURE                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Cameras (RTSP)              Server                    Smart Home   │
│  ┌───────────────┐           ┌─────────────────┐      ┌─────────┐  │
│  │ 192.168.1.101 │           │ 192.168.1.10   │      │ HA      │  │
│  │ Tapo-GarageCam│──RTSP────→│                 │      │ .163    │  │
│  └───────────────┘           │ Debian 12       │ MQTT │         │  │
│  ┌───────────────┐           │ 8GB RAM         │◄────→│ Mosquitto│  │
│  │ 192.168.1.102 │           │                 │      │ :1885   │  │
│  │ TopStairCam   │──RTSP────→│ Google Coral    │      │         │  │
│  └───────────────┘           │ TPU (PCI)       │      │ Alexa   │  │
│  ┌───────────────┐           │                 │      │ Media   │  │
│  │ 192.168.1.103 │           │ Docker          │      │ Player  │  │
│  │ TerraceCam    │──RTSP────→│ Python 3.11     │      └────┬────┘  │
│  └───────────────┘           │ Node.js         │           │       │
│                              └─────────────────┘           ▼       │
│                                                     ┌────────────┐ │
│  Echo Devices (WiFi)                                │ 4x Alexa   │ │
│  ┌──────────────────────────────────────────────┐   │ Echo       │ │
│  │ Ravi's Echo Dot | Echo Show 5 | Old Echo Dot │◄──│ Devices    │ │
│  │ Mom's Echo                                    │   └────────────┘ │
│  └──────────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Software Stack Map

```
┌──────────────────────────────────────────────────────────┐
│                    SOFTWARE LAYERS                        │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Layer 4: NOTIFICATIONS                                  │
│  ┌────────────┐ ┌──────────┐ ┌────────┐ ┌────────────┐  │
│  │ WhatsApp   │ │ Alexa    │ │ HA App │ │ HA Dash    │  │
│  │ (snap+txt) │ │ (TTS)    │ │ (push) │ │ (persist)  │  │
│  └─────┬──────┘ └────┬─────┘ └───┬────┘ └─────┬──────┘  │
│        │             │           │             │         │
│  Layer 3: INTELLIGENCE                                   │
│  ┌───────────────────────────────────────────────────┐   │
│  │           OpenClaw Gateway (Node.js)              │   │
│  │           GPT-4o-mini Vision Analysis             │   │
│  │           Frigate Skill (SKILL.md)                │   │
│  │           Port 18789                              │   │
│  └──────────────────────┬────────────────────────────┘   │
│                         │                                │
│  Layer 2: ORCHESTRATION                                  │
│  ┌───────────────────────────────────────────────────┐   │
│  │        Bridge Script (Python 3.11 / systemd)      │   │
│  │        MQTT listener → Snapshot downloader →      │   │
│  │        Webhook caller → MQTT publisher            │   │
│  └──────────────────────┬────────────────────────────┘   │
│                         │                                │
│  Layer 1: DETECTION                                      │
│  ┌───────────────────────────────────────────────────┐   │
│  │        Frigate NVR (Docker)                       │   │
│  │        Google Coral TPU (PCI)                     │   │
│  │        3 RTSP cameras @ 5 FPS                     │   │
│  │        Port 5000                                  │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  Layer 0: MESSAGING                                      │
│  ┌───────────────────────────────────────────────────┐   │
│  │        MQTT Broker (Mosquitto on HA)              │   │
│  │        192.168.1.20:1885                         │   │
│  │        Topics: frigate/events,                    │   │
│  │                openclaw/frigate/analysis           │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Network Topology

```
                    ┌──────────────────┐
                    │    ROUTER        │
                    │  192.168.1.1     │
                    └────────┬─────────┘
                             │
            ┌────────────────┼────────────────────────┐
            │                │                        │
    ┌───────┴──────┐  ┌──────┴───────┐  ┌────────────┴──────┐
    │ Main Server  │  │Home Assistant│  │   IP Cameras      │
    │ .156         │  │ .163         │  │                    │
    │              │  │              │  │ .235 GarageCam     │
    │ Frigate:5000 │  │ HA:8123      │  │ .187 TopStairCam  │
    │ OpenClaw:    │  │ MQTT:1885    │  │ .244 TerraceCam   │
    │   18789      │  │ Alexa Media  │  │                    │
    │ Bridge       │  │ Player       │  │ (RTSP streams)     │
    └──────────────┘  └──────────────┘  └───────────────────┘

    Connections:
    .235/.187/.244  ──RTSP──→  .156 (Frigate)
    .156 (Frigate)  ──MQTT──→  .163 (broker)   : frigate/events
    .156 (Bridge)   ←─MQTT──  .163 (broker)    : subscribes
    .156 (Bridge)   ──MQTT──→  .163 (broker)   : openclaw/frigate/analysis
    .156 (Bridge)   ──HTTP──→  .156 (OpenClaw) : webhook POST
    .156 (Bridge)   ──HTTP──→  .156 (Frigate)  : snapshot download
    .156 (OpenClaw) ──HTTPS─→  api.openai.com  : GPT-4o-mini
    .156 (OpenClaw) ──HTTPS─→  WhatsApp        : message delivery
    .163 (HA)       ──WiFi──→  Echo devices    : Alexa announcements
```

### Port Map

| Host | Port | Service | Protocol |
|------|------|---------|----------|
| 192.168.1.10 | 5000 | Frigate NVR Web UI & API | HTTP |
| 192.168.1.10 | 18789 | OpenClaw Gateway | HTTP |
| 192.168.1.20 | 1885 | MQTT Broker (Mosquitto) | MQTT |
| 192.168.1.20 | 8123 | Home Assistant | HTTP |
| 192.168.1.101 | 554 | GarageCam RTSP | RTSP |
| 192.168.1.102 | 554 | TopStairCam RTSP | RTSP |
| 192.168.1.103 | 554 | TerraceCam RTSP | RTSP |

---

## 5. Data Flow — Step by Step

### Step 1: Camera Detection (0ms)

```
Camera (RTSP) → Frigate → Coral TPU
```

- Camera streams RTSP video at 1280x720 @ 5 FPS
- Frigate feeds frames to Google Coral TPU via PCI
- Coral runs SSD MobileNet object detection
- When confidence exceeds threshold → detection event created
- Tracked objects: `person`, `cat`, `dog`

### Step 2: MQTT Event Published (~100ms)

```
Frigate → MQTT broker (192.168.1.20:1885)
Topic: frigate/events
```

Frigate publishes a JSON event:
```json
{
  "type": "new",
  "before": {},
  "after": {
    "id": "1770451102.182101-3aibcv",
    "camera": "TopStairCam",
    "label": "person",
    "score": 0.87,
    "has_snapshot": true
  }
}
```

### Step 3: Bridge Receives & Filters (~200ms)

```
MQTT broker → Bridge Script
```

The bridge script:
- Receives the event on `frigate/events`
- Checks: `type == "new"` AND `label == "person"` → proceed
- Checks cooldown: has this camera triggered in the last 30 seconds?
  - **YES** → skip (log: "cooldown active")
  - **NO** → record timestamp, continue

### Step 4: Snapshot Download (~3 seconds)

```
Bridge Script → Frigate API (localhost:5000)
```

- Bridge waits 3 seconds for Frigate to finalize the snapshot
- Downloads from: `GET /api/events/{event_id}/snapshot.jpg`
- Falls back to: `GET /api/events/{event_id}/thumbnail.jpg`
- Saves to: `/home/<HOME_USER>/frigate/storage/ai-snapshots/{event_id}.jpg`
- Typical size: 50-100 KB JPEG

### Step 5: OpenClaw Webhook (~5-10 seconds)

```
Bridge Script → OpenClaw Gateway (localhost:18789)
POST /hooks/agent
```

The bridge sends:
```json
{
  "message": "Security alert from camera 'TopStairCam'. Use the image tool to open and analyze the snapshot at: /home/.../snapshot.jpg ...",
  "model": "openai/gpt-4o-mini",
  "deliver": true,
  "channel": "whatsapp",
  "to": "+1234567890",
  "name": "Frigate",
  "sessionKey": "frigate:TopStairCam:1770451102.182101-3aibcv",
  "timeoutSeconds": 60
}
```

### Step 6: AI Vision Analysis (~5-8 seconds)

```
OpenClaw → GPT-4o-mini (via OpenAI API)
```

OpenClaw:
1. Creates an isolated agent session (sessionKey prevents cross-talk)
2. Loads the **Frigate skill** (SKILL.md) for context
3. Agent uses `image` tool to open the snapshot file
4. GPT-4o-mini analyzes the image
5. Agent responds with `MEDIA:/path/to/snapshot.jpg` + text analysis

### Step 7: WhatsApp Delivery (~1-2 seconds)

```
OpenClaw → WhatsApp API → recipient phone
```

The recipient receives:
- **Snapshot image** (the actual camera capture)
- **AI analysis text** like:
  ```
  [TopStairCam] Threat: LOW
  One person in casual clothes walking up the stairs.
  Daytime, normal activity. No action needed.
  ```

### Step 8: MQTT Analysis Published (~100ms)

```
Bridge Script → MQTT broker
Topic: openclaw/frigate/analysis
```

Published payload:
```json
{
  "camera": "TopStairCam",
  "label": "person",
  "analysis": "[TopStairCam] Threat: LOW\nOne person in casual clothes...",
  "tts": "Security alert, TopStairCam. One person in casual clothes walking up the stairs.",
  "timestamp": "2026-02-07T08:00:15+00:00",
  "event_id": "1770451102.182101-3aibcv",
  "snapshot_path": "/home/<HOME_USER>/frigate/storage/ai-snapshots/1770451102.182101-3aibcv.jpg"
}
```

### Step 9: Home Assistant Automations (~500ms)

```
MQTT broker → Home Assistant → Alexa / Dashboard / Mobile
```

Three things happen simultaneously:

**a) Alexa Announcement** (6 AM - 11 PM only):
```
"Security alert, TopStairCam. One person in casual clothes walking up the stairs."
```
Spoken on: Ravi's Echo Dot, Echo Show 5, Ravi's Old Echo Dot, Mom's Echo

**b) HA Mobile Notification:**
Push notification with title, analysis text, and snapshot image

**c) HA Dashboard:**
Persistent notification visible in the sidebar

### Timeline Summary

```
  0.0s  Camera captures person
  0.1s  Coral TPU detects person
  0.2s  MQTT event published
  0.3s  Bridge receives event, starts cooldown check
  3.3s  Bridge downloads snapshot from Frigate API
  3.5s  Bridge POSTs to OpenClaw webhook
  ~10s  GPT-4o-mini completes analysis
  ~11s  WhatsApp message delivered (snapshot + text)
  ~11s  MQTT analysis published
  ~12s  Alexa announces on 4 devices
  ~12s  HA dashboard updated
  ──────────────────────────────────────
  TOTAL: ~10-15 seconds end-to-end
```

---

## 6. Component Details

### 6.1 Frigate NVR

| Property | Value |
|----------|-------|
| Version | 0.15-1 |
| Runtime | Docker container (`frigate`) |
| Detection | Google Coral TPU (PCI) |
| Web UI | http://192.168.1.10:5000 |
| Config | `/home/<HOME_USER>/frigate/config.yml` |

**Cameras:**

| Camera | IP | Resolution | FPS | Tracks |
|--------|----|-----------|-----|--------|
| Tapo-GarageCam | 192.168.1.101 | 1280x720 | 5 | person, cat, dog |
| TopStairCam | 192.168.1.102 | 1280x720 | 5 | person, cat |
| TerraceCam | 192.168.1.103 | 1280x720 | 5 | person, cat |

**Snapshots:**
- Enabled globally with 7-day retention
- Accessible via API: `GET /api/events/{id}/snapshot.jpg`

### 6.2 OpenClaw AI Gateway

| Property | Value |
|----------|-------|
| Version | 2026.2.2-3 |
| Runtime | Node.js (systemd user service) |
| Port | 18789 |
| Primary Model | openai/gpt-4o-mini |
| WhatsApp | Enabled (plugin) |
| Webhook | Enabled at `/hooks/agent` |
| Config | `/home/<HOME_USER>/.openclaw/openclaw.json` |

**Available Models:**

| Model | Alias | Use |
|-------|-------|-----|
| openai/gpt-4o-mini | (default) | Vision analysis, daily tasks |
| openai/gpt-4o | gpt4o | Complex analysis |
| anthropic/claude-opus-4-5 | opus | Advanced reasoning |
| anthropic/claude-3-5-haiku-latest | haiku | Fast tasks |

**WhatsApp Allowlist:**
- +1234567890 (Amit Kaushik)
- +1234567890 (Ravi — OpenClaw's own number)
- +1234567890 (alert recipient)
- +1234567890
- +1234567890
- +1234567890

### 6.3 Bridge Script

| Property | Value |
|----------|-------|
| File | `/home/<HOME_USER>/frigate/frigate-openclaw-bridge.py` |
| Runtime | Python 3.11 (venv) |
| Venv | `/home/<HOME_USER>/frigate/bridge-venv/` |
| Dependencies | paho-mqtt 2.1.0, requests 2.32.5 |
| Service | `frigate-openclaw-bridge.service` (systemd user) |

**What it does:**

```
┌─────────────────────────────────────────────────┐
│              Bridge Script Logic                 │
├─────────────────────────────────────────────────┤
│                                                  │
│  on_connect()                                    │
│  └─ Subscribe to frigate/events                  │
│                                                  │
│  on_message()                                    │
│  ├─ Parse JSON payload                           │
│  ├─ Filter: type=="new" AND label=="person"      │
│  ├─ Cooldown check (30s per camera)              │
│  ├─ sleep(3) — wait for snapshot                 │
│  ├─ download_snapshot()                          │
│  │  ├─ Try: /api/events/{id}/snapshot.jpg        │
│  │  └─ Fallback: /api/events/{id}/thumbnail.jpg  │
│  ├─ send_to_openclaw()                           │
│  │  ├─ Build prompt with MEDIA directive         │
│  │  ├─ POST /hooks/agent for each recipient      │
│  │  └─ Return analysis text                      │
│  └─ publish_analysis()                           │
│     ├─ Build JSON with analysis + tts            │
│     └─ Publish to openclaw/frigate/analysis      │
│                                                  │
│  make_tts()                                      │
│  └─ Extracts first 1-2 sentences for Alexa       │
│                                                  │
└─────────────────────────────────────────────────┘
```

**Configuration constants (top of script):**

| Constant | Value | Purpose |
|----------|-------|---------|
| MQTT_HOST | 192.168.1.20 | HA MQTT broker |
| MQTT_PORT | 1885 | MQTT port |
| MQTT_USER | <MQTT_USER> | MQTT auth |
| MQTT_PASS | <MQTT_PASS> | MQTT auth |
| MQTT_TOPIC_SUBSCRIBE | frigate/events | Frigate events |
| MQTT_TOPIC_PUBLISH | openclaw/frigate/analysis | AI results |
| FRIGATE_API | http://localhost:5000 | Snapshot download |
| OPENCLAW_WEBHOOK | http://localhost:18789/hooks/agent | AI analysis |
| OPENCLAW_TOKEN | <HOOK_TOKEN> | Webhook auth |
| SNAPSHOT_DIR | /home/.../ai-snapshots | Saved images |
| WHATSAPP_TO | ["+1234567890"] | Recipients list |
| COOLDOWN_SECONDS | 30 | Rate limit |

### 6.4 OpenClaw Frigate Skill

| Property | Value |
|----------|-------|
| File | `~/.openclaw/workspace/skills/frigate/SKILL.md` |

The skill instructs the AI agent on:
- **How to process:** Open snapshot with `image` tool, analyze, respond
- **What to look for:** People count, clothing, activity, location context, time of day, vehicles, threat indicators
- **Threat levels:**
  - **LOW** — Familiar activity, delivery person, daytime, normal behavior
  - **MEDIUM** — Unfamiliar person, unusual time, lingering near entry points
  - **HIGH** — Attempted entry, face concealment, multiple unknowns at night
- **Response format:** `[CameraName] Threat: LEVEL` + 3-5 sentences

### 6.5 Home Assistant

| Property | Value |
|----------|-------|
| Host | 192.168.1.20 |
| Port | 8123 |
| MQTT Broker | Port 1885 (Mosquitto) |
| Alexa Integration | Alexa Media Player (custom component) |
| Automation File | `/home/<HOME_USER>/frigate/ha-frigate-ai-automation.yaml` |

**HA Automations (4 total):**

| # | ID | Trigger | Action | Condition |
|---|------|---------|--------|-----------|
| 1 | frigate_ai_alexa_announce | MQTT topic | Alexa TTS on 4 devices | 6AM-11PM only |
| 2 | frigate_ai_mobile_notify | MQTT topic | HA mobile push + snapshot | Always |
| 3 | frigate_ai_echo_show_display | MQTT topic | Show image on Echo Show | Disabled (optional) |
| 4 | frigate_ai_persistent_notify | MQTT topic | Dashboard sidebar notification | Always |

### 6.6 Alexa Echo Devices

| Device | Entity ID |
|--------|-----------|
| Ravi's Echo Dot | `media_player.ravi_s_echo_dot` |
| Echo Show 5 | `media_player.echo_show_5` |
| Ravi's Old Echo Dot | `media_player.ravi_s_old_echo_dot` |
| Mom's Echo | `media_player.mom_s_echo` |

**Announcement behavior:**
- Type: `announce` (plays attention tone first)
- Time restriction: 6:00 AM to 11:00 PM (silent at night)
- Content: Short TTS version (1-2 sentences), not full analysis

---

## 7. File Map

```
/home/<HOME_USER>/
├── frigate/
│   ├── config.yml                          ← Frigate configuration
│   ├── frigate-openclaw-bridge.py          ← Bridge script (main)
│   ├── bridge-venv/                        ← Python virtual environment
│   │   ├── bin/python3                     ← Python interpreter
│   │   └── lib/python3.11/site-packages/
│   │       ├── paho/mqtt/                  ← MQTT client library
│   │       └── requests/                   ← HTTP client library
│   ├── storage/
│   │   ├── ai-snapshots/                   ← AI-analyzed snapshots
│   │   │   ├── {event_id_1}.jpg
│   │   │   ├── {event_id_2}.jpg
│   │   │   └── ...
│   │   ├── clips/                          ← Frigate clips
│   │   ├── recordings/                     ← Frigate recordings
│   │   └── exports/                        ← Frigate exports
│   ├── FRIGATE-OPENCLAW-BRIDGE.md          ← Quick reference doc
│   ├── HOME-ASSISTANT-SETUP.md             ← HA setup instructions
│   ├── SECURITY-AI-SYSTEM-COMPLETE.md      ← THIS FILE (full docs)
│   └── ha-frigate-ai-automation.yaml       ← HA automation YAML
│
├── .openclaw/
│   ├── openclaw.json                       ← OpenClaw configuration
│   └── workspace/
│       ├── ai-snapshots/                   ← Staged snapshots for WhatsApp MEDIA
│       │   ├── {event_id_1}.jpg
│       │   ├── {event_id_2}.jpg
│       │   └── ...
│       └── skills/
│           └── frigate/
│               └── SKILL.md                ← AI analysis instructions
│
└── .config/systemd/user/
    ├── openclaw-gateway.service            ← OpenClaw service
    ├── frigate-openclaw-bridge.service     ← Bridge service
    └── default.target.wants/
        ├── openclaw-gateway.service        ← Auto-start symlink
        └── frigate-openclaw-bridge.service ← Auto-start symlink
```

**Repository note:** Real OpenClaw configs, auth profiles, and sessions are **not** included in the GitHub repo.
Use `config/openclaw.json.example` as a template and keep real tokens private.

---

## 8. Configuration Reference

### Frigate — config.yml (key sections)

```yaml
detectors:
  coral:
    type: edgetpu
    device: pci               # PCI Coral TPU

mqtt:
  host: 192.168.1.20
  port: 1885
  user: <MQTT_USER>
  password: <MQTT_PASS>

snapshots:
  enabled: true               # REQUIRED for bridge
  retain:
    default: 7                # days

cameras:
  Tapo-GarageCam:             # tracks: person, cat, dog
  TopStairCam:                # tracks: person, cat
  TerraceCam:                 # tracks: person, cat
```

### OpenClaw — openclaw.json (key sections)

```json
{
  "gateway": {
    "port": 18789,
    "auth": {
      "mode": "token",
      "token": "899f89b02c7a6c98b2cc40ab3a038d0a7b46ca134f1e8f1a"
    }
  },
  "hooks": {
    "enabled": true,
    "token": "<HOOK_TOKEN>",
    "path": "/hooks"
  },
  "agents": {
    "defaults": {
      "model": { "primary": "openai/gpt-4o-mini" }
    }
  },
  "plugins": {
    "entries": {
      "whatsapp": { "enabled": true }
    }
  }
}
```

### Systemd — Bridge Service

```ini
[Unit]
Description=Frigate → OpenClaw Vision Bridge
After=network-online.target openclaw-gateway.service

[Service]
ExecStart=/home/<HOME_USER>/frigate/bridge-venv/bin/python3 /home/<HOME_USER>/frigate/frigate-openclaw-bridge.py
Restart=always
RestartSec=10
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=default.target
```

---

## 9. MQTT Topics & Payloads

### Topic: `frigate/events` (Frigate → Bridge)

**Direction:** Frigate publishes, Bridge subscribes
**QoS:** 0

```json
{
  "type": "new",
  "before": {},
  "after": {
    "id": "1770451102.182101-3aibcv",
    "camera": "TopStairCam",
    "label": "person",
    "score": 0.87,
    "has_snapshot": true,
    "start_time": 1770451102.182
  }
}
```

Bridge only processes events where: `type == "new"` AND `after.label == "person"`

### Topic: `openclaw/frigate/analysis` (Bridge → HA)

**Direction:** Bridge publishes, HA subscribes
**QoS:** 1
**Retain:** true (HA sees last value on restart)

```json
{
  "camera": "TopStairCam",
  "label": "person",
  "analysis": "[TopStairCam] Threat: LOW\nOne person in casual clothes walking up the stairs. Daytime, normal activity. No action needed.",
  "tts": "Security alert, TopStairCam. One person in casual clothes walking up the stairs.",
  "timestamp": "2026-02-07T08:00:15.123456+00:00",
  "event_id": "1770451102.182101-3aibcv",
  "snapshot_path": "/home/<HOME_USER>/frigate/storage/ai-snapshots/1770451102.182101-3aibcv.jpg"
}
```

**Field descriptions:**

| Field | Type | Used By | Description |
|-------|------|---------|-------------|
| camera | string | Alexa, HA | Camera name that triggered |
| label | string | HA | Detection label (always "person") |
| analysis | string | WhatsApp, HA dashboard, Mobile | Full AI analysis text |
| tts | string | Alexa | Short 1-2 sentence spoken version |
| timestamp | ISO 8601 | HA | UTC timestamp of analysis |
| event_id | string | HA, debug | Frigate event identifier |
| snapshot_path | string | HA mobile, debug | Local path to saved snapshot |

---

## 10. Notification Channels

### Channel 1: WhatsApp

```
┌─────────────────────────────────────┐
│  WhatsApp Message                   │
│                                     │
│  FROM: +1234567890 (OpenClaw)     │
│  TO:   +1234567890                │
│                                     │
│  ┌───────────────────────────────┐  │
│  │  [snapshot image]             │  │
│  │  camera capture JPEG          │  │
│  └───────────────────────────────┘  │
│                                     │
│  [TopStairCam] Threat: LOW          │
│  One person in casual clothes       │
│  walking up the stairs. Daytime,    │
│  normal activity. No action needed. │
└─────────────────────────────────────┘
```

**Delivery:** Immediate via OpenClaw WhatsApp plugin
**Content:** Snapshot image + full AI analysis text
**Rate limit:** 30-second cooldown per camera

### Channel 2: Alexa (Voice)

```
┌─────────────────────────────────────┐
│  Alexa Announcement                 │
│                                     │
│  🔊 *attention tone*                │
│                                     │
│  "Security alert, TopStairCam.      │
│   One person in casual clothes      │
│   walking up the stairs."           │
│                                     │
│  Devices: 4 Echo speakers           │
│  Hours: 6:00 AM - 11:00 PM         │
└─────────────────────────────────────┘
```

**Delivery:** Via HA → Alexa Media Player → `notify.alexa_media`
**Content:** Short TTS version (1-2 sentences)
**Silent hours:** 11 PM to 6 AM (configurable in HA automation)

### Channel 3: HA Mobile App

```
┌─────────────────────────────────────┐
│  📱 Push Notification               │
│                                     │
│  Title: TopStairCam — Person        │
│         Detected                    │
│                                     │
│  [TopStairCam] Threat: LOW          │
│  One person in casual clothes...    │
│                                     │
│  [snapshot image thumbnail]         │
│                                     │
│  Tag: frigate-TopStairCam           │
│  Group: frigate-security            │
└─────────────────────────────────────┘
```

**Delivery:** Via HA → `notify.notify` → Companion App
**Content:** Title + analysis text + snapshot image

### Channel 4: HA Dashboard

```
┌─────────────────────────────────────┐
│  🔔 Persistent Notification         │
│  (HA Sidebar)                       │
│                                     │
│  Security: TopStairCam              │
│                                     │
│  Time: 2026-02-07T08:00:15+00:00   │
│                                     │
│  [TopStairCam] Threat: LOW          │
│  One person in casual clothes       │
│  walking up the stairs.             │
│                                     │
│  ID: frigate_TopStairCam            │
│  (replaces previous for same cam)   │
└─────────────────────────────────────┘
```

**Delivery:** Via HA → `persistent_notification.create`
**Content:** Timestamp + full analysis text
**Behavior:** Replaces previous notification per camera (not stacking)

---

## 11. Service Management

### Quick Reference

```bash
# ── Bridge Service ──────────────────────────────────
systemctl --user status  frigate-openclaw-bridge.service  # Check status
systemctl --user restart frigate-openclaw-bridge.service  # Restart
systemctl --user stop    frigate-openclaw-bridge.service  # Stop
systemctl --user start   frigate-openclaw-bridge.service  # Start
systemctl --user enable  frigate-openclaw-bridge.service  # Auto-start on boot
systemctl --user disable frigate-openclaw-bridge.service  # Remove auto-start

# ── OpenClaw Gateway ───────────────────────────────
systemctl --user status  openclaw-gateway.service
systemctl --user restart openclaw-gateway.service

# ── Frigate (Docker) ───────────────────────────────
docker ps --filter name=frigate                           # Status
docker restart frigate                                    # Restart
docker logs frigate --tail 50                             # View logs

# ── View Logs ──────────────────────────────────────
journalctl --user -u frigate-openclaw-bridge.service -f   # Live logs
journalctl --user -u frigate-openclaw-bridge.service -n 50 # Last 50 lines
journalctl --user -u openclaw-gateway.service -f          # OpenClaw logs

# ── Reload after config changes ───────────────────
systemctl --user daemon-reload                            # After editing .service files
```

### Startup Order

```
1. Network comes up
2. Docker starts → Frigate container starts
3. systemd user services start:
   a. openclaw-gateway.service (OpenClaw)
   b. frigate-openclaw-bridge.service (Bridge, after gateway)
4. Bridge connects to MQTT broker
5. System is ready
```

### Restart After Changes

| What Changed | What to Restart |
|-------------|-----------------|
| `config.yml` (Frigate) | `docker restart frigate` |
| `openclaw.json` | `systemctl --user restart openclaw-gateway.service` |
| `frigate-openclaw-bridge.py` | `systemctl --user restart frigate-openclaw-bridge.service` |
| `SKILL.md` | Nothing (loaded per-session) |
| `.service` file | `systemctl --user daemon-reload` then restart |
| `ha-frigate-ai-automation.yaml` | Reload automations in HA UI |

---

## 12. Security & Access Control

### Authentication Tokens

| Token | Purpose | Used By |
|-------|---------|---------|
| `899f89b02c7a6c98b2cc40ab3a038d0a7b46ca134f1e8f1a` | OpenClaw gateway auth | API access |
| `<HOOK_TOKEN>` | Webhook authentication | Bridge → OpenClaw |
| `<MQTT_USER>` / `<MQTT_PASS>` | MQTT broker auth | Frigate, Bridge |

### Access Control

- OpenClaw WhatsApp uses **allowlist** — only pre-approved numbers can interact
- Webhook endpoint requires `Authorization: Bearer` header
- OpenClaw gateway binds to LAN only (`"bind": "lan"`)
- Frigate API is localhost-only (Docker network)
- All services run as unprivileged user `<HOME_USER>` (no root)

---

## 13. Adding Future Channels

### Adding Telegram

OpenClaw supports Telegram natively. To add:

1. Enable the Telegram plugin in `openclaw.json`:
   ```json
   "plugins": {
     "entries": {
       "whatsapp": { "enabled": true },
       "telegram": { "enabled": true }
     }
   }
   ```

2. Add Telegram recipients to the bridge script `WHATSAPP_TO` list (rename to `RECIPIENTS`), or create a separate list:
   ```python
   CHANNELS = [
       {"channel": "whatsapp", "to": "+1234567890"},
       {"channel": "telegram", "to": "telegram_chat_id"},
   ]
   ```

3. Update the `send_to_openclaw()` loop to iterate over `CHANNELS`

### Adding More WhatsApp Recipients

Edit `/home/<HOME_USER>/frigate/frigate-openclaw-bridge.py`:
```python
WHATSAPP_TO = ["+1234567890", "+1234567890"]
```

Make sure new numbers are in the OpenClaw allowlist (`openclaw.json` → `channels.whatsapp.allowFrom`).

### Adding Discord / Slack / Signal

Same pattern — OpenClaw supports: `whatsapp`, `telegram`, `discord`, `slack`, `signal`, `imessage`, `msteams`, `googlechat`

---

## 14. New System Checklist

1. Install Debian + Docker + Python 3.10+.
2. Install OpenClaw and complete WhatsApp login.
3. Ensure OpenClaw gateway is running on `:18789`.
4. Ensure OpenClaw workspace exists: `~/.openclaw/workspace`.
5. Create OpenClaw media path: `~/.openclaw/workspace/ai-snapshots`.
6. Ensure sessions index exists: `~/.openclaw/agents/main/sessions/sessions.json`.
7. Install Frigate and enable snapshots in `config.yml`.
8. Run `setup-frigate-ai-prereqs.sh` and fix any warnings.
9. Run `install.sh` and follow prompts.
10. Apply Home Assistant automation YAML.
11. Enable lingering so services start at boot: `sudo loginctl enable-linger <user>`.
12. Test end-to-end by walking in front of a camera.

### API Keys And Model Selection

OpenClaw supports multiple providers. For this pipeline, **OpenAI GPT-4o-mini** is recommended for vision.

**OpenAI (Recommended)**
1. Create an API key in the OpenAI console (API Keys section).
2. Paste it into OpenClaw:

```bash
openclaw models auth paste-token --provider openai
```

3. Set the model:

```bash
openclaw models set openai/gpt-4o-mini
```

**Anthropic (Optional)**
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

## 15. Troubleshooting Guide

### Problem: No alerts at all

```bash
# 1. Is the bridge running?
systemctl --user status frigate-openclaw-bridge.service

# 2. Is it connected to MQTT?
journalctl --user -u frigate-openclaw-bridge.service -n 20
# Look for: "Connected to MQTT broker" and "Subscribed to frigate/events"

# 3. Is Frigate detecting?
# Open http://192.168.1.10:5000 → check events tab

# 4. Is Frigate sending MQTT events?
# On HA: Developer Tools → MQTT → Listen → frigate/events
```

### Problem: "Cooldown active" for everything

```bash
# Cooldown is 30s per camera. If cameras trigger often, increase it:
# Edit bridge script, change COOLDOWN_SECONDS = 60 (or desired value)
# Then restart: systemctl --user restart frigate-openclaw-bridge.service
```

### Problem: Snapshot download fails

```bash
# Test Frigate API directly
curl -s http://localhost:5000/api/events | python3 -m json.tool | head -30

# Test snapshot download (use a real event ID from above)
curl -o /tmp/test.jpg http://localhost:5000/api/events/EVENT_ID/snapshot.jpg
ls -la /tmp/test.jpg
```

### Problem: OpenClaw webhook returns error

```bash
# Test webhook manually
curl -v -X POST http://localhost:18789/hooks/agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <HOOK_TOKEN>" \
  -d '{"message": "test ping", "deliver": false}'

# Check OpenClaw logs
journalctl --user -u openclaw-gateway.service -n 50
```

### Problem: WhatsApp message not delivered

```bash
# Check bridge logs for OpenClaw response
journalctl --user -u frigate-openclaw-bridge.service --since "5 min ago"
# Look for: "OpenClaw → +1234567890 (202)" — 202 means accepted

# Verify number is in allowlist
cat ~/.openclaw/openclaw.json | python3 -m json.tool | grep -A10 allowFrom
```

### Problem: Alexa not announcing

```
1. Check HA automation is enabled: Settings → Automations
2. Check time condition: announcements only between 6 AM - 11 PM
3. Test MQTT in HA: Developer Tools → MQTT → Listen → openclaw/frigate/analysis
4. Test Alexa manually: Developer Tools → Services → notify.alexa_media
5. Check Alexa Media Player integration is connected
```

### Problem: AI says "cannot analyze image"

The model is hedging. The analysis is actually working (descriptions are accurate).
The current prompt explicitly forbids disclaimers. If it still happens:
```bash
# Check the SKILL.md is in place
cat ~/.openclaw/workspace/skills/frigate/SKILL.md

# Restart OpenClaw to pick up skill changes
systemctl --user restart openclaw-gateway.service
```

---

## 16. Appendix — All File Contents

### A. Bridge Script Location
`/home/<HOME_USER>/frigate/frigate-openclaw-bridge.py`

### B. Frigate Skill Location
`/home/<HOME_USER>/.openclaw/workspace/skills/frigate/SKILL.md`

### C. HA Automation Location
`/home/<HOME_USER>/frigate/ha-frigate-ai-automation.yaml`

### D. Systemd Service Location
`/home/<HOME_USER>/.config/systemd/user/frigate-openclaw-bridge.service`

---

*Last updated: 2026-02-07 by Claude Code + Ravi*
