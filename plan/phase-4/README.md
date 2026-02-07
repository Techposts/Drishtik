# Phase 4 — Memory Store (Event History)

## Goal
Add simple memory so decisions can reference **recent history** without a vector DB.

---

## Outcome
- Every event logged in a JSON file
- OpenClaw can reason about repetition and patterns

---

## Data Model (events.json)

```json
{
  "timestamp": "2026-02-07T12:30:00Z",
  "camera": "Tapo-GarageCam",
  "risk": "medium",
  "action": "notify_and_save_clip",
  "type": "unknown_person",
  "confidence": 0.78
}
```

Store as append‑only list or JSONL.

---

## Prompt Usage

OpenClaw gets a summary block:

```
RECENT_EVENTS:
- 3 events in last 30 min (Garage)
- last event 7 min ago
```

---

## Test Plan

1. Trigger multiple events
2. Verify memory file updated
3. Verify risk decreases for repeated known patterns

---

## Done When

- Memory file is updated per event
- Prompt includes recent events summary
- Decisions reflect repetition

