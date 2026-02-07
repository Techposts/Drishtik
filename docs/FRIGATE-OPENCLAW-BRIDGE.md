# Frigate → OpenClaw → Vision AI Security Bridge

**Date:** 2026-02-07
**Server:** 192.168.1.10 (Debian)

## Architecture

### Hardware Context

This system runs on a **12-year-old laptop** with a **Google Coral TPU (Half Mini PCIe)** installed by **replacing the WiFi card**. The TPU handles real-time detection while GPT-4o-mini handles vision analysis.

```
Frigate (Coral TPU)          OpenClaw Gateway           Notifications
┌──────────────┐            ┌──────────────────┐       ┌──────────────┐
│ Person detect │──MQTT──→  │ Bridge Script     │       │ WhatsApp     │
│ on camera     │           │  ↓ download snap  │──→    │ (snap+text)  │
│               │           │  ↓ POST webhook   │       ├──────────────┤
│ 3 cameras:    │           │  ↓ GPT-4o-mini    │       │ Alexa TTS    │
│  GarageCam    │           │    vision analyze  │──→    │ (4 Echos)    │
│  TopStairCam  │           │  ↓ publish MQTT   │       ├──────────────┤
│  TerraceCam   │           └──────────────────┘       │ HA Dashboard  │
└──────────────┘                                        └──────────────┘
```

### Pipeline Flow

1. Frigate detects a **person** via Coral TPU on any camera
2. Frigate publishes event to MQTT topic `frigate/events`
3. Bridge script receives the event, filters for `type=new` + `label=person`
4. Bridge waits 3 seconds, then downloads snapshot from Frigate API
5. Snapshot saved to `/home/<HOME_USER>/frigate/storage/ai-snapshots/{event_id}.jpg`
6. Bridge **copies the snapshot into OpenClaw workspace** at `/home/<HOME_USER>/.openclaw/workspace/ai-snapshots/{event_id}.jpg`
7. Bridge POSTs to OpenClaw webhook (`/hooks/agent`) with the snapshot path
8. OpenClaw uses **GPT-4o-mini vision** + the Frigate skill to analyze the image
9. Analysis + **snapshot image** delivered to **WhatsApp** via `MEDIA:./.openclaw/workspace/ai-snapshots/{event_id}.jpg`
10. Bridge publishes **immediate MQTT notice** ("analysis pending") to `openclaw/frigate/analysis`
11. Bridge publishes **final MQTT analysis** to `openclaw/frigate/analysis` (same event_id)
12. **Home Assistant** picks up MQTT → announces via **Alexa** + dashboard notification (auto-updates)

---

## Files & Locations

| File | Purpose |
|------|---------|
| `/home/<HOME_USER>/frigate/config.yml` | Frigate config (snapshots enabled, 7-day retention) |
| `/home/<HOME_USER>/.openclaw/openclaw.json` | OpenClaw config (hooks section added) |
| `/home/<HOME_USER>/frigate/frigate-openclaw-bridge.py` | Bridge script (main logic) |
| `/home/<HOME_USER>/.openclaw/workspace/skills/frigate/SKILL.md` | OpenClaw skill for analyzing security snapshots |
| `/home/<HOME_USER>/.config/systemd/user/frigate-openclaw-bridge.service` | Systemd user service |
| `/home/<HOME_USER>/frigate/bridge-venv/` | Python venv (paho-mqtt, requests) |
| `/home/<HOME_USER>/frigate/storage/ai-snapshots/` | Saved snapshot images |
| `/home/<HOME_USER>/.openclaw/workspace/ai-snapshots/` | Staged snapshots for WhatsApp media |
| `/home/<HOME_USER>/frigate/ha-frigate-ai-automation.yaml` | HA automation YAML (Alexa + notifications) |

---

## Services

All run as **user-level systemd services** (no root needed).

| Service | Command |
|---------|---------|
| Frigate | `docker restart frigate` |
| OpenClaw Gateway | `systemctl --user restart openclaw-gateway.service` |
| Bridge | `systemctl --user restart frigate-openclaw-bridge.service` |

### Common Service Commands

```bash
# Check status
systemctl --user status frigate-openclaw-bridge.service

# View logs (live)
journalctl --user -u frigate-openclaw-bridge.service -f

# Restart
systemctl --user restart frigate-openclaw-bridge.service

# Stop
systemctl --user stop frigate-openclaw-bridge.service

# Disable auto-start
systemctl --user disable frigate-openclaw-bridge.service
```

---

## Configuration Details

### Frigate Snapshots (config.yml)

```yaml
snapshots:
  enabled: true
  retain:
    default: 7   # days
```

### OpenClaw Hooks (openclaw.json)

```json
"hooks": {
  "enabled": true,
  "token": "<HOOK_TOKEN>",
  "path": "/hooks"
}
```

### Bridge Script Settings

| Setting | Value |
|---------|-------|
| MQTT Broker | 192.168.1.20:1885 |
| MQTT Credentials | <MQTT_USER> / <MQTT_PASS> |
| Subscribe Topic | `frigate/events` |
| Publish Topic | `openclaw/frigate/analysis` |
| Frigate API | http://localhost:5000 |
| OpenClaw Webhook | http://localhost:18789/hooks/agent |
| Webhook Token | `<HOOK_TOKEN>` |
| WhatsApp To | +1234567890 |
| Cooldown | 30 seconds per camera |
| Snapshot delay | 3 seconds (wait for Frigate to save) |
| OpenClaw media path | `MEDIA:./.openclaw/workspace/ai-snapshots/{event_id}.jpg` |

---

## MQTT Payload Format

The bridge publishes to `openclaw/frigate/analysis` **twice per event**:
- First: immediate `"analysis pending"` notice
- Second: final AI analysis (same `event_id`)

**Pending payload example:**

```json
{
  "camera": "Tapo-GarageCam",
  "label": "person",
  "analysis": "Person detected on Tapo-GarageCam — vision analysis pending.",
  "tts": "Security alert, Tapo-GarageCam. Person detected on Tapo-GarageCam — vision analysis pending.",
  "timestamp": "2026-02-07T08:30:00+00:00",
  "event_id": "1738920600.123456-abc123",
  "snapshot_path": "/home/<HOME_USER>/frigate/storage/ai-snapshots/1738920600.123456-abc123.jpg"
}
```

**Final payload example:**

```json
{
  "camera": "Tapo-GarageCam",
  "label": "person",
  "analysis": "[Tapo-GarageCam] Threat: LOW\nOne person in casual clothes...",
  "tts": "Security alert, Tapo-GarageCam. One person in casual clothes walking through driveway.",
  "timestamp": "2026-02-07T08:30:00+00:00",
  "event_id": "1738920600.123456-abc123",
  "snapshot_path": "/home/<HOME_USER>/frigate/storage/ai-snapshots/1738920600.123456-abc123.jpg"
}
```

- `analysis` — full text (for dashboard/notifications)
- `tts` — short spoken version (for Alexa, 1-2 sentences)

---

## Troubleshooting

### Bridge not connecting to MQTT

```bash
journalctl --user -u frigate-openclaw-bridge.service -n 50
# Look for "Connected to MQTT broker" or connection errors
```

### No snapshots being saved

```bash
# Check if Frigate snapshots are enabled
docker exec frigate cat /config/config.yml | grep -A3 snapshots

# Check if snapshots directory has files
ls -la /home/<HOME_USER>/frigate/storage/ai-snapshots/

# Test Frigate API directly (replace EVENT_ID with a real one)
curl http://localhost:5000/api/events | python3 -m json.tool | head -30
```

### OpenClaw webhook not responding

```bash
# Test webhook manually
curl -X POST http://localhost:18789/hooks/agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <HOOK_TOKEN>" \
  -d '{"message": "test", "deliver": false}'
```

### WhatsApp message shows path instead of attachment

OpenClaw **blocks absolute paths** in `MEDIA:` for security. The bridge now uses:

```
MEDIA:./.openclaw/workspace/ai-snapshots/<event_id>.jpg
```

If you still see a path, verify the staged file exists:

```bash
ls -la /home/<HOME_USER>/.openclaw/workspace/ai-snapshots/
```

### Python dependency issues

```bash
# Reinstall venv
rm -rf /home/<HOME_USER>/frigate/bridge-venv
python3 -m venv /home/<HOME_USER>/frigate/bridge-venv
/home/<HOME_USER>/frigate/bridge-venv/bin/pip install paho-mqtt requests
systemctl --user restart frigate-openclaw-bridge.service
```
