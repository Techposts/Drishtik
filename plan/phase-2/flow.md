# Phase 2 — Flow Diagram

```
(1) Frigate detects person
    MQTT: frigate/events
           │
           ▼
(2) Bridge downloads + stages snapshot
           │
           ▼
(3) OpenClaw agent
    Vision → Summary → JSON action
           │
           ▼
(4) Bridge reads `action`
    Map to HA service call
           │
           ▼
(5) Home Assistant executes
    - light.turn_on
    - media_player.play_media
    - notify.mobile_app
    - script.save_frigate_clip
```
