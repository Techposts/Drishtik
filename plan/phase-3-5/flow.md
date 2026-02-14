# Phase 3.5 — Known Faces Recognition (Flow)

```
Frigate Event
  ↓
Snapshot Downloaded
  ↓
Face Detection + Embedding (InsightFace / face_recognition)
  ↓
Compare to Known Face DB (threshold)
  ↓
known_face / person_name / face_confidence
  ↓
Bridge adds fields to MQTT payload
  ↓
OpenClaw Policy Layer
  ↓
Decision (notify / suppress / escalate)
```

## Data Added to Payload

```
"known_face": true,
"person_name": "Ravi",
"face_confidence": 0.83
```

## Example Policy Use

- If `known_face=true` AND `risk=low` → suppress WhatsApp/Alexa
- If `known_face=true` AND `risk=medium|high` → notify normally
- If `known_face=true` AND `time_of_day` outside policy → escalate

