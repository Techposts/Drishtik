# Phase 1 — Flow Diagram

```
(1) Frigate detects person
    MQTT: frigate/events
           │
           ▼
(2) Bridge downloads snapshot
    Saves: /frigate/storage/ai-snapshots/<event_id>.jpg
    Stages: ~/.openclaw/workspace/ai-snapshots/<event_id>.jpg
           │
           ▼
(3) OpenClaw webhook
    POST /hooks/agent
    Prompt includes MEDIA line + JSON output rules
           │
           ▼
(4) OpenClaw agent
    Vision analysis → summary → JSON decision
           │
           ▼
(5) Bridge parses JSON
    Adds: risk/type/confidence/action
           │
           ▼
(6) MQTT publish
    openclaw/frigate/analysis (pending → final)
           │
           ▼
(7) Home Assistant
    Notification shows action + risk
```
