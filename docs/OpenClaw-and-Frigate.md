# OpenClaw And Frigate — Redacted Summary

This file replaces the original session transcript, which contained private information.

## Summary

This system integrates Frigate (person detection) with OpenClaw (GPT-4o-mini vision) to deliver:

- WhatsApp image + analysis
- Home Assistant notifications (pending → final)
- Alexa announcements for higher risk

### Core Flow

1. Frigate publishes `frigate/events` to MQTT.
2. Bridge script downloads the snapshot from Frigate API.
3. Snapshot is staged into OpenClaw workspace for WhatsApp media delivery.
4. Bridge sends a webhook to OpenClaw (`/hooks/agent`).
5. OpenClaw runs GPT-4o-mini vision analysis.
6. WhatsApp receives image + analysis.
7. MQTT gets immediate pending + final analysis for HA updates.

### Files (examples)

- `scripts/frigate-openclaw-bridge.py`
- `scripts/setup-frigate-ai.sh`
- `scripts/setup-frigate-ai-prereqs.sh`
- `config/ha-frigate-ai-automation.yaml`
- `docs/SECURITY-AI-SYSTEM-COMPLETE.md`

If you need the full original transcript, see `github_sensitive/docs/OpenClaw-and-Frigate.md`.
