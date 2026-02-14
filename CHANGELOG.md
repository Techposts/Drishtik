# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added — 3-Pillar Alert Architecture (2026-02-14)
- **Pillar 1: Structured AI Output** — Vision model (Ollama qwen2.5vl:7b) outputs structured JSON
  with subject identity/description, behavior, risk level/confidence/reason, event type, action
- **Pillar 2: Rule-Based Severity Scoring** — Deterministic `score_severity()` engine adjusts AI risk
  using time of day, camera zone, home mode, behavioral keywords, known faces.
  Score thresholds: 0-2=LOW, 3-4=MEDIUM, 5-6=HIGH, 7+=CRITICAL
- **Pillar 3: Professional WhatsApp Formatter** — `_format_whatsapp_alert()` builds structured messages
  with emoji severity (🟢🟡🟠🔴), organized sections (EVENT/SUBJECT/BEHAVIOR/RISK/CONTEXT/ACTION/MEDIA/ESCALATION)
- **Smart media decisions** — `decide_media()` selects snapshot/clip/monitoring based on risk level:
  LOW=snapshot, MEDIUM=snapshot+15s clip, HIGH=+30s+monitoring, CRITICAL=+60s+monitoring
- WhatsApp alerts include snapshot image at top and video clip at bottom (single message)

### Added — Local Vision AI with Ollama (2026-02-14)
- **Local Ollama VLM** analysis using qwen2.5vl:7b on Mac M4 Mini (192.168.1.30)
- Base64 image encoding sent directly to Ollama `/api/generate` endpoint
- Automatic fallback to OpenAI GPT-4o-mini if Ollama fails
- Structured prompt with camera context, zone, time, home mode, known faces
- JSON output parsing with 4 strategies: `JSON:` prefix, markdown code fence, bare JSON, embedded regex

### Added — Enhanced JSON Decision Parsing (2026-02-14)
- 4-strategy `parse_decision_json()` parser handles multi-line, code-fenced, and embedded JSON
- Handles both flat (`{risk:"low"}`) and structured (`{risk:{level,confidence,reason}}`) formats
- Smart `_fallback_decision()` extracts type from text keywords when JSON parsing fails
- `sanitize_decision()` normalizes all decision fields

### Added — WhatsApp Delivery Improvements (2026-02-14)
- WhatsApp filtered to **medium/high/critical only** — low-risk goes to HA/logs only
- "DELIVERY MODE" forwarding instruction prefix for OpenClaw agent
- Clip download from Frigate API (`/api/events/{id}/clip.mp4`) saved to `ai-clips/`
- Event marked for retention via Frigate API (`/api/events/{id}/retain`)
- Action execution runs BEFORE WhatsApp delivery so clip is available for attachment

### Added — Descriptive Alexa TTS (2026-02-14)
- `make_tts()` now generates full security briefings: severity, subject, behavior, risk reason, action
- Example: "Security alert from TerraceCam. Medium priority. Unknown male in dark hoodie
  approaching terrace door. Risk: unusual approach to restricted entry. Clip saved."

### Added — Structured HA Notifications (2026-02-14)
- HA automation updated with severity emoji in title (🟢🟡🟠🔴)
- Mobile notification title: `{emoji} {camera} — {RISK}`
- Importance levels mapped to risk (low=min, medium=default, high=high, critical=max)
- Structured MQTT payload includes: behavior, subject_identity, subject_description,
  camera_zone, home_mode, time_of_day, media_snapshot, media_clip, clip_url

### Added — Runtime Config: `bridge-runtime-config.json.example` template
- All settings documented with placeholder values
- Camera context notes, zone mappings, Ollama endpoint, phase toggles

### Added — Control Panel: Missing Settings & OpenClaw Integration (2026-02-14)
- **Home Assistant Settings card**: alert cooldown, fallback light entity,
  camera zone mappings, MQTT connection settings
- **Features card**: Two-Step Verification sub-settings, Event History sub-settings
- **AI Engine card**: SKILL.md editor for AI prompt management from UI
- **Camera NVR card**: Frigate API URL field
- **Admin card**: UI auth, approval requirement, audit signing key, user management
- All 13 previously hidden config keys now accessible in the UI

### Changed — Control Panel UX Audit (2026-02-14)
- Rebranded UI from "Frigate Control Panel" to "Drishtik Control Panel"
- Renamed mode toggle from "Basic/Advanced" to "Simple/Expert"
- Renamed all menu tabs for clarity
- Replaced developer jargon with user-friendly language (~70 text changes)

### Added — Phase 2: HA Tool Execution (2026-02-13)
- Bridge executes HA service calls based on decision `action` field
- Action handlers: lights, speaker/Alexa, clip save, alarm siren
- Camera-to-zone light entity mapping

### Added — Phase 1: Decision Engine (2026-02-13)
- Structured JSON decision parsing in bridge
- MQTT payload enriched with type, confidence, action, reason fields
- CRITICAL threat level support

### Changed
- Rewrote README with 3-pillar architecture, alert examples, multi-machine setup
- Updated all docs to reflect local Ollama VLM instead of cloud-only

### Fixed
- JSON parsing failures (qwen2.5vl outputs multi-line/code-block JSON)
- Clip attachment on WhatsApp (single message: snapshot top, clip bottom)
- Alexa announcements now descriptive instead of generic "Alert"
- Redacted all sensitive data from repo configs (IPs, tokens, phone numbers)

## [1.0.0] - 2026-02-07

### Added
- Full Frigate -> OpenClaw -> HA pipeline
- Interactive installers and prereq checks
- Home Assistant automation YAML
- OpenClaw installer scripts
- Redacted examples and security policy
