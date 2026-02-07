# Phase 6 — Multi-Camera Correlation

## Goal
Infer movement across cameras and reduce duplicate alerts.

---

## Outcome
- Correlate detections across cameras within a time window
- OpenClaw reports a movement path instead of separate alerts

---

## Inputs
- timestamps
- camera IDs
- clothing/appearance hints
- zone order (topology)

---

## Test Plan

- Walk through 2 cameras in sequence
- Verify OpenClaw outputs a single correlated narrative

---

## Done When

- Agent can infer “person moved from A → B”
- Duplicate alerts reduced

---

## Pros / Cons / Recommendation

**Pros**
- Great for multi-camera environments
- Reduces duplicate alerts

**Cons**
- High complexity (identity correlation is hard)
- Error-prone without strong appearance signals

**Recommendation:** **Skip for now. Advanced feature.**
