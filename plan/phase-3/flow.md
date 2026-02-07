# Phase 3 — Flow Diagram

```
(1) Frigate detects person
           │
           ▼
(2) Bridge pulls context
    - time_of_day
    - home_mode
    - known_faces_present
    - camera_zone
    - recent_events
           │
           ▼
(3) OpenClaw prompt
    includes POLICY block
           │
           ▼
(4) OpenClaw decision
    applies policy + returns JSON
           │
           ▼
(5) Bridge publishes action
    and executes via HA (Phase 2)
```
