# Phase 2 — Home Assistant Tool Execution (Detailed Plan)

## Goal
Execute **OpenClaw decisions** via Home Assistant **service calls**, while keeping safety boundaries:

**OpenClaw decides → Bridge executes → Home Assistant acts**

No direct LLM access to HA.

---

## Outcome (What Changes)

**Before**
- Actions are published only (no device control).

**After**
- Bridge maps `action` → HA service calls.
- HA executes light/speaker/clip/notification actions.

---

## Architecture (Phase 2)

```
Frigate → Detection (MQTT)
        ↓
Bridge → Snapshot + OpenClaw
        ↓
OpenClaw → JSON action
        ↓
Bridge → HA REST service calls
        ↓
Home Assistant → Devices / Automations
```

---

## Action → HA Service Mapping

| Action | HA Service | Example |
|--------|------------|---------|
| notify_only | notify.mobile_app | message + snapshot |
| notify_and_save_clip | script.save_frigate_clip | camera + duration |
| notify_and_light | light.turn_on | entity_id or area |
| notify_and_speaker | media_player.play_media | TTS message |
| notify_and_alarm | switch.turn_on | siren / alarm |

**Note:** Only actions in this allowlist are executed.

---

## Tools To Expose (Start Small)

1. `turn_light(zone)`
2. `announce_speaker(message)`
3. `save_frigate_clip(camera, seconds)`
4. `set_alert_mode(level)`
5. `send_notification(channel)`

---

## Bridge Responsibilities (Phase 2)

- Read `action` from JSON
- Map to HA REST service call
- Retry once on failure
- Log success/failure
- Fallback to `notify_only` if any call fails

---

## Home Assistant Requirements

- Long‑lived access token
- Entities for:
  - Lights (or area)
  - Speaker (Alexa / media_player)
  - Alarm / siren switch (optional)
  - Script for clip saving

---

## HA REST Examples

```http
POST /api/services/light/turn_on
Authorization: Bearer <HA_TOKEN>

{ "entity_id": "light.garage" }
```

```http
POST /api/services/notify/mobile_app
Authorization: Bearer <HA_TOKEN>

{ "message": "Person detected", "title": "Security" }
```

---

## Safety Rules

- No direct LLM → HA
- Only pre‑approved actions
- If `risk=low` always force `notify_only`
- If time is quiet hours, ignore speaker action unless `critical`

---

## Test Plan (Phase 2)

1. Force action = `notify_only`
2. Force action = `notify_and_light`
3. Force action = `notify_and_speaker`
4. Force action = `notify_and_save_clip`
5. Force action = `notify_and_alarm`

Verify logs and HA device state.

---

## Phase 2 Done When

- Actions execute reliably from HA
- No accidental device triggers
- Logs show action mapping + success/failure

