# Phase 1 — Decision Engine (Detailed Plan)

## Goal
Make OpenClaw a **decision maker** (not just a narrator). The output must be **structured, machine‑readable** and include a recommended action. **No device control yet** — actions are only published to MQTT.

---

## Outcome (What Changes)

**Before**
- OpenClaw returns a human‑readable summary only.
- HA receives analysis text only.

**After**
- OpenClaw returns **analysis text + structured JSON decision**.
- Bridge publishes **risk, type, confidence, action** to MQTT.
- HA can display/route based on `action` (but **no device control** yet).

---

## Architecture (Phase 1)

```
Frigate → Detection (MQTT: frigate/events)
        ↓
Bridge → Snapshot download + staging
        ↓
OpenClaw (GPT‑4o‑mini vision)
        ↓
Decision Output (JSON)
        ↓
Bridge publishes to MQTT (openclaw/frigate/analysis)
        ↓
Home Assistant (notifications only)
```

---

## Decision Output Schema (Strict JSON)

```json
{
  "risk": "low|medium|high|critical",
  "type": "unknown_person|known_person|delivery|vehicle|animal|loitering|other",
  "confidence": 0.00,
  "action": "notify_only|notify_and_save_clip|notify_and_light|notify_and_speaker|notify_and_alarm",
  "reason": "short explanation of why the action was chosen"
}
```

**Rules:**
- `confidence` = 0.00–1.00
- `action` must map 1:1 to your future HA tool calls
- `reason` should be < 120 chars

---

## Action Mapping (Phase 1)

| Risk | Action | Meaning |
|------|--------|---------|
| low | notify_only | Inform user only |
| medium | notify_and_save_clip | Notify + mark clip for saving |
| high | notify_and_light | Notify + turn on lights |
| critical | notify_and_alarm | Notify + alarm/siren |

**Note:** In Phase 1, only `notify_only` will be executed. Others are just published.

---

## Prompt Contract (What OpenClaw Must Produce)

OpenClaw must return:

1. **MEDIA line** (for WhatsApp attachment)
2. **Human summary** (3–5 sentences)
3. **Strict JSON block**

Example response format:

```
MEDIA:./.openclaw/workspace/ai-snapshots/<event_id>.jpg

[Tapo-GarageCam] Threat: MEDIUM
One person stands near the garage entry. No face is clearly visible. No tools or forced entry seen. Recommend monitoring.

JSON:
{"risk":"medium","type":"unknown_person","confidence":0.78,"action":"notify_and_save_clip","reason":"Unknown person near entry"}
```

---

## Bridge Responsibilities (Phase 1)

- Parse JSON from OpenClaw response
- Validate schema
- Publish to MQTT as fields:
  - `risk`
  - `type`
  - `confidence`
  - `action`
  - `reason`
- If JSON missing/invalid → fallback to `risk=low`, `action=notify_only`

---

## Home Assistant (Phase 1)

- Display `risk` and `action` in notification
- No service calls yet

---

## Observability & Debug

- Log raw OpenClaw output (last 200 chars)
- Log parsed JSON
- Log fallback reason when JSON invalid

---

## Test Plan (Phase 1)

1. Trigger a known person (low risk)
2. Trigger unknown person (medium/high risk)
3. Verify MQTT payload contains JSON fields
4. Verify WhatsApp message still includes media + summary
5. Verify HA notification shows `risk` + `action`

---

## Phase 1 Done When

- OpenClaw always returns structured JSON
- Bridge parses and publishes fields to MQTT
- HA sees risk + action values
- No device actions yet

---

## Files To Update (When Implementing)

- Bridge script
- OpenClaw skill prompt
- HA automation (optional display only)

---

## Pros / Cons / Recommendation

**Pros**
- Biggest impact for clarity and automation
- Low risk (no device control yet)
- Makes all future phases possible

**Cons**
- Requires strict JSON enforcement in prompts
- Needs robust parsing + fallback

**Recommendation:** **Do this first. Mandatory.**
