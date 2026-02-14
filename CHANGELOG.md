# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed — Severity Scoring & Alexa Alert Tuning (2026-02-14)
- **Severity scoring now trusts AI baseline** — rule engine starts from AI's risk level
  instead of always starting from 0, preventing false escalation of routine events
- Removed aggressive scoring for normal behaviors (`looking around`, `standing`, `walking`)
  which were incorrectly bumping LOW events to MEDIUM/HIGH
- Added score reduction for routine behavior keywords (walking, standing, passing)
- Known face reduction increased from -3 to -4 for stronger suppression
- Delivery type reduction increased from -1 to -2
- **Alexa now only announces medium/high/critical** — HA automation already had the filter
  but false severity escalation was triggering it on routine events

### Added — 3-Pillar Alert Architecture (2026-02-14)
- **Pillar 1: Structured AI Output** — Vision model (Ollama qwen2.5vl:7b) outputs structured JSON
  with subject identity/description, behavior, risk level/confidence/reason, event type, action
- **Pillar 2: Rule-Based Severity Scoring** — Deterministic `score_severity()` engine adjusts AI risk
  using time of day, camera zone, home mode, behavioral keywords, known faces.
  Score thresholds: 0-2=LOW, 3-4=MEDIUM, 5-6=HIGH, 7+=CRITICAL
- **Pillar 3: Professional WhatsApp Formatter** — `_format_whatsapp_alert()` builds structured messages
  with emoji severity, organized sections (EVENT/SUBJECT/BEHAVIOR/RISK/CONTEXT/ACTION/MEDIA/ESCALATION)
- **Smart media decisions** — `decide_media()` selects snapshot/clip/monitoring based on risk level:
  LOW=snapshot, MEDIUM=snapshot+15s clip, HIGH=+30s+monitoring, CRITICAL=+60s+monitoring
- WhatsApp alerts include snapshot image at top and video clip at bottom (single message)

### Added — Local Vision AI with Ollama (2026-02-14)
- **Local Ollama VLM** analysis using qwen2.5vl:7b on Mac M4 Mini
- Base64 image encoding sent directly to Ollama `/api/generate` endpoint
- Automatic fallback to OpenAI GPT-4o-mini if Ollama fails
- Structured prompt with camera context, zone, time, home mode, known faces
- JSON output parsing with 4 strategies: `JSON:` prefix, markdown code fence, bare JSON, embedded regex

### Added — Enhanced JSON Decision Parsing (2026-02-14)
- 4-strategy `parse_decision_json()` parser handles multi-line, code-fenced, and embedded JSON
- Handles both flat (`{risk:"low"}`) and structured (`{risk:{level,confidence,reason}}`) formats
- Smart `_fallback_decision()` extracts type from text keywords when JSON parsing fails

### Added — WhatsApp Delivery Improvements (2026-02-14)
- WhatsApp filtered to **medium/high/critical only** — low-risk goes to HA/logs only
- "DELIVERY MODE" forwarding instruction prefix for OpenClaw agent
- Clip download from Frigate API saved to `ai-clips/`
- Single message delivery: snapshot MEDIA at top, formatted text, clip MEDIA at bottom
- Action execution runs BEFORE WhatsApp so clip is available for attachment

### Added — Descriptive Alexa TTS (2026-02-14)
- `make_tts()` generates full security briefings with severity, subject, behavior, risk reason

### Added — Structured HA Notifications (2026-02-14)
- Severity emoji in title, importance levels mapped to risk
- Structured MQTT payload with behavior, subject, zone, home mode, media fields

### Added — Runtime Config Template (2026-02-14)
- `config/bridge-runtime-config.json.example` with all settings documented

### Added — Control Panel Updates (2026-02-14)
- Rebranded to "Drishtik Control Panel"
- Missing UI settings added (MQTT, cooldown, zones, user management)
- SKILL.md editor in UI

### Added — Phase 2: HA Tool Execution (2026-02-13)
- Bridge executes HA service calls based on decision `action` field
- Action handlers: lights, speaker/Alexa, clip save, alarm siren

### Added — Phase 1: Decision Engine (2026-02-13)
- Structured JSON decision parsing
- MQTT payload enriched with type, confidence, action, reason

### Fixed
- JSON parsing failures (qwen2.5vl outputs multi-line/code-block JSON)
- Clip attachment on WhatsApp (single message pattern)
- Alexa announcements now descriptive instead of generic "Alert"
- Redacted all sensitive data from repo configs

## [1.0.0] - 2026-02-07

### Added
- Full Frigate -> OpenClaw -> HA pipeline
- Interactive installers and prereq checks
- Home Assistant automation YAML
- OpenClaw installer scripts
- Redacted examples and security policy
