# Phase 5 — Multi-Step Reasoning

## Goal
Reduce false alarms by adding **confirmation steps** before high-risk actions.

---

## Outcome
- OpenClaw can request a second frame/crop
- Final decision based on confirmation

---

## Example Flow

1. Initial vision: suspicious
2. Bridge fetches secondary frame or crop
3. OpenClaw re-checks and confirms
4. Action escalates only if confirmed

---

## Test Plan

- Simulate borderline detections
- Verify second pass prevents false escalation

---

## Done When

- High/critical actions require confirmation
- False positives reduced at night

---

## Pros / Cons / Recommendation

**Pros**
- Directly reduces false positives before escalation
- Increases trust in automation

**Cons**
- Adds latency (extra 3–10s)
- More complex to implement (extra frame fetch)

**Recommendation:** **High value if you see night false positives. Otherwise optional.**
