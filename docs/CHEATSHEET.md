# Cheat Sheet — Drishtik (Frigate + Ollama + OpenClaw + HA)

## Core Services

| Service | What | Restart Command |
|---------|------|-----------------|
| Frigate (Docker) | Detection + snapshots | `docker restart frigate` |
| OpenClaw (systemd user) | AI gateway + messaging | `systemctl --user restart openclaw-gateway.service` |
| Bridge (systemd user) | MQTT -> Ollama -> OpenClaw -> MQTT | `systemctl --user restart frigate-openclaw-bridge.service` |
| Home Assistant | Automations + Alexa | Restart via HA UI |

---

## Key Files

| File | Purpose |
|------|---------|
| `frigate-openclaw-bridge.py` | Main bridge script |
| `bridge-runtime-config.json` | All runtime settings |
| `config.yml` | Frigate NVR config |
| `~/.openclaw/openclaw.json` | OpenClaw gateway config |
| `~/.openclaw/workspace/skills/frigate/SKILL.md` | AI analysis + delivery instructions |
| `storage/events-history.jsonl` | Phase 4 event memory |
| `storage/ai-snapshots/` | Saved detection snapshots |
| `storage/ai-clips/` | Saved video clips |

---

## Logs

```bash
# Bridge logs (live)
journalctl --user -u frigate-openclaw-bridge.service -f

# Bridge logs (last 50 lines)
journalctl --user -u frigate-openclaw-bridge.service -n 50

# OpenClaw logs
journalctl --user -u openclaw-gateway.service -f

# Frigate logs
docker logs -f frigate
```

---

## MQTT Topics

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `frigate/events` | Frigate -> Bridge | Person detection events |
| `openclaw/frigate/analysis` | Bridge -> HA | AI analysis results |

---

## MQTT Payload Fields (openclaw/frigate/analysis)

| Field | Description |
|-------|-------------|
| `camera` | Camera name |
| `risk` | `low` / `medium` / `high` / `critical` |
| `type` | `known_person` / `unknown_person` / `delivery` / `other` |
| `confidence` | 0.0 - 1.0 |
| `analysis` | Full structured text for HA dashboard |
| `tts` | Descriptive spoken text for Alexa |
| `behavior` | What the person is doing |
| `subject_identity` | Known/Unknown |
| `subject_description` | Appearance description |
| `camera_zone` | Zone type (garage, terrace, stairs) |
| `home_mode` | Home/Away/Sleep/Guest |
| `media_snapshot` | true/false |
| `media_clip` | true/false |
| `clip_url` | URL to clip on Frigate API |
| `event_id` | Frigate event identifier |

---

## WhatsApp Alert Flow

1. Frigate detects person -> MQTT event
2. Bridge downloads snapshot from Frigate API
3. Bridge sends snapshot to Ollama (local VLM) for analysis
4. Bridge parses structured JSON decision
5. Rule engine adjusts severity score
6. If medium+: formats professional WhatsApp alert
7. Snapshot at top, formatted text, clip at bottom
8. Sent via OpenClaw `/hooks/agent` with DELIVERY MODE prefix

---

## Severity Scoring Rules

| Factor | Score Change |
|--------|-------------|
| Unknown person type | +2 |
| Evening/night time | +2 |
| Entry zone (terrace, garage, door) | +1 |
| Home mode: away | +3 |
| Suspicious keywords (loitering, concealment) | +2 to +3 |
| Known faces present | -3 |

Thresholds: 0-2=LOW, 3-4=MEDIUM, 5-6=HIGH, 7+=CRITICAL

---

## Quick Debug Flow

1. Check Frigate is detecting: `http://<server>:5000`
2. Check bridge logs for Ollama calls and JSON parsing
3. Check MQTT payload in HA Developer Tools -> MQTT -> Listen
4. Check OpenClaw logs for WhatsApp delivery
5. Verify snapshot exists: `ls storage/ai-snapshots/`
6. Verify clip exists: `ls storage/ai-clips/`

---

## Runtime Config Changes

Edit `bridge-runtime-config.json` and restart:
```bash
systemctl --user restart frigate-openclaw-bridge.service
```

No need to restart OpenClaw unless you changed `openclaw.json`.

SKILL.md changes take effect on next agent session (no restart needed).

---

## Ollama (Local VLM)

```bash
# Check Ollama is running
curl http://<OLLAMA_HOST>:11434/api/tags

# Pull/update model
ollama pull qwen2.5vl:7b

# Test vision analysis
curl http://<OLLAMA_HOST>:11434/api/generate \
  -d '{"model":"qwen2.5vl:7b","prompt":"describe this image","images":["<base64>"]}'
```
