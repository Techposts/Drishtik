# Phase 3 — Policy Layer (Context-Aware Decisions)

## Goal
Decisions adapt to **context**: time, home mode, known faces, zones, recent activity. OpenClaw still decides; bridge still executes.

---

## Outcome (What Changes)

**Before**
- Decisions based only on image content.

**After**
- Decisions incorporate policy variables, producing different actions for the same visual input.

---

## Policy Inputs (Context Variables)

Send these alongside the snapshot prompt:

- `time_of_day`: day / evening / night
- `home_mode`: home / away / night
- `known_faces_present`: true / false
- `camera_zone`: entry / driveway / garage / backyard
- `recent_events`: count + last timestamp

---

## Policy Rules (Examples)

- After 11pm → increase risk by 1 level
- `home_mode=away` → escalate by 1 level
- `known_faces_present=true` → reduce risk by 1 level
- `delivery_hours` (9am–8pm) → lower risk for unknown person near gate
- Repeated detections within 5 min → increase risk

---

## Prompt Contract

OpenClaw must:
1. Describe the scene
2. Apply policy variables
3. Output the **final JSON** decision

---

## Bridge Responsibilities

- Fetch policy variables from HA or local config
- Attach them to OpenClaw prompt
- Log the policy inputs used

---

## Example Context Block

```
POLICY:
- time_of_day: night
- home_mode: away
- known_faces_present: false
- camera_zone: entry
- recent_events: 3 in last 10 minutes
```

---

## Test Plan

1. Simulate `home_mode=home` vs `away`
2. Simulate day vs night
3. Verify `risk` changes predictably
4. Confirm no policy inputs = safe defaults

---

## Phase 3 Done When

- Policy inputs are attached to every prompt
- Decisions change based on policy inputs
- Logs show policy values for every event

