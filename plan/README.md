# Roadmap Plan

This folder contains the step-by-step implementation plan, broken by phase.

## Phases (Core)

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | [Decision Engine](phase-1/README.md) — Structured JSON from AI | Done |
| 2 | [HA Tool Execution](phase-2/README.md) — Lights, clips, alarm via HA REST | Done |
| 3 | [Policy Layer](phase-3/README.md) — Camera context, zones, time, home mode | Done |
| 3.5 | [Known Faces](phase-3-5/README.md) — Face recognition to suppress routine alerts | Planned |
| 4 | [Memory Store](phase-4/README.md) — JSONL event history for pattern awareness | Done |
| 5 | [Multi-Step Reasoning](phase-5/README.md) — Re-confirm high/critical with second pass | Done |
| 8 | [Summaries & Reports](phase-8/README.md) — Daily/weekly reports, trends | Done |

## Recently Completed (2026-02-14)

- **3-Pillar Alert Architecture**: Structured AI JSON, Rule-based severity scoring, Professional WhatsApp formatting
- **Local Ollama VLM**: qwen2.5vl:7b on Mac M4 Mini for zero-cloud-dependency vision analysis
- **Enhanced JSON Parsing**: 4-strategy parser for multi-line/code-fenced AI output
- **WhatsApp Media**: Snapshot + clip attachment, medium+ risk filtering
- **Descriptive Alexa TTS**: Full security briefings instead of generic "Alert"
- **Structured HA Notifications**: Emoji severity, importance levels, structured MQTT payload

## Optional / Advanced (High Complexity)

- **Phase 6 — Multi-Camera Correlation**
  - [plan/phase-6/](phase-6/README.md)
- **Phase 7 — Conversation Mode**
  - [plan/phase-7/](phase-7/README.md)

These are intentionally **not part of the core roadmap** due to complexity vs. impact.
