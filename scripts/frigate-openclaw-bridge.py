#!/usr/bin/env python3
"""
Frigate → OpenClaw Bridge
Listens for Frigate person-detection events via MQTT, downloads the snapshot,
sends it to OpenClaw for GPT-4o-mini vision analysis, and publishes the
analysis back to MQTT for Home Assistant.
"""

import json
import logging
import os
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
OPENCLAW_WEBHOOK = "http://localhost:18789/hooks/agent"
OPENCLAW_TOKEN = "<HOOK_TOKEN>"
OPENCLAW_SESSIONS_DIR = Path("/home/<HOME_USER>/.openclaw/agents/main/sessions")
OPENCLAW_SESSIONS_INDEX = OPENCLAW_SESSIONS_DIR / "sessions.json"

SNAPSHOT_DIR = Path("/home/<HOME_USER>/frigate/storage/ai-snapshots")
OPENCLAW_WORKSPACE = Path("/home/<HOME_USER>/.openclaw/workspace")
OPENCLAW_MEDIA_DIR = OPENCLAW_WORKSPACE / "ai-snapshots"
WHATSAPP_TO = ["+1234567890"]

COOLDOWN_SECONDS = 30  # minimum gap between alerts per camera

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("frigate-bridge")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
last_alert: dict[str, float] = {}  # camera -> epoch of last alert


def is_on_cooldown(camera: str) -> bool:
    now = time.time()
    if camera in last_alert and (now - last_alert[camera]) < COOLDOWN_SECONDS:
        return True
    last_alert[camera] = now
    return False


def download_snapshot(event_id: str) -> Path | None:
    """Download snapshot (or thumbnail fallback) from Frigate API."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    dest = SNAPSHOT_DIR / f"{event_id}.jpg"

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


def send_to_openclaw(camera: str, event_id: str) -> str | None:
    """POST the snapshot to OpenClaw webhook for GPT-4o-mini vision analysis.
    Sends analysis to all numbers in WHATSAPP_TO. The first request does the
    actual analysis; subsequent ones just deliver the same result."""
    # OpenClaw only allows MEDIA:./relative paths for security
    # MEDIA lines must be relative and cannot use ".." per OpenClaw security rules.
    # The gateway runs with HOME=/home/<HOME_USER>, so use a workspace-relative path.
    openclaw_rel_media = f"./.openclaw/workspace/ai-snapshots/{event_id}.jpg"
    openclaw_abs_media = str(OPENCLAW_MEDIA_DIR / f"{event_id}.jpg")

    prompt = (
        f"Security alert from camera '{camera}'. "
        f"Use the image tool to open and analyze the snapshot at: {openclaw_abs_media}\n\n"
        "IMPORTANT: You CAN and MUST use the image tool to view the snapshot. "
        "Do NOT say you cannot analyze the image — you have the image tool available. "
        "Open the image first, then respond.\n\n"
        "After viewing the image, your reply MUST have exactly two parts:\n\n"
        "PART 1 — Send the snapshot image using this exact line:\n"
        f"MEDIA:{openclaw_rel_media}\n\n"
        "PART 2 — Below the MEDIA line, provide a brief security assessment:\n"
        f"[{camera}] Threat: LOW/MEDIUM/HIGH\n"
        "Description of what you see. Recommended action if any.\n\n"
        "Rules:\n"
        "- 3-5 sentences max, this goes to a phone notification\n"
        "- Be factual and direct, no questions or disclaimers\n"
        "- Do NOT ask the user anything, just report what you see\n"
        "- Always include the MEDIA line BEFORE the text analysis"
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
    }

    analysis = None

    # Deliver to WhatsApp (webhook returns 202; actual reply is async)
    for number in WHATSAPP_TO:
        payload = {
            "message": prompt,
            "model": "openai/gpt-4o-mini",
            "deliver": True,
            "channel": "whatsapp",
            "to": number,
            "name": "Frigate",
            "sessionKey": f"frigate:{camera}:{event_id}",
            "timeoutSeconds": 60,
        }

        try:
            resp = requests.post(
                OPENCLAW_WEBHOOK,
                json=payload,
                headers=headers,
                timeout=90,
            )
            if resp.status_code in (200, 201, 202):
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                result = data.get("reply") or data.get("response") or data.get("message", "")
                log.info("OpenClaw → %s (%d): %s", number, resp.status_code, result[:120])
                if not analysis and result:
                    analysis = result
            else:
                log.error("OpenClaw → %s returned %d: %s", number, resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.error("OpenClaw → %s failed: %s", number, exc)

    # Pull the completed reply from OpenClaw session logs (async result)
    session_key = f"frigate:{camera}:{event_id}"
    session_analysis = read_openclaw_session_reply(session_key, timeout_seconds=75)
    if session_analysis:
        analysis = session_analysis

    return analysis


def read_openclaw_session_reply(session_key: str, timeout_seconds: int = 60) -> str | None:
    """Read the latest assistant reply from OpenClaw session logs for a session key."""
    if not OPENCLAW_SESSIONS_INDEX.exists():
        log.warning("OpenClaw sessions index not found: %s", OPENCLAW_SESSIONS_INDEX)
        return None

    # Session keys are normalized to lower-case in OpenClaw's sessions index
    norm_key = session_key.strip().lower()
    full_key = f"agent:main:{norm_key}"

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


def make_tts(camera: str, analysis: str) -> str:
    """Create a short spoken version of the analysis for Alexa TTS."""
    sentences = analysis.replace("\n", " ").split(". ")
    short = ". ".join(sentences[:2]).strip()
    if short and not short.endswith("."):
        short += "."
    return f"Security alert, {camera}. {short}"


def publish_analysis(client: mqtt.Client, camera: str, label: str,
                     analysis: str, event_id: str, snapshot_path: Path):
    """Publish the AI analysis to MQTT for Home Assistant."""
    risk = extract_risk(analysis)
    payload = {
        "camera": camera,
        "label": label,
        "analysis": analysis,
        "risk": risk,
        "tts": make_tts(camera, analysis),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id,
        "snapshot_path": str(snapshot_path),
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
        log.error("MQTT connection failed with code %d", rc)


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

    analysis = send_to_openclaw(camera, event_id)
    if analysis:
        publish_analysis(client, camera, label, analysis, event_id, snapshot_path)


def on_disconnect(client, userdata, rc, properties=None):
    log.warning("Disconnected from MQTT (rc=%d), will reconnect…", rc)


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
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
