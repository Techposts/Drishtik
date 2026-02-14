#!/usr/bin/env python3
"""
Frigate → OpenClaw Bridge
Listens for Frigate person-detection events via MQTT, downloads the snapshot,
sends it to OpenClaw for GPT-4o-mini vision analysis, and publishes the
analysis back to MQTT for Home Assistant.
"""

import json
import base64
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import shutil

import paho.mqtt.client as mqtt
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MQTT_HOST = "192.168.1.20"
MQTT_PORT = 1885
MQTT_USER = "<MQTT_USER>"
MQTT_PASS = "<MQTT_PASS>"
MQTT_TOPIC_SUBSCRIBE = "frigate/events"
MQTT_TOPIC_PUBLISH = "openclaw/frigate/analysis"

FRIGATE_API = "http://localhost:5000"
OPENCLAW_ANALYSIS_WEBHOOK = os.getenv("OPENCLAW_ANALYSIS_WEBHOOK", "http://localhost:18789/hooks/agent")
OPENCLAW_DELIVERY_WEBHOOK = os.getenv("OPENCLAW_DELIVERY_WEBHOOK", "http://localhost:18789/hooks/agent")
OPENCLAW_TOKEN = "<HOOK_TOKEN>"
OPENCLAW_ANALYSIS_AGENT_NAME = os.getenv("OPENCLAW_ANALYSIS_AGENT_NAME", "main")
OPENCLAW_DELIVERY_AGENT_NAME = os.getenv("OPENCLAW_DELIVERY_AGENT_NAME", "main")
OPENCLAW_ANALYSIS_MODEL = os.getenv("OPENCLAW_ANALYSIS_MODEL", "litellm/qwen2.5vl:7b")
OPENCLAW_ANALYSIS_MODEL_FALLBACK = os.getenv("OPENCLAW_ANALYSIS_MODEL_FALLBACK", "openai/gpt-4o-mini")
OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK = os.getenv("OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK", "http://localhost:18789/hooks/agent")
OPENCLAW_SESSIONS_DIR = Path(f"/home/<HOME_USER>/.openclaw/agents/{OPENCLAW_ANALYSIS_AGENT_NAME}/sessions")
OPENCLAW_SESSIONS_INDEX = OPENCLAW_SESSIONS_DIR / "sessions.json"

OLLAMA_API = os.getenv("OLLAMA_API", "http://<OLLAMA_HOST>:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")

SNAPSHOT_DIR = Path("/home/<HOME_USER>/frigate/storage/ai-snapshots")
OPENCLAW_WORKSPACE = Path("/home/<HOME_USER>/.openclaw/workspace")
OPENCLAW_MEDIA_DIR = OPENCLAW_WORKSPACE / "ai-snapshots"
WHATSAPP_TO = ["+1234567890"]
WHATSAPP_ENABLED = True

COOLDOWN_SECONDS = 30  # minimum gap between alerts per camera

# ---------------------------------------------------------------------------
# Home Assistant REST API (Phase 2 — action execution)
# ---------------------------------------------------------------------------
HA_URL = "http://<HA_HOST>:8123"
HA_TOKEN = "<HA_LONG_LIVED_TOKEN>"

# Camera → zone entity mapping (update entity_ids to match your HA setup)
CAMERA_ZONE_LIGHTS: dict[str, list[str]] = {
    "GarageCam":    ["light.garage"],
    "TopStairCam":  ["light.stairway"],
    "TerraceCam":   ["light.terrace"],
}
CAMERA_ZONE_LIGHTS_DEFAULT = ["light.garage"]  # fallback if camera not mapped

# Phase 3 policy context sources (safe defaults if entities are missing)
HA_HOME_MODE_ENTITY = "input_select.home_mode"
HA_KNOWN_FACES_ENTITY = "binary_sensor.known_faces_present"
EXCLUDE_KNOWN_FACES = False
CAMERA_CONTEXT_NOTES: dict[str, str] = {
    "GarageCam": "Garage entry + home entrance zone",
    "TopStairCam": "Outside main door stair area",
    "TerraceCam": "Inside door stair/landing area",
}
CAMERA_POLICY_ZONES: dict[str, str] = {
    "GarageCam": "garage",
    "TopStairCam": "entry",
    "TerraceCam": "backyard",
}
CAMERA_POLICY_ZONE_DEFAULT = "entry"
RECENT_EVENTS_WINDOW_SECONDS = 600  # 10 minutes
EVENT_HISTORY_FILE = Path("/home/<HOME_USER>/frigate/storage/events-history.jsonl")
EVENT_HISTORY_WINDOW_SECONDS = 1800  # 30 minutes
EVENT_HISTORY_MAX_LINES = 5000

# Phase 5 confirmation (multi-step reasoning)
PHASE5_CONFIRM_ENABLED = True
PHASE5_CONFIRM_DELAY_SECONDS = 4
PHASE5_CONFIRM_TIMEOUT_SECONDS = 90
PHASE5_CONFIRM_RISKS = {"high", "critical"}

# Runtime feature toggles
PHASE3_ENABLED = True
PHASE4_ENABLED = True
PHASE8_ENABLED = True

# Runtime config file (editable by control UI/API)
RUNTIME_CONFIG_FILE = Path("/home/<HOME_USER>/frigate/bridge-runtime-config.json")
SECRETS_ENV_FILE = Path("/home/<HOME_USER>/frigate/.secrets.env")

# Alarm / siren entity (optional — used by notify_and_alarm)
ALARM_ENTITY = "switch.security_siren"

# Quiet hours — suppress speaker actions unless critical
QUIET_HOURS_START = 23  # 11 PM
QUIET_HOURS_END = 6     # 6 AM

# Allowed actions whitelist
ALLOWED_ACTIONS = {
    "notify_only",
    "notify_and_save_clip",
    "notify_and_light",
    "notify_and_speaker",
    "notify_and_alarm",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("frigate-bridge")


def _load_runtime_config():
    """Load runtime overrides from JSON config file."""
    if not RUNTIME_CONFIG_FILE.exists():
        return
    try:
        cfg = json.loads(RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed loading runtime config %s: %s", RUNTIME_CONFIG_FILE, exc)
        return

    def _cfg(name, default):
        return cfg.get(name, default)

    def _looks_masked_secret(val) -> bool:
        s = str(val or "").strip()
        return s.startswith("********")

    global MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS
    global MQTT_TOPIC_SUBSCRIBE, MQTT_TOPIC_PUBLISH
    global FRIGATE_API
    global OPENCLAW_ANALYSIS_WEBHOOK, OPENCLAW_DELIVERY_WEBHOOK
    global OPENCLAW_TOKEN, OPENCLAW_ANALYSIS_AGENT_NAME, OPENCLAW_DELIVERY_AGENT_NAME
    global OPENCLAW_ANALYSIS_MODEL, OPENCLAW_ANALYSIS_MODEL_FALLBACK, OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK
    global OPENCLAW_SESSIONS_DIR, OPENCLAW_SESSIONS_INDEX
    global OLLAMA_API, OLLAMA_MODEL
    global WHATSAPP_TO, WHATSAPP_ENABLED, COOLDOWN_SECONDS
    global HA_URL, HA_TOKEN, CAMERA_ZONE_LIGHTS, CAMERA_ZONE_LIGHTS_DEFAULT
    global ALARM_ENTITY, QUIET_HOURS_START, QUIET_HOURS_END
    global HA_HOME_MODE_ENTITY, HA_KNOWN_FACES_ENTITY, EXCLUDE_KNOWN_FACES, CAMERA_CONTEXT_NOTES
    global CAMERA_POLICY_ZONES, CAMERA_POLICY_ZONE_DEFAULT, RECENT_EVENTS_WINDOW_SECONDS
    global EVENT_HISTORY_FILE, EVENT_HISTORY_WINDOW_SECONDS, EVENT_HISTORY_MAX_LINES
    global PHASE5_CONFIRM_ENABLED, PHASE5_CONFIRM_DELAY_SECONDS
    global PHASE5_CONFIRM_TIMEOUT_SECONDS, PHASE5_CONFIRM_RISKS
    global PHASE3_ENABLED, PHASE4_ENABLED, PHASE8_ENABLED
    global PHASE5_CONFIRM_ENABLED

    MQTT_HOST = str(_cfg("mqtt_host", MQTT_HOST))
    MQTT_PORT = int(_cfg("mqtt_port", MQTT_PORT))
    MQTT_USER = str(_cfg("mqtt_user", MQTT_USER))
    _mqtt_pass = _cfg("mqtt_pass", MQTT_PASS)
    if not _looks_masked_secret(_mqtt_pass):
        MQTT_PASS = str(_mqtt_pass)
    MQTT_TOPIC_SUBSCRIBE = str(_cfg("mqtt_topic_subscribe", MQTT_TOPIC_SUBSCRIBE))
    MQTT_TOPIC_PUBLISH = str(_cfg("mqtt_topic_publish", MQTT_TOPIC_PUBLISH))
    FRIGATE_API = str(_cfg("frigate_api", FRIGATE_API))

    OPENCLAW_ANALYSIS_WEBHOOK = str(_cfg("openclaw_analysis_webhook", OPENCLAW_ANALYSIS_WEBHOOK))
    OPENCLAW_DELIVERY_WEBHOOK = str(_cfg("openclaw_delivery_webhook", OPENCLAW_DELIVERY_WEBHOOK))
    _oc_token = _cfg("openclaw_token", OPENCLAW_TOKEN)
    if not _looks_masked_secret(_oc_token):
        OPENCLAW_TOKEN = str(_oc_token)
    OPENCLAW_ANALYSIS_AGENT_NAME = str(_cfg("openclaw_analysis_agent_name", OPENCLAW_ANALYSIS_AGENT_NAME))
    OPENCLAW_DELIVERY_AGENT_NAME = str(_cfg("openclaw_delivery_agent_name", OPENCLAW_DELIVERY_AGENT_NAME))
    OPENCLAW_ANALYSIS_MODEL = str(_cfg("openclaw_analysis_model", OPENCLAW_ANALYSIS_MODEL))
    OPENCLAW_ANALYSIS_MODEL_FALLBACK = str(_cfg("openclaw_analysis_model_fallback", OPENCLAW_ANALYSIS_MODEL_FALLBACK))
    OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK = str(_cfg("openclaw_analysis_webhook_fallback", OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK))
    OPENCLAW_SESSIONS_DIR = Path(f"/home/<HOME_USER>/.openclaw/agents/{OPENCLAW_ANALYSIS_AGENT_NAME}/sessions")
    OPENCLAW_SESSIONS_INDEX = OPENCLAW_SESSIONS_DIR / "sessions.json"
    OLLAMA_API = str(_cfg("ollama_api", OLLAMA_API))
    OLLAMA_MODEL = str(_cfg("ollama_model", OLLAMA_MODEL))

    recipients = _cfg("whatsapp_to", WHATSAPP_TO)
    if isinstance(recipients, list) and recipients:
        WHATSAPP_TO = ["+1234567890"]
    WHATSAPP_ENABLED = bool(_cfg("whatsapp_enabled", WHATSAPP_ENABLED))
    COOLDOWN_SECONDS = int(_cfg("cooldown_seconds", COOLDOWN_SECONDS))

    HA_URL = str(_cfg("ha_url", HA_URL))
    _ha_token = _cfg("ha_token", HA_TOKEN)
    if not _looks_masked_secret(_ha_token):
        HA_TOKEN = str(_ha_token)
    CAMERA_ZONE_LIGHTS = dict(_cfg("camera_zone_lights", CAMERA_ZONE_LIGHTS))
    default_lights = _cfg("camera_zone_lights_default", CAMERA_ZONE_LIGHTS_DEFAULT)
    if isinstance(default_lights, list) and default_lights:
        CAMERA_ZONE_LIGHTS_DEFAULT = [str(x) for x in default_lights]
    ALARM_ENTITY = str(_cfg("alarm_entity", ALARM_ENTITY))
    QUIET_HOURS_START = int(_cfg("quiet_hours_start", QUIET_HOURS_START))
    QUIET_HOURS_END = int(_cfg("quiet_hours_end", QUIET_HOURS_END))

    HA_HOME_MODE_ENTITY = str(_cfg("ha_home_mode_entity", HA_HOME_MODE_ENTITY))
    HA_KNOWN_FACES_ENTITY = str(_cfg("ha_known_faces_entity", HA_KNOWN_FACES_ENTITY))
    EXCLUDE_KNOWN_FACES = bool(_cfg("exclude_known_faces", EXCLUDE_KNOWN_FACES))
    CAMERA_CONTEXT_NOTES = dict(_cfg("camera_context_notes", CAMERA_CONTEXT_NOTES))
    CAMERA_POLICY_ZONES = dict(_cfg("camera_policy_zones", CAMERA_POLICY_ZONES))
    CAMERA_POLICY_ZONE_DEFAULT = str(_cfg("camera_policy_zone_default", CAMERA_POLICY_ZONE_DEFAULT))
    RECENT_EVENTS_WINDOW_SECONDS = int(_cfg("recent_events_window_seconds", RECENT_EVENTS_WINDOW_SECONDS))

    EVENT_HISTORY_FILE = Path(str(_cfg("event_history_file", str(EVENT_HISTORY_FILE))))
    EVENT_HISTORY_WINDOW_SECONDS = int(_cfg("event_history_window_seconds", EVENT_HISTORY_WINDOW_SECONDS))
    EVENT_HISTORY_MAX_LINES = int(_cfg("event_history_max_lines", EVENT_HISTORY_MAX_LINES))

    PHASE3_ENABLED = bool(_cfg("phase3_enabled", PHASE3_ENABLED))
    PHASE4_ENABLED = bool(_cfg("phase4_enabled", PHASE4_ENABLED))
    PHASE5_CONFIRM_ENABLED = bool(_cfg("phase5_enabled", PHASE5_CONFIRM_ENABLED))
    PHASE8_ENABLED = bool(_cfg("phase8_enabled", PHASE8_ENABLED))
    PHASE5_CONFIRM_DELAY_SECONDS = int(_cfg("phase5_confirm_delay_seconds", PHASE5_CONFIRM_DELAY_SECONDS))
    PHASE5_CONFIRM_TIMEOUT_SECONDS = int(_cfg("phase5_confirm_timeout_seconds", PHASE5_CONFIRM_TIMEOUT_SECONDS))
    risks = _cfg("phase5_confirm_risks", list(PHASE5_CONFIRM_RISKS))
    if isinstance(risks, list) and risks:
        PHASE5_CONFIRM_RISKS = {str(x).lower() for x in risks}

    # Optional enterprise secret overrides from .secrets.env
    if SECRETS_ENV_FILE.exists():
        try:
            for ln in SECRETS_ENV_FILE.read_text(encoding="utf-8").splitlines():
                s = ln.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                key = k.strip()
                val = v.strip().strip("'").strip('"')
                if key == "FRIGATE_MQTT_PASS" and val:
                    MQTT_PASS = val
                elif key == "OPENCLAW_TOKEN" and val:
                    OPENCLAW_TOKEN = val
                elif key == "HA_TOKEN" and val:
                    HA_TOKEN = val
        except Exception as exc:
            log.warning("Failed reading secrets env %s: %s", SECRETS_ENV_FILE, exc)

    log.info("Loaded runtime config from %s", RUNTIME_CONFIG_FILE)


_load_runtime_config()

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
last_alert: dict[str, float] = {}  # camera -> epoch of last alert
recent_events: dict[str, list[float]] = {}  # camera -> list of event epochs


def is_on_cooldown(camera: str) -> bool:
    now = time.time()
    if camera in last_alert and (now - last_alert[camera]) < COOLDOWN_SECONDS:
        return True
    last_alert[camera] = now
    return False


def download_snapshot(event_id: str, filename: str | None = None) -> Path | None:
    """Download snapshot (or thumbnail fallback) from Frigate API."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    dest = SNAPSHOT_DIR / (filename or f"{event_id}.jpg")

    for endpoint in ("snapshot.jpg", "thumbnail.jpg"):
        url = f"{FRIGATE_API}/api/events/{event_id}/{endpoint}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                dest.write_bytes(resp.content)
                log.info("Saved %s (%d bytes) via %s", dest, len(resp.content), endpoint)
                return dest
        except requests.RequestException as exc:
            log.warning("Failed to fetch %s: %s", url, exc)

    log.error("Could not download snapshot for event %s", event_id)
    return None


def stage_snapshot_for_openclaw(src: Path, event_id: str) -> Path | None:
    """Copy snapshot into OpenClaw workspace so MEDIA:./... works."""
    try:
        OPENCLAW_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        dest = OPENCLAW_MEDIA_DIR / f"{event_id}.jpg"
        shutil.copyfile(src, dest)
        return dest
    except Exception as exc:
        log.warning("Failed to stage snapshot for OpenClaw: %s", exc)
        return None


def _ha_get_state(entity_id: str) -> str | None:
    """Read one Home Assistant entity state via REST API."""
    url = f"{HA_URL}/api/states/{entity_id}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            return str(data.get("state", "")).strip()
        log.warning("HA state read %s returned %d", entity_id, resp.status_code)
    except requests.RequestException as exc:
        log.warning("HA state read %s failed: %s", entity_id, exc)
    return None


def _time_of_day_bucket() -> str:
    hour = datetime.now().hour
    if 6 <= hour < 18:
        return "day"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _recent_event_snapshot(camera: str) -> tuple[int, str]:
    """Return count + last timestamp for this camera within policy window."""
    now = time.time()
    events = recent_events.get(camera, [])
    events = [ts for ts in events if (now - ts) <= RECENT_EVENTS_WINDOW_SECONDS]
    recent_events[camera] = events
    if not events:
        return 0, "none"
    last_dt = datetime.fromtimestamp(max(events), tz=timezone.utc).isoformat()
    return len(events), last_dt


def _record_event(camera: str):
    now = time.time()
    events = recent_events.get(camera, [])
    events.append(now)
    recent_events[camera] = [ts for ts in events if (now - ts) <= RECENT_EVENTS_WINDOW_SECONDS]


def get_policy_context(camera: str) -> dict:
    """Build Phase 3 policy context with HA-backed values and safe defaults."""
    home_mode = (_ha_get_state(HA_HOME_MODE_ENTITY) or "home").lower()
    known_faces_state = (_ha_get_state(HA_KNOWN_FACES_ENTITY) or "off").lower()
    known_faces_present = known_faces_state in {"on", "true", "home", "detected"}
    recent_count, recent_last_ts = _recent_event_snapshot(camera)
    return {
        "time_of_day": _time_of_day_bucket(),
        "home_mode": home_mode,
        "known_faces_present": known_faces_present,
        "camera_context": CAMERA_CONTEXT_NOTES.get(camera, "unspecified"),
        "camera_zone": CAMERA_POLICY_ZONES.get(camera, CAMERA_POLICY_ZONE_DEFAULT),
        "recent_events_count": recent_count,
        "recent_events_last_ts": recent_last_ts,
    }


def _parse_iso_utc(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_recent_history(camera: str, window_seconds: int = EVENT_HISTORY_WINDOW_SECONDS) -> list[dict]:
    """Read recent events for one camera from JSONL memory store."""
    if not EVENT_HISTORY_FILE.exists():
        return []
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    try:
        with EVENT_HISTORY_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("camera") != camera:
                    continue
                dt = _parse_iso_utc(str(row.get("timestamp", "")))
                if not dt:
                    continue
                age = (now - dt).total_seconds()
                if age <= window_seconds:
                    out.append(row)
    except Exception as exc:
        log.warning("Failed reading event history: %s", exc)
    return out


def _recent_events_summary(camera: str) -> str:
    """Build Phase 4 RECENT_EVENTS summary for prompt context."""
    rows = _read_recent_history(camera)
    if not rows:
        return "- none in last 30 minutes"

    last_row = rows[-1]
    last_ts = str(last_row.get("timestamp", "unknown"))
    high_or_critical = sum(1 for r in rows if str(r.get("risk", "")).lower() in {"high", "critical"})
    common_type = str(last_row.get("type", "other"))
    return (
        f"- {len(rows)} events in last 30 minutes ({camera})\n"
        f"- last event: {last_ts}\n"
        f"- high/critical count: {high_or_critical}\n"
        f"- latest type trend: {common_type}"
    )


def _trim_event_history() -> None:
    """Keep memory file bounded to last N lines."""
    try:
        lines = EVENT_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) <= EVENT_HISTORY_MAX_LINES:
            return
        trimmed = "\n".join(lines[-EVENT_HISTORY_MAX_LINES:]) + "\n"
        EVENT_HISTORY_FILE.write_text(trimmed, encoding="utf-8")
    except Exception as exc:
        log.warning("Failed trimming event history: %s", exc)


def append_event_history(camera: str, event_id: str, decision: dict) -> None:
    """Append one decision event to Phase 4 JSONL memory store."""
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "camera": camera,
        "event_id": event_id,
        "risk": str(decision.get("risk", "low")),
        "action": str(decision.get("action", "notify_only")),
        "type": str(decision.get("type", "other")),
        "confidence": float(decision.get("confidence", 0.0)),
    }
    try:
        EVENT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        _trim_event_history()
    except Exception as exc:
        log.warning("Failed writing event history: %s", exc)



# ---------------------------------------------------------------------------
# Pillar 2 — Rule-based severity scoring (supplements AI decision)
# ---------------------------------------------------------------------------
def score_severity(ai_decision: dict, policy: dict) -> str:
    """Apply simple deterministic rules to adjust AI risk assessment.
    Returns: low / medium / high / critical."""
    score = 0
    ai_risk = str(ai_decision.get("risk", {}) if not isinstance(ai_decision.get("risk"), dict) else ai_decision.get("risk", {}).get("level", "low")).lower()
    ai_type = str(ai_decision.get("type", "other")).lower()
    time_of_day = str(policy.get("time_of_day", "day")).lower()
    home_mode = str(policy.get("home_mode", "home")).lower()
    known_faces = bool(policy.get("known_faces_present", False))
    zone = str(policy.get("camera_zone", "entry")).lower()
    recent_count = int(policy.get("recent_events_count", 0))

    # Unknown person = base risk
    if "unknown" in ai_type or ai_type == "other":
        score += 2
    # After hours (evening/night)
    if time_of_day in ("evening", "night"):
        score += 2
    # Restricted/sensitive zones
    if any(z in zone for z in ("terrace", "garage", "entry", "door")):
        score += 1
    # Away mode = higher risk
    if home_mode == "away":
        score += 3
    elif home_mode == "sleep":
        score += 2
    # Suspicious behavior keywords from AI
    behavior = str(ai_decision.get("behavior", "")).lower()
    if any(w in behavior for w in ("suspicious", "lurking", "trying", "forcing", "climbing", "breaking", "running")):
        score += 3
    elif any(w in behavior for w in ("reaching", "looking around", "crouching", "hiding")):
        score += 2
    # Loitering
    if "loitering" in ai_type:
        score += 2
    # Known face = reduce
    if known_faces or "known" in ai_type:
        score -= 3
    # Delivery = reduce
    if "delivery" in ai_type:
        score -= 1
    # Frequent recent events = something ongoing
    if recent_count >= 3:
        score += 1

    # Map score to risk level
    if score <= 2:
        return "low"
    elif score <= 4:
        return "medium"
    elif score <= 6:
        return "high"
    else:
        return "critical"


def decide_media(risk_level: str) -> dict:
    """Decide what media to attach based on risk level."""
    return {
        "low":      {"snapshot": True,  "clip": False, "clip_length": 0,  "monitoring": False},
        "medium":   {"snapshot": True,  "clip": True,  "clip_length": 15, "monitoring": False},
        "high":     {"snapshot": True,  "clip": True,  "clip_length": 30, "monitoring": True},
        "critical": {"snapshot": True,  "clip": True,  "clip_length": 60, "monitoring": True},
    }.get(risk_level, {"snapshot": True, "clip": False, "clip_length": 0, "monitoring": False})


def _send_to_ollama_direct(camera: str, event_id: str, policy: dict, recent_events_summary: str) -> str | None:
    """Direct local VLM analysis via Mac Ollama API to avoid OpenClaw session polling issues."""
    img_path = OPENCLAW_MEDIA_DIR / f"{event_id}.jpg"
    if not img_path.exists():
        log.warning("Ollama direct analysis skipped: missing staged image %s", img_path)
        return None
    try:
        b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
    except Exception as exc:
        log.warning("Ollama direct analysis skipped: failed to read image %s", exc)
        return None

    prompt = (
        f"You are an AI security camera analyst. Analyze this image from camera '{camera}'.\n"
        f"Location: {policy.get('camera_context', 'unspecified')}\n"
        f"Zone: {policy.get('camera_zone', 'entry')}\n"
        f"Time: {policy.get('time_of_day', 'unknown')}, Home: {policy.get('home_mode', 'unknown')}\n"
        f"Known faces: {str(policy.get('known_faces_present', False)).lower()}\n\n"
        "Describe EXACTLY what you see. Be specific about:\n"
        "- Number of people, clothing, build, distinguishing features\n"
        "- Actions: walking, standing, reaching, looking around, carrying items\n"
        "- Items: bags, tools, packages, phone, nothing\n"
        "- Is behavior normal or suspicious for this location?\n\n"
        "Then output a JSON block. Start the line with JSON: and put the entire object on ONE line.\n"
        "JSON: {"
        '"subject":{"identity":"unknown","description":"brief appearance"},'
        '"behavior":"what they are doing",'
        '"risk":{"level":"low|medium|high|critical","confidence":0.0,"reason":"why"},'
        '"type":"unknown_person|known_person|delivery|vehicle|animal|loitering|other",'
        '"action":"notify_only|notify_and_save_clip|notify_and_light|notify_and_alarm"'
        "}\n\n"
        "Rules: low=routine, medium=unusual activity, high=suspicious/after-hours, critical=threat/break-in.\n"
        "Match action to risk: low->notify_only, medium->notify_and_save_clip, high->notify_and_light, critical->notify_and_alarm."
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "images": [b64],
        "stream": False,
        "options": {"num_predict": 350, "temperature": 0.1}
    }
    try:
        resp = requests.post(f"{OLLAMA_API.rstrip('/')}/api/generate", json=payload, timeout=300)
        if resp.status_code != 200:
            log.warning("Ollama direct analysis returned %d: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        out = str(data.get("response", "")).strip()
        if out:
            log.info("Ollama direct analysis completed via %s model=%s", OLLAMA_API, OLLAMA_MODEL)
            return out
    except Exception as exc:
        log.warning("Ollama direct analysis failed: %s", exc)
    return None


def send_to_openclaw(camera: str, event_id: str, policy: dict | None = None,
                     recent_events_summary: str | None = None) -> str | None:
    """POST the snapshot to OpenClaw webhook for GPT-4o-mini vision analysis.
    This request is analysis-only; WhatsApp delivery is sent separately using
    a cleaned message (without machine JSON)."""
    # OpenClaw only allows MEDIA:./relative paths for security
    # MEDIA lines must be relative and cannot use ".." per OpenClaw security rules.
    # The gateway runs with HOME=/home/<HOME_USER>, so use a workspace-relative path.
    openclaw_rel_media = f"./frigate/storage/ai-snapshots/{event_id}.jpg"
    openclaw_abs_media = str(OPENCLAW_MEDIA_DIR / f"{event_id}.jpg")
    if policy is None:
        policy = {
            "time_of_day": "unknown",
            "home_mode": "unknown",
            "known_faces_present": False,
            "camera_context": "unspecified",
            "camera_zone": "entry",
            "recent_events_count": 0,
            "recent_events_last_ts": "none",
        }
    if recent_events_summary is None:
        recent_events_summary = "- none in last 30 minutes"

    prompt = (
        f"Security alert from camera '{camera}'. "
        f"Use the image tool to open and analyze the snapshot at: {openclaw_abs_media}\n\n"
        "Policy context for this event:\n"
        f"- time_of_day: {policy['time_of_day']}\n"
        f"- home_mode: {policy['home_mode']}\n"
        f"- known_faces_present: {str(policy['known_faces_present']).lower()}\n"
        f"- camera_context: {policy.get('camera_context', 'unspecified')}\n"
        f"- camera_zone: {policy['camera_zone']}\n"
        f"- recent_events: {policy['recent_events_count']} in last 10 minutes "
        f"(last={policy['recent_events_last_ts']})\n\n"
        "RECENT_EVENTS:\n"
        f"{recent_events_summary}\n\n"
        "IMPORTANT: You CAN and MUST use the image tool to view the snapshot. "
        "Do NOT say you cannot analyze the image — you have the image tool available. "
        "Open the image first, then respond.\n\n"
        "After viewing the image, your reply MUST have exactly three parts:\n\n"
        "PART 1 — Send the snapshot image using this exact line:\n"
        f"MEDIA:{openclaw_rel_media}\n\n"
        "PART 2 — Below the MEDIA line, provide a brief security assessment:\n"
        f"[{camera}] Threat: LOW/MEDIUM/HIGH/CRITICAL\n"
        "Description of what you see. Recommended action if any.\n\n"
        "PART 3 — End your response with a JSON decision block on a SINGLE line:\n"
        "JSON:\n"
        '{"risk":"low|medium|high|critical","type":"unknown_person|known_person|delivery|vehicle|animal|loitering|other",'
        '"confidence":0.00,"action":"notify_only|notify_and_save_clip|notify_and_light|notify_and_alarm",'
        '"reason":"short explanation under 120 chars"}\n\n'
        "Action mapping: low→notify_only, medium→notify_and_save_clip, high→notify_and_light, critical→notify_and_alarm\n\n"
        "Rules:\n"
        "- 3-5 sentences max for the human-readable part\n"
        "- Be factual and direct, no questions or disclaimers\n"
        "- Do NOT ask the user anything, just report what you see\n"
        "- Always include the MEDIA line BEFORE the text analysis\n"
        "- The JSON: line MUST be the last line of your response"
    )

    # Prefer direct Ollama (Mac mini) for local VLM reasoning; keep OpenClaw path as fallback.
    analysis = _send_to_ollama_direct(camera, event_id, policy, recent_events_summary)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
    }

    if analysis:
        return analysis

    analysis = None
    payload = {
        "message": prompt,
        "model": OPENCLAW_ANALYSIS_MODEL,
        "deliver": False,
        "sessionKey": f"frigate:{camera}:{event_id}",
        "timeoutSeconds": 120,
    }
    try:
        resp = requests.post(
            OPENCLAW_ANALYSIS_WEBHOOK,
            json=payload,
            headers=headers,
            timeout=90,
        )
        if resp.status_code in (200, 201, 202):
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            result = data.get("reply") or data.get("response") or data.get("message", "")
            log.info("OpenClaw analysis request accepted (%d): %s", resp.status_code, result[:120])
            if result:
                analysis = result
        else:
            log.error("OpenClaw analysis request returned %d: %s", resp.status_code, resp.text[:200])
    except requests.RequestException as exc:
        log.error("OpenClaw analysis request failed: %s", exc)

    # Pull the completed reply from OpenClaw session logs (async result)
    session_key = f"frigate:{camera}:{event_id}"
    session_analysis = read_openclaw_session_reply(session_key, timeout_seconds=120)
    if session_analysis:
        analysis = session_analysis

    # Fallback path: local OpenClaw + OpenAI model when primary does not yield a session
    if not analysis and OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK and OPENCLAW_ANALYSIS_MODEL_FALLBACK:
        fallback_key = f"{session_key}:fallback"
        fb_payload = dict(payload)
        fb_payload["model"] = OPENCLAW_ANALYSIS_MODEL_FALLBACK
        fb_payload["sessionKey"] = fallback_key
        try:
            fb_resp = requests.post(
                OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK,
                json=fb_payload,
                headers=headers,
                timeout=90,
            )
            if fb_resp.status_code in (200, 201, 202):
                log.warning(
                    "Primary analysis returned no session; fallback accepted (%d) via %s model=%s",
                    fb_resp.status_code, OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK, OPENCLAW_ANALYSIS_MODEL_FALLBACK
                )
                analysis = read_openclaw_session_reply(fallback_key, timeout_seconds=120)
            else:
                log.error(
                    "Fallback analysis request returned %d: %s",
                    fb_resp.status_code, fb_resp.text[:200]
                )
        except requests.RequestException as exc:
            log.error("Fallback analysis request failed: %s", exc)

    return analysis


def send_confirmation_to_openclaw(camera: str, event_id: str, media_event_id: str,
                                  initial_decision: dict, policy: dict,
                                  recent_events_summary: str) -> str | None:
    """Run Phase 5 second-pass confirmation using a fresh snapshot."""
    openclaw_rel_media = f"./frigate/storage/ai-snapshots/{media_event_id}.jpg"
    openclaw_abs_media = str(OPENCLAW_MEDIA_DIR / f"{media_event_id}.jpg")
    prompt = (
        f"Confirmation check for camera '{camera}'. Re-check this newer snapshot: {openclaw_abs_media}\n\n"
        "Use the image tool before answering.\n"
        f"MEDIA:{openclaw_rel_media}\n\n"
        "Initial decision from first pass:\n"
        f'{json.dumps(initial_decision, separators=(",", ":"))}\n\n'
        "Policy context:\n"
        f"- time_of_day: {policy['time_of_day']}\n"
        f"- home_mode: {policy['home_mode']}\n"
        f"- known_faces_present: {str(policy['known_faces_present']).lower()}\n"
        f"- camera_context: {policy.get('camera_context', 'unspecified')}\n"
        f"- camera_zone: {policy['camera_zone']}\n"
        f"- recent_events: {policy['recent_events_count']} in last 10 minutes "
        f"(last={policy['recent_events_last_ts']})\n\n"
        "RECENT_EVENTS:\n"
        f"{recent_events_summary}\n\n"
        "Return only one final line in this exact format:\n"
        'CONFIRM_JSON: {"confirmed":true|false,"risk":"low|medium|high|critical","action":"notify_only|notify_and_save_clip|notify_and_light|notify_and_alarm","reason":"short reason"}'
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
    }
    payload = {
        "message": prompt,
        "model": OPENCLAW_ANALYSIS_MODEL,
        "deliver": False,
        "sessionKey": f"frigate:confirm:{camera}:{event_id}",
        "timeoutSeconds": PHASE5_CONFIRM_TIMEOUT_SECONDS,
    }
    try:
        resp = requests.post(
            OPENCLAW_ANALYSIS_WEBHOOK,
            json=payload,
            headers=headers,
            timeout=90,
        )
        if resp.status_code not in (200, 201, 202):
            log.warning("Phase 5 confirm request returned %d: %s", resp.status_code, resp.text[:200])
    except requests.RequestException as exc:
        log.warning("Phase 5 confirm request failed: %s", exc)
        return None

    confirm_key = f"frigate:confirm:{camera}:{event_id}"
    confirm_result = read_openclaw_session_reply(
        confirm_key,
        timeout_seconds=PHASE5_CONFIRM_TIMEOUT_SECONDS,
    )
    if confirm_result:
        return confirm_result

    # Fallback confirm path when primary did not yield a session
    if OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK and OPENCLAW_ANALYSIS_MODEL_FALLBACK:
        fb_key = f"{confirm_key}:fallback"
        fb_payload = dict(payload)
        fb_payload["model"] = OPENCLAW_ANALYSIS_MODEL_FALLBACK
        fb_payload["sessionKey"] = fb_key
        try:
            fb_resp = requests.post(
                OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK,
                json=fb_payload,
                headers=headers,
                timeout=90,
            )
            if fb_resp.status_code in (200, 201, 202):
                log.warning(
                    "Phase5 primary returned no session; fallback accepted (%d) via %s model=%s",
                    fb_resp.status_code, OPENCLAW_ANALYSIS_WEBHOOK_FALLBACK, OPENCLAW_ANALYSIS_MODEL_FALLBACK
                )
                return read_openclaw_session_reply(
                    fb_key,
                    timeout_seconds=PHASE5_CONFIRM_TIMEOUT_SECONDS,
                )
            log.warning("Phase 5 fallback request returned %d: %s", fb_resp.status_code, fb_resp.text[:200])
        except requests.RequestException as exc:
            log.warning("Phase 5 fallback request failed: %s", exc)
    return None


def parse_confirmation_json(analysis: str) -> dict | None:
    """Parse CONFIRM_JSON line (same-line or next-line JSON)."""
    if not analysis:
        return None
    lines = analysis.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        match = re.match(r"(?i)^confirm_json:\s*(.*)", stripped)
        if not match:
            continue
        json_str = match.group(1).strip()
        if not json_str and i + 1 < len(lines):
            json_str = lines[i + 1].strip()
        if not json_str:
            return None
        try:
            obj = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        if "confirmed" not in obj:
            return None
        return obj
    return None


def maybe_confirm_decision(camera: str, event_id: str, decision: dict, policy: dict,
                           recent_events_summary: str) -> tuple[dict, str]:
    """Phase 5: second-pass confirmation before high/critical actions."""
    risk = str(decision.get("risk", "low")).lower()
    if not PHASE5_CONFIRM_ENABLED or risk not in PHASE5_CONFIRM_RISKS:
        return decision, ""

    log.info("Phase 5 confirmation started for %s (risk=%s)", event_id, risk)
    time.sleep(PHASE5_CONFIRM_DELAY_SECONDS)

    confirm_media_id = f"{event_id}-confirm"
    confirm_snapshot = download_snapshot(event_id, filename=f"{confirm_media_id}.jpg")
    if not confirm_snapshot:
        log.warning("Phase 5 confirmation skipped: no second snapshot")
        return decision, "Confirmation unavailable (no second snapshot); keeping initial decision."
    if not stage_snapshot_for_openclaw(confirm_snapshot, confirm_media_id):
        log.warning("Phase 5 confirmation skipped: failed staging second snapshot")
        return decision, "Confirmation unavailable (staging failed); keeping initial decision."

    confirm_reply = send_confirmation_to_openclaw(
        camera=camera,
        event_id=event_id,
        media_event_id=confirm_media_id,
        initial_decision=decision,
        policy=policy,
        recent_events_summary=recent_events_summary,
    )
    confirm_obj = parse_confirmation_json(confirm_reply or "")
    if not confirm_obj:
        log.warning("Phase 5 confirmation unavailable/invalid; keeping initial decision")
        return decision, "Confirmation unavailable (invalid response); keeping initial decision."

    confirmed = bool(confirm_obj.get("confirmed"))
    if not confirmed:
        downgraded = dict(decision)
        downgraded["risk"] = "medium" if risk in {"high", "critical"} else risk
        if str(downgraded.get("action", "")) in {"notify_and_alarm", "notify_and_light", "notify_and_speaker"}:
            downgraded["action"] = "notify_and_save_clip"
        downgraded["reason"] = str(confirm_obj.get("reason") or "Unconfirmed on second pass — downgraded")
        log.info("Phase 5 confirmation rejected escalation for %s; downgraded decision", event_id)
        return downgraded, f"Second-pass confirmation: NOT confirmed. Decision downgraded ({downgraded['action']})."

    upgraded = dict(decision)
    suggested_risk = str(confirm_obj.get("risk", upgraded.get("risk", "low"))).lower()
    suggested_action = str(confirm_obj.get("action", upgraded.get("action", "notify_only")))
    if suggested_risk in {"low", "medium", "high", "critical"}:
        upgraded["risk"] = suggested_risk
    if suggested_action in ALLOWED_ACTIONS:
        upgraded["action"] = suggested_action
    if confirm_obj.get("reason"):
        upgraded["reason"] = str(confirm_obj["reason"])
    log.info("Phase 5 confirmation accepted for %s", event_id)
    return upgraded, "Second-pass confirmation: confirmed."


def _format_whatsapp_alert(camera: str, event_id: str, analysis_text: str,
                           decision: dict, policy: dict) -> str:
    """Format professional structured WhatsApp security alert (Pillar 3)."""
    from datetime import datetime as _dt

    # Extract structured fields from decision
    risk_obj = decision.get("risk", {})
    if isinstance(risk_obj, dict):
        risk_level = str(risk_obj.get("level", "low")).upper()
        confidence = risk_obj.get("confidence", 0.0)
        reason = str(risk_obj.get("reason", ""))
    else:
        risk_level = str(decision.get("risk", "low")).upper()
        confidence = decision.get("confidence", 0.0)
        reason = str(decision.get("reason", ""))

    severity_emoji = {"LOW": "\U0001f7e2", "MEDIUM": "\U0001f7e1", "HIGH": "\U0001f7e0", "CRITICAL": "\U0001f534"}
    risk_icon = severity_emoji.get(risk_level, "\u2753")

    # Subject info
    subject_obj = decision.get("subject", {})
    if isinstance(subject_obj, dict):
        identity = str(subject_obj.get("identity", "unknown")).title()
        subject_desc = str(subject_obj.get("description", ""))
    else:
        det_type = str(decision.get("type", "other"))
        identity = "Known" if "known" in det_type else "Unknown"
        subject_desc = det_type.replace("_", " ").title()

    # Behavior
    behavior = str(decision.get("behavior", ""))
    if not behavior:
        # Extract from analysis text
        clean = strip_json_block(analysis_text).strip()
        beh_lines = []
        for line in clean.splitlines():
            s = line.strip()
            low = s.lower()
            if not s or low.startswith("media:") or "ai-snapshots/" in low:
                continue
            if low.startswith("attached") or low.startswith("security assessment"):
                continue
            beh_lines.append(s)
        behavior = "\n".join(beh_lines[:5]).strip()
    if not behavior:
        behavior = "Person detected in view"
    if len(behavior) > 500:
        behavior = behavior[:497] + "..."

    # Confidence formatting
    if isinstance(confidence, (int, float)):
        if confidence <= 1.0:
            conf_display = f"{confidence:.2f}"
        else:
            conf_display = f"{confidence/100:.2f}"
    else:
        conf_display = str(confidence)

    # Context
    camera_zone = str(policy.get("camera_zone", "unknown")).replace("-", " ").title()
    home_mode = str(policy.get("home_mode", "unknown")).title()
    time_of_day = str(policy.get("time_of_day", "unknown")).title()
    known_faces = "Yes" if policy.get("known_faces_present") else "No"
    time_str = _dt.now().strftime("%H:%M:%S")
    date_str = _dt.now().strftime("%d %b %Y")

    # Building status
    if home_mode.lower() == "away":
        building_status = "Unoccupied"
        expected = "None"
    elif home_mode.lower() == "sleep":
        building_status = "Occupied (sleeping)"
        expected = "None"
    elif home_mode.lower() == "guest":
        building_status = "Occupied (guests)"
        expected = "Possible visitor movement"
    else:
        building_status = "Occupied"
        expected = "Normal household activity"

    # Action taken
    action_raw = str(decision.get("action", "notify_only"))
    action_map = {
        "notify_only": "\U0001f514 Owner notified",
        "notify_and_save_clip": "\U0001f514 Owner notified\n\U0001f4be Clip saved",
        "notify_and_light": "\U0001f514 Owner notified\n\U0001f4be Clip saved\n\U0001f4a1 Lights activated",
        "notify_and_speaker": "\U0001f514 Owner notified\n\U0001f4be Clip saved\n\U0001f50a Alexa announcement",
        "notify_and_alarm": "\U0001f6a8 ALARM ACTIVATED\n\U0001f4a1 All lights ON\n\U0001f50a Speakers active\n\U0001f4be Clip saved",
    }
    action_text = action_map.get(action_raw, action_raw.replace("_", " ").title())

    # Media info
    media_info = decide_media(risk_level.lower())
    clip_path = SNAPSHOT_DIR.parent / "ai-clips" / f"{event_id}.mp4"
    snap_line = "\u2705 Snapshot attached"
    clip_line = f"\u2705 {media_info['clip_length']}s clip attached" if clip_path.exists() else (
        f"\U0001f4be {media_info['clip_length']}s clip saving..." if media_info["clip"] else "\u274c No clip needed"
    )
    monitor_line = "\U0001f4f9 Continued monitoring active" if media_info["monitoring"] else ""

    # Escalation logic
    escalation = ""
    if risk_level == "MEDIUM":
        escalation = (
            "\n\n\u26a0\ufe0f *ESCALATION CONDITIONS*\n"
            "Will upgrade to HIGH if:\n"
            "\u2022 Subject remains > 60 sec\n"
            "\u2022 Forced entry attempt detected\n"
            "\u2022 Additional persons appear"
        )
    elif risk_level == "HIGH":
        escalation = (
            "\n\n\u26a0\ufe0f *ESCALATION CONDITIONS*\n"
            "Will upgrade to CRITICAL if:\n"
            "\u2022 Break-in attempt detected\n"
            "\u2022 Weapon or tool observed\n"
            "\u2022 Multiple intruders confirmed"
        )
    elif risk_level == "CRITICAL":
        escalation = (
            "\n\n\U0001f6a8 *IMMEDIATE RESPONSE*\n"
            "\u2022 Alarm siren active\n"
            "\u2022 All lights ON\n"
            "\u2022 Evidence being recorded\n"
            "\u2022 Consider calling authorities"
        )

    # Recent events
    recent_count = policy.get("recent_events_count", 0)
    recent_line = f"\nRecent: {recent_count} events in last 10 min" if recent_count > 0 else ""

    msg = (
        f"\U0001f6a8 *AI SECURITY ALERT*\n"
        f"Severity: {risk_icon} *{risk_level}*\n"
        f"\n"
        f"\U0001f4cd *EVENT*\n"
        f"Location: {camera}\n"
        f"Zone: {camera_zone}\n"
        f"Time: {time_str} \u2022 {date_str}\n"
        f"Event: `{event_id[:35]}`\n"
        f"\n"
        f"\U0001f464 *SUBJECT*\n"
        f"Identity: {identity}\n"
        f"{subject_desc}\n"
        f"\n"
        f"\U0001f3af *BEHAVIOR OBSERVED*\n"
        f"{behavior}\n"
        f"\n"
        f"\U0001f9e0 *RISK ASSESSMENT*\n"
        f"Threat: {risk_level}\n"
        f"Confidence: {conf_display}\n"
        f"Reason: _{reason}_\n"
        f"\n"
        f"\U0001f4cd *CONTEXT*\n"
        f"Building: {building_status}\n"
        f"Expected: {expected}\n"
        f"Known faces: {known_faces}"
        f"{recent_line}\n"
        f"\n"
        f"\u26a1 *SYSTEM ACTION*\n"
        f"{action_text}\n"
        f"\n"
        f"\U0001f4ce *MEDIA*\n"
        f"{snap_line}\n"
        f"{clip_line}"
    )
    if monitor_line:
        msg += f"\n{monitor_line}"
    msg += escalation

    return msg


def deliver_whatsapp_message(camera: str, event_id: str, analysis_text: str,
                              decision: dict | None = None, policy: dict | None = None):
    """Send professional structured WhatsApp alert with snapshot at top, clip at bottom."""
    if not WHATSAPP_ENABLED:
        log.info("WhatsApp delivery disabled by config; skipping %s", event_id)
        return
    if decision is None:
        decision = _fallback_decision(analysis_text)
    if policy is None:
        policy = {}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
    }

    # Build single message: snapshot MEDIA at top, formatted text, clip MEDIA at bottom
    snapshot_media = f"MEDIA:./frigate/storage/ai-snapshots/{event_id}.jpg"
    formatted_text = _format_whatsapp_alert(camera, event_id, analysis_text, decision, policy)

    # Check for clip (attach at bottom if exists)
    clip_path = SNAPSHOT_DIR.parent / "ai-clips" / f"{event_id}.mp4"
    clip_line = ""
    if clip_path.exists() and clip_path.stat().st_size > 1000:
        clip_line = f"\nMEDIA:./frigate/storage/ai-clips/{event_id}.mp4"
        log.info("Clip found for %s (%d bytes) — attaching to alert",
                 event_id, clip_path.stat().st_size)

    message = f"{snapshot_media}\n{formatted_text}{clip_line}"

    forward_instruction = (
        "DELIVERY MODE. Forward the EXACT message below to WhatsApp verbatim. "
        "Do not rewrite or add anything. Preserve all formatting:\n\n"
    )

    for number in WHATSAPP_TO:
        delivery_msg = forward_instruction + message
        payload = {
            "message": delivery_msg,
            "deliver": True,
            "channel": "whatsapp",
            "to": number,
            "name": "Frigate",
            "sessionKey": f"frigate:alert:{OPENCLAW_DELIVERY_AGENT_NAME}:{camera}:{event_id}:{number}",
            "timeoutSeconds": 60,
        }
        try:
            resp = requests.post(
                OPENCLAW_DELIVERY_WEBHOOK, json=payload, headers=headers, timeout=60,
            )
            if resp.status_code in (200, 201, 202):
                log.info("WhatsApp alert accepted for %s (%d)%s",
                         number, resp.status_code, " [+clip]" if clip_line else "")
            else:
                log.error("WhatsApp alert to %s returned %d: %s",
                          number, resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.error("WhatsApp alert to %s failed: %s", number, exc)


def read_openclaw_session_reply(session_key: str, timeout_seconds: int = 60) -> str | None:
    """Read the latest assistant reply from OpenClaw session logs for a session key."""
    if not OPENCLAW_SESSIONS_INDEX.exists():
        log.warning("OpenClaw sessions index not found: %s", OPENCLAW_SESSIONS_INDEX)
        return None

    # Session keys are normalized to lower-case in OpenClaw's sessions index
    norm_key = session_key.strip().lower()
    full_key = f"agent:{OPENCLAW_ANALYSIS_AGENT_NAME}:{norm_key}"

    deadline = time.time() + timeout_seconds
    session_id = None

    # Wait for session to be created
    while time.time() < deadline and not session_id:
        try:
            data = json.loads(OPENCLAW_SESSIONS_INDEX.read_text())
            entry = data.get(full_key)
            if entry and isinstance(entry, dict):
                session_id = entry.get("sessionId")
                if session_id:
                    break
        except Exception as exc:
            log.warning("Failed reading sessions index: %s", exc)
        time.sleep(1)

    if not session_id:
        log.warning("No OpenClaw session found for key %s", full_key)
        return None

    session_file = OPENCLAW_SESSIONS_DIR / f"{session_id}.jsonl"

    # Wait for session file and assistant reply to appear
    while time.time() < deadline:
        if not session_file.exists():
            time.sleep(1)
            continue
        try:
            last_reply = None
            with session_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if item.get("type") != "message":
                        continue
                    message = item.get("message") or {}
                    if message.get("role") != "assistant":
                        continue
                    content = message.get("content") or []
                    if not isinstance(content, list):
                        continue
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text = part.get("text")
                            if text:
                                text_parts.append(text)
                    if text_parts:
                        last_reply = "\n".join(text_parts).strip()

            if last_reply:
                # Strip MEDIA line for HA; keep analysis text
                lines = [ln for ln in last_reply.splitlines() if not ln.strip().startswith("MEDIA:")]
                cleaned = "\n".join(lines).strip()
                return cleaned or last_reply
        except Exception as exc:
            log.warning("Failed reading session file %s: %s", session_file, exc)

        time.sleep(1)

    if not session_file.exists():
        log.warning("OpenClaw session file missing after timeout: %s", session_file)
    else:
        log.warning("Timed out waiting for OpenClaw reply for %s", session_key)
    return None


def extract_risk(analysis: str) -> str:
    """Extract threat/risk level from the analysis text."""
    upper = analysis.upper()
    if "THREAT: HIGH" in upper or "THREAT:HIGH" in upper:
        return "high"
    if "THREAT: MEDIUM" in upper or "THREAT:MEDIUM" in upper:
        return "medium"
    return "low"


DECISION_REQUIRED_KEYS = {"risk", "type", "confidence", "action", "reason"}


def parse_decision_json(analysis: str) -> dict:
    """Extract the JSON decision block from the analysis text.

    Supports multiple formats:
    1. JSON: {...}  or  json: {...}
    2. ```json\n{...}\n```  (markdown code fence)
    3. Bare JSON object on its own line containing required keys
    Falls back to a smart fallback built from text extraction.
    """
    if not analysis:
        return _fallback_decision("")

    lines = analysis.splitlines()

    # Strategy 1: Look for explicit JSON: prefix (original approach)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        match = re.match(r"(?i)^json:\s*(.*)", stripped)
        if match:
            json_str = match.group(1).strip()
            if not json_str and i + 1 < len(lines):
                json_str = lines[i + 1].strip()
            if json_str:
                obj = _try_parse_decision(json_str)
                if obj:
                    log.info("Parsed decision JSON (prefix): %s", obj)
                    return obj
            break

    # Strategy 2: Look for ```json ... ``` code fence
    fence_match = re.search(r"```(?:json)?\s*\n(\{[^`]+\})\s*\n```", analysis, re.IGNORECASE)
    if fence_match:
        obj = _try_parse_decision(fence_match.group(1).strip())
        if obj:
            log.info("Parsed decision JSON (code fence): %s", obj)
            return obj

    # Strategy 3: Find any line that looks like a JSON object with risk/action keys
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("{") and stripped.endswith("}") and "risk" in stripped:
            obj = _try_parse_decision(stripped)
            if obj:
                log.info("Parsed decision JSON (bare): %s", obj)
                return obj

    # Strategy 4: Find JSON embedded within text (e.g. "... result: {"risk":...}")
    json_match = re.search(r'(\{[^{}]*"risk"\s*:\s*"[^"]*"[^{}]*\})', analysis)
    if json_match:
        obj = _try_parse_decision(json_match.group(1))
        if obj:
            log.info("Parsed decision JSON (embedded): %s", obj)
            return obj

    log.info("JSON decision block not found — using smart fallback")
    return _fallback_decision(analysis)


def _try_parse_decision(json_str: str) -> dict | None:
    """Attempt to parse a JSON string as a decision object.
    Handles both flat and structured (nested) formats."""
    try:
        obj = json.loads(json_str)
        if not isinstance(obj, dict):
            return None

        # Handle new structured format: {subject:{}, behavior:"", risk:{level,confidence,reason}, ...}
        if isinstance(obj.get("risk"), dict):
            risk_obj = obj["risk"]
            flat = {
                "risk": str(risk_obj.get("level", "low")).lower(),
                "confidence": float(risk_obj.get("confidence", 0.5)),
                "reason": str(risk_obj.get("reason", "AI analysis")),
                "type": str(obj.get("type", "other")),
                "action": str(obj.get("action", "notify_only")),
                "subject": obj.get("subject", {}),
                "behavior": str(obj.get("behavior", "")),
            }
            return flat

        # Handle flat format: {risk:"low", type:"...", confidence:0.7, action:"...", reason:"..."}
        if "risk" in obj and "action" in obj:
            obj.setdefault("type", "other")
            obj.setdefault("confidence", 0.5)
            obj.setdefault("reason", "AI analysis")
            return obj
        if DECISION_REQUIRED_KEYS.issubset(obj.keys()):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _fallback_decision(analysis: str) -> dict:
    """Build a decision dict from text-based extraction when JSON parsing fails."""
    risk = extract_risk(analysis)
    upper = analysis.upper() if analysis else ""
    # Try to extract type from analysis text
    det_type = "other"
    if any(w in upper for w in ("DELIVERY", "PACKAGE", "COURIER", "PARCEL")):
        det_type = "delivery"
    elif any(w in upper for w in ("KNOWN PERSON", "FAMILIAR", "RECOGNIZED", "HOUSEHOLD")):
        det_type = "known_person"
    elif any(w in upper for w in ("LOITERING", "LINGERING", "WAITING SUSPICIOUSLY")):
        det_type = "loitering"
    elif any(w in upper for w in ("VEHICLE", "CAR ", "MOTORCYCLE", "BIKE ")):
        det_type = "vehicle"
    elif any(w in upper for w in ("ANIMAL", "CAT ", "DOG ", "BIRD ")):
        det_type = "animal"
    elif "PERSON" in upper or "INDIVIDUAL" in upper or "MALE" in upper or "FEMALE" in upper:
        det_type = "unknown_person"
    # Map risk to action
    action_map = {"low": "notify_only", "medium": "notify_and_save_clip", "high": "notify_and_light", "critical": "notify_and_alarm"}
    return {
        "risk": risk,
        "type": det_type,
        "confidence": 0.4 if risk == "low" else 0.6,
        "action": action_map.get(risk, "notify_only"),
        "reason": "Extracted from AI text (no structured JSON)" if analysis else "AI decision unavailable",
    }


def sanitize_decision(decision: dict) -> dict:
    """Normalize AI decision fields to safe, consistent values."""
    out = dict(decision or {})

    risk = str(out.get("risk", "low")).lower()
    if risk not in {"low", "medium", "high", "critical"}:
        risk = "low"
    out["risk"] = risk

    action = str(out.get("action", "notify_only"))
    if action not in ALLOWED_ACTIONS:
        action = "notify_only"
    out["action"] = action

    try:
        conf = float(out.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    # Some model replies return percent (e.g., 71.0). Convert to 0-1 scale.
    if conf > 1.0 and conf <= 100.0:
        conf = conf / 100.0
    conf = max(0.0, min(1.0, conf))
    out["confidence"] = conf

    out["type"] = str(out.get("type", "other"))
    out["reason"] = str(out.get("reason", "AI decision unavailable"))
    return out


def strip_json_block(analysis: str) -> str:
    """Remove the JSON decision block from analysis text.

    Supports either:
    - JSON: {...}
    - JSON:
      {...}
    """
    out = []
    skip_next_json_line = False
    for line in analysis.splitlines():
        stripped = line.strip()

        if skip_next_json_line:
            if stripped.startswith("{") and stripped.endswith("}"):
                skip_next_json_line = False
                continue
            skip_next_json_line = False

        match = re.match(r"(?i)^json:\s*(.*)", stripped)
        if match:
            tail = match.group(1).strip()
            if tail.startswith("{") and tail.endswith("}"):
                continue
            if not tail:
                skip_next_json_line = True
                continue

        out.append(line)
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# Phase 2 — HA REST action execution
# ---------------------------------------------------------------------------
def _is_quiet_hours() -> bool:
    hour = datetime.now().hour
    if QUIET_HOURS_START > QUIET_HOURS_END:
        return hour >= QUIET_HOURS_START or hour < QUIET_HOURS_END
    return QUIET_HOURS_START <= hour < QUIET_HOURS_END


def _ha_call_service(domain: str, service: str, data: dict) -> bool:
    """Call a Home Assistant service via REST API. Retries once on failure."""
    url = f"{HA_URL}/api/services/{domain}/{service}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }
    for attempt in range(2):
        try:
            resp = requests.post(url, json=data, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                log.info("HA service %s/%s OK (attempt %d)", domain, service, attempt + 1)
                return True
            log.warning("HA service %s/%s returned %d: %s (attempt %d)",
                        domain, service, resp.status_code, resp.text[:200], attempt + 1)
        except requests.RequestException as exc:
            log.warning("HA service %s/%s failed: %s (attempt %d)",
                        domain, service, exc, attempt + 1)
        if attempt == 0:
            time.sleep(1)
    return False


def _action_save_clip(camera: str, event_id: str = "") -> bool:
    """Retain the Frigate event clip via Frigate REST API and export it."""
    if not event_id:
        log.warning("save_clip called without event_id for %s", camera)
        return False
    # Mark event for indefinite retention
    try:
        retain_url = f"{FRIGATE_API}/api/events/{event_id}/retain"
        resp = requests.post(retain_url, timeout=10)
        if resp.status_code in (200, 201):
            log.info("Frigate event %s marked for retention", event_id)
        else:
            log.warning("Frigate retain for %s returned %d", event_id, resp.status_code)
    except requests.RequestException as exc:
        log.warning("Frigate retain for %s failed: %s", event_id, exc)

    # Export the clip to storage for WhatsApp delivery
    clip_dir = SNAPSHOT_DIR.parent / "ai-clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    clip_path = clip_dir / f"{event_id}.mp4"
    try:
        clip_url = f"{FRIGATE_API}/api/events/{event_id}/clip.mp4"
        resp = requests.get(clip_url, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 1000:
            clip_path.write_bytes(resp.content)
            log.info("Saved clip %s (%d bytes)", clip_path, len(resp.content))
            return True
        log.warning("Clip download for %s returned %d (%d bytes)", event_id, resp.status_code, len(resp.content))
    except requests.RequestException as exc:
        log.warning("Clip download for %s failed: %s", event_id, exc)
    return False


def _action_light(camera: str) -> bool:
    """Turn on zone lights for the camera."""
    entities = CAMERA_ZONE_LIGHTS.get(camera, CAMERA_ZONE_LIGHTS_DEFAULT)
    ok = True
    for entity in entities:
        if not _ha_call_service("light", "turn_on", {
            "entity_id": entity,
            "brightness_pct": 100,
        }):
            ok = False
    return ok


def _action_speaker(camera: str, tts_msg: str) -> bool:
    """Announce on Alexa speakers via notify service."""
    return _ha_call_service("notify", "alexa_media", {
        "message": tts_msg,
        "target": [
            "media_player.ravi_s_echo_dot",
            "media_player.echo_show_5",
            "media_player.ravi_s_old_echo_dot",
            "media_player.mom_s_echo",
        ],
        "data": {"type": "announce"},
    })


def _action_alarm() -> bool:
    """Activate the siren / alarm switch."""
    return _ha_call_service("switch", "turn_on", {
        "entity_id": ALARM_ENTITY,
    })


def execute_action(decision: dict, camera: str, tts_msg: str, event_id: str = "") -> None:
    """Execute the HA action from the decision JSON.

    Safety rules:
    - low risk always forced to notify_only
    - Unknown actions fall back to notify_only
    - Quiet hours suppress speaker unless critical
    - Failure in any sub-action falls back to notify_only (already published via MQTT)
    """
    action = decision.get("action", "notify_only")
    risk = decision.get("risk", "low")

    # Safety: force low risk to notify_only
    if risk == "low":
        action = "notify_only"

    # Safety: reject unknown actions
    if action not in ALLOWED_ACTIONS:
        log.warning("Unknown action '%s' — forcing notify_only", action)
        action = "notify_only"

    log.info("Executing action: %s (risk=%s, camera=%s)", action, risk, camera)

    if action == "notify_only":
        return  # already published via MQTT, nothing else to do

    if action == "notify_and_save_clip":
        if not _action_save_clip(camera, event_id=event_id):
            log.error("Failed to save clip for %s — fallback to notify_only", camera)
        return

    if action == "notify_and_light":
        _action_save_clip(camera, event_id=event_id)  # always save clip for high risk
        if not _action_light(camera):
            log.error("Failed to turn on lights for %s — fallback to notify_only", camera)
        return

    if action == "notify_and_speaker":
        if _is_quiet_hours() and risk != "critical":
            log.info("Suppressing speaker during quiet hours (risk=%s)", risk)
            return
        if not _action_speaker(camera, tts_msg):
            log.error("Failed to announce on speakers — fallback to notify_only")
        return

    if action == "notify_and_alarm":
        # Alarm is the highest escalation — also turn on lights
        _action_light(camera)
        if not _action_alarm():
            log.error("Failed to activate alarm — fallback to notify_only")
        if not _is_quiet_hours() or risk == "critical":
            _action_speaker(camera, tts_msg)
        return


def make_tts(camera: str, analysis: str, decision: dict | None = None, policy: dict | None = None) -> str:
    """Create a descriptive Alexa spoken security briefing."""
    if decision is None:
        decision = {}
    if policy is None:
        policy = {}

    risk = str(decision.get("risk", "low")).lower()
    det_type = str(decision.get("type", "person")).replace("_", " ")
    reason = str(decision.get("reason", ""))
    action = str(decision.get("action", "notify_only")).replace("_", " ")
    camera_zone = str(policy.get("camera_zone", "")).replace("-", " ")
    behavior = str(decision.get("behavior", ""))

    # Severity word for speech
    severity_word = {
        "low": "low priority",
        "medium": "medium priority. Please review.",
        "high": "high priority. Attention required.",
        "critical": "critical. Immediate attention required.",
    }.get(risk, "")

    # Subject description from AI
    subject_obj = decision.get("subject", {})
    if isinstance(subject_obj, dict) and subject_obj.get("description"):
        subject_desc = str(subject_obj["description"])
    else:
        subject_desc = det_type

    # Build speech
    parts = [f"Security alert from {camera}."]
    parts.append(f"Severity: {severity_word}")
    parts.append(f"{subject_desc} detected in {camera_zone} area.")

    if behavior:
        # Keep behavior short for speech
        beh_short = behavior.split(".")[0].strip()
        if beh_short and len(beh_short) < 120:
            parts.append(beh_short + ".")

    if reason and len(reason) < 100:
        parts.append(f"Risk assessment: {reason}.")

    if risk in ("medium", "high", "critical"):
        if "clip" in action:
            parts.append("Clip has been saved.")
        if "light" in action:
            parts.append("Lights have been turned on.")
        if "alarm" in action:
            parts.append("Alarm has been activated.")

    return " ".join(parts)


def publish_analysis(client: mqtt.Client, camera: str, label: str,
                     analysis: str, event_id: str, snapshot_path: Path,
                     decision: dict | None = None, policy: dict | None = None):
    """Publish structured AI analysis to MQTT for Home Assistant."""
    if decision is None:
        decision = _fallback_decision(analysis)
    if policy is None:
        policy = {}

    risk = str(decision.get("risk", "low")).lower()
    risk_upper = risk.upper()
    det_type = str(decision.get("type", "other")).replace("_", " ").title()
    confidence = decision.get("confidence", 0.0)
    reason = str(decision.get("reason", ""))
    action = str(decision.get("action", "notify_only"))
    behavior = str(decision.get("behavior", ""))
    camera_zone = str(policy.get("camera_zone", "unknown")).replace("-", " ").title()
    home_mode = str(policy.get("home_mode", "unknown")).title()
    time_of_day = str(policy.get("time_of_day", "unknown")).title()
    now_ts = datetime.now(timezone.utc)

    # Subject info
    subject_obj = decision.get("subject", {})
    if isinstance(subject_obj, dict):
        identity = str(subject_obj.get("identity", "unknown")).title()
        subject_desc = str(subject_obj.get("description", det_type))
    else:
        identity = "Unknown"
        subject_desc = det_type

    # Clean analysis text (no JSON, no MEDIA lines)
    clean_analysis = strip_json_block(analysis).strip()
    clean_lines = []
    for line in clean_analysis.splitlines():
        s = line.strip()
        if not s or s.lower().startswith("media:") or "ai-snapshots/" in s.lower():
            continue
        if s.lower().startswith("attached"):
            continue
        clean_lines.append(s)
    clean_analysis = "\n".join(clean_lines).strip()

    # Build structured analysis for HA persistent notification
    severity_emoji = {"low": "\U0001f7e2", "medium": "\U0001f7e1", "high": "\U0001f7e0", "critical": "\U0001f534"}
    s_icon = severity_emoji.get(risk, "")
    ha_analysis = (
        f"{s_icon} Risk: {risk_upper}\n"
        f"Time: {now_ts.strftime('%H:%M:%S')}\n\n"
        f"Subject: {identity} — {subject_desc}\n\n"
    )
    if behavior:
        ha_analysis += f"Behavior: {behavior}\n\n"
    if clean_analysis:
        ha_analysis += f"Security Assessment:\n{clean_analysis}\n\n"
    ha_analysis += (
        f"Confidence: {confidence:.2f}\n"
        f"Reason: {reason}\n\n"
        f"Context: {camera_zone} | {home_mode} | {time_of_day}\n"
        f"Action: {action.replace('_', ' ').title()}"
    )

    # Media info
    media_decision = decide_media(risk)

    payload = {
        "camera": camera,
        "label": label,
        "analysis": ha_analysis,
        "risk": risk,
        "type": str(decision.get("type", "other")),
        "confidence": confidence,
        "action": action,
        "reason": reason,
        "behavior": behavior,
        "subject_identity": identity,
        "subject_description": subject_desc,
        "camera_zone": camera_zone,
        "home_mode": home_mode,
        "time_of_day": time_of_day,
        "media_snapshot": media_decision["snapshot"],
        "media_clip": media_decision["clip"],
        "media_clip_length": media_decision["clip_length"],
        "media_monitoring": media_decision["monitoring"],
        "tts": make_tts(camera, analysis, decision, policy),
        "timestamp": now_ts.isoformat(),
        "event_id": event_id,
        "snapshot_path": str(snapshot_path),
        "clip_url": f"http://192.168.1.10:5000/api/events/{event_id}/clip.mp4" if media_decision["clip"] else "",
    }
    result = client.publish(MQTT_TOPIC_PUBLISH, json.dumps(payload), qos=1, retain=True)
    log.info("Published analysis to %s (rc=%s)", MQTT_TOPIC_PUBLISH, result.rc)


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to MQTT broker %s:%d", MQTT_HOST, MQTT_PORT)
        client.subscribe(MQTT_TOPIC_SUBSCRIBE)
        log.info("Subscribed to %s", MQTT_TOPIC_SUBSCRIBE)
    else:
        log.error("MQTT connection failed with code %s", rc)


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
    except (json.JSONDecodeError, ValueError):
        return

    before = data.get("before", {})
    after = data.get("after", {})
    event_type = data.get("type", "")

    # Only process new person detections
    if event_type != "new":
        return

    label = after.get("label", "")
    if label != "person":
        return

    camera = after.get("camera", "unknown")
    event_id = after.get("id", "")

    if not event_id:
        return

    log.info("Person detected on %s (event %s)", camera, event_id)
    if PHASE3_ENABLED:
        policy = get_policy_context(camera)
    else:
        policy = {
            "time_of_day": "unknown",
            "home_mode": "unknown",
            "known_faces_present": False,
            "camera_context": "unspecified",
            "camera_zone": CAMERA_POLICY_ZONE_DEFAULT,
            "recent_events_count": 0,
            "recent_events_last_ts": "none",
        }
    history_summary = _recent_events_summary(camera) if PHASE4_ENABLED else "- disabled"
    if PHASE3_ENABLED:
        log.info("Policy context for %s: %s", camera, policy)
    if PHASE4_ENABLED:
        log.info("Recent events summary for %s: %s", camera, history_summary.replace("\n", " | "))

    if EXCLUDE_KNOWN_FACES and bool(policy.get("known_faces_present", False)):
        log.info("Skipping %s — known faces present and exclude_known_faces=true", event_id)
        publish_analysis(
            client, camera, label,
            f"Person detected on {camera} — ignored because known face was detected.",
            event_id, Path(""),
            {"risk": "low", "type": "known_person", "confidence": 0.95, "action": "notify_only", "reason": "known face excluded"},
        )
        return

    if is_on_cooldown(camera):
        log.info("Skipping %s — cooldown active for %s", event_id, camera)
        return

    # Wait for snapshot to be ready
    time.sleep(3)

    snapshot_path = download_snapshot(event_id)
    if not snapshot_path:
        return

    # Stage the snapshot for OpenClaw media delivery
    staged_path = stage_snapshot_for_openclaw(snapshot_path, event_id)
    if not staged_path:
        return

    # Publish immediate "pending" notice to HA
    publish_analysis(
        client, camera, label,
        f"Person detected on {camera} — vision analysis pending.",
        event_id, snapshot_path,
    )

    analysis = send_to_openclaw(camera, event_id, policy, history_summary)
    if analysis:
        decision = sanitize_decision(parse_decision_json(analysis))
        # Pillar 2: Apply rule-based severity scoring (overrides AI if rules disagree)
        rule_risk = score_severity(decision, policy)
        ai_risk = str(decision.get("risk", "low")).lower()
        if rule_risk != ai_risk:
            log.info("Rule engine adjusted risk: AI=%s -> Rules=%s for %s", ai_risk, rule_risk, event_id)
            decision["risk"] = rule_risk
            # Re-map action based on new risk
            risk_action_map = {"low": "notify_only", "medium": "notify_and_save_clip", "high": "notify_and_light", "critical": "notify_and_alarm"}
            decision["action"] = risk_action_map.get(rule_risk, decision.get("action", "notify_only"))
        analysis_text = strip_json_block(analysis)
        decision, confirmation_note = maybe_confirm_decision(
            camera=camera,
            event_id=event_id,
            decision=decision,
            policy=policy,
            recent_events_summary=history_summary,
        )
        decision = sanitize_decision(decision)
        if confirmation_note:
            analysis_text = f"{analysis_text}\n\n{confirmation_note}".strip()
        publish_analysis(client, camera, label, analysis_text, event_id,
                         snapshot_path, decision, policy)
        # Only send medium/high/critical alerts to WhatsApp (Phase 3 policy)
        # Phase 2 — execute the decided action via HA REST API (also saves clips)
        tts_msg = make_tts(camera, analysis_text, decision, policy)
        execute_action(decision, camera, tts_msg, event_id=event_id)
        # WhatsApp delivery — only medium/high/critical (clip saved above is now available)
        alert_risk = decision.get("risk", "low")
        if alert_risk in ("medium", "high", "critical"):
            deliver_whatsapp_message(camera, event_id, analysis_text, decision, policy)
        else:
            log.info("Skipping WhatsApp for %s — risk=%s (only medium+ sent to WhatsApp)", event_id, alert_risk)
        if PHASE4_ENABLED:
            append_event_history(camera, event_id, decision)
        _record_event(camera)


def on_disconnect(client, userdata, flags, rc, properties=None):
    log.warning("Disconnected from MQTT (rc=%s), will reconnect…", rc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("Frigate → OpenClaw bridge starting")
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    client = mqtt.Client(
        client_id="frigate-openclaw-bridge",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    log.info("Connecting to MQTT %s:%d…", MQTT_HOST, MQTT_PORT)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=120)
    client.loop_forever()


if __name__ == "__main__":
    main()
