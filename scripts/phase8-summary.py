#!/usr/bin/env python3
"""Phase 8 summaries from Frigate event history.

Reads JSONL memory written by the bridge (events-history.jsonl), builds a
daily or weekly report, and optionally:
- publishes summary payload to MQTT for Home Assistant
- delivers report text via OpenClaw WhatsApp delivery
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import requests


EVENT_HISTORY_FILE = Path("/home/techposts/frigate/storage/events-history.jsonl")
RUNTIME_CONFIG_FILE = Path("/home/techposts/frigate/bridge-runtime-config.json")
SECRETS_ENV_FILE = Path("/home/techposts/frigate/.secrets.env")

MQTT_HOST = "192.168.0.163"
MQTT_PORT = 1885
MQTT_USER = "mqtt-user"
MQTT_PASS = "techposts"
MQTT_TOPIC_SUMMARY = "openclaw/frigate/summary"

OPENCLAW_DELIVERY_WEBHOOK = "http://localhost:18789/hooks/agent"
OPENCLAW_TOKEN = "frigate-hook-secret-2026"
OPENCLAW_DELIVERY_AGENT_NAME = "main"
WHATSAPP_TO = ["+919958040437", "+919873240906"]
WHATSAPP_ENABLED = True


def load_runtime_config() -> None:
    """Load runtime overrides (shared with bridge)."""
    global EVENT_HISTORY_FILE
    global MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_TOPIC_SUMMARY
    global OPENCLAW_DELIVERY_WEBHOOK, OPENCLAW_TOKEN, OPENCLAW_DELIVERY_AGENT_NAME, WHATSAPP_TO, WHATSAPP_ENABLED
    if not RUNTIME_CONFIG_FILE.exists():
        return
    try:
        cfg = json.loads(RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    def _looks_masked_secret(val) -> bool:
        s = str(val or "").strip()
        return s.startswith("********")
    EVENT_HISTORY_FILE = Path(str(cfg.get("event_history_file", str(EVENT_HISTORY_FILE))))
    MQTT_HOST = str(cfg.get("mqtt_host", MQTT_HOST))
    MQTT_PORT = int(cfg.get("mqtt_port", MQTT_PORT))
    MQTT_USER = str(cfg.get("mqtt_user", MQTT_USER))
    _mqtt_pass = cfg.get("mqtt_pass", MQTT_PASS)
    if not _looks_masked_secret(_mqtt_pass):
        MQTT_PASS = str(_mqtt_pass)
    OPENCLAW_DELIVERY_WEBHOOK = str(cfg.get("openclaw_delivery_webhook", OPENCLAW_DELIVERY_WEBHOOK))
    _oc_token = cfg.get("openclaw_token", OPENCLAW_TOKEN)
    if not _looks_masked_secret(_oc_token):
        OPENCLAW_TOKEN = str(_oc_token)
    OPENCLAW_DELIVERY_AGENT_NAME = str(cfg.get("openclaw_delivery_agent_name", OPENCLAW_DELIVERY_AGENT_NAME))
    recipients = cfg.get("whatsapp_to", WHATSAPP_TO)
    if isinstance(recipients, list) and recipients:
        WHATSAPP_TO = [str(x) for x in recipients]
    WHATSAPP_ENABLED = bool(cfg.get("whatsapp_enabled", WHATSAPP_ENABLED))

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
        except Exception:
            pass


def parse_iso_utc(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_iso_utc(str(row.get("timestamp", "")))
            if not ts:
                continue
            row["_ts"] = ts
            rows.append(row)
    return rows


def filter_window(rows: list[dict], start: datetime, end: datetime) -> list[dict]:
    out = []
    for row in rows:
        ts = row.get("_ts")
        if isinstance(ts, datetime) and start <= ts <= end:
            out.append(row)
    return out


def build_summary(rows: list[dict], period: str, start: datetime, end: datetime) -> tuple[str, dict]:
    total = len(rows)
    by_camera: dict[str, int] = Counter()
    by_risk: dict[str, int] = Counter()
    by_action: dict[str, int] = Counter()
    by_type: dict[str, int] = Counter()
    by_hour: dict[int, int] = Counter()
    conf_by_risk: dict[str, list[float]] = defaultdict(list)

    for r in rows:
        cam = str(r.get("camera", "unknown"))
        risk = str(r.get("risk", "unknown")).lower()
        action = str(r.get("action", "unknown"))
        kind = str(r.get("type", "other"))
        conf = float(r.get("confidence", 0.0))

        by_camera[cam] += 1
        by_risk[risk] += 1
        by_action[action] += 1
        by_type[kind] += 1
        conf_by_risk[risk].append(conf)
        ts = r.get("_ts")
        if isinstance(ts, datetime):
            by_hour[ts.hour] += 1

    peak_hour = None
    if by_hour:
        peak_hour = max(by_hour.items(), key=lambda x: x[1])[0]

    high_count = by_risk.get("high", 0)
    critical_count = by_risk.get("critical", 0)
    escalations = by_action.get("notify_and_alarm", 0) + by_action.get("notify_and_light", 0)

    lines = []
    lines.append(f"Frigate {period.title()} Summary")
    lines.append(f"Window: {start.isoformat()} to {end.isoformat()}")
    lines.append(f"Total events: {total}")
    lines.append(f"High/Critical: {high_count + critical_count} ({high_count}/{critical_count})")
    lines.append(f"Escalation actions: {escalations}")
    if peak_hour is not None:
        lines.append(f"Peak hour (UTC): {peak_hour:02d}:00")

    if by_camera:
        cams = ", ".join(f"{k}:{v}" for k, v in sorted(by_camera.items()))
        lines.append(f"By camera: {cams}")
    if by_risk:
        risks = ", ".join(f"{k}:{v}" for k, v in sorted(by_risk.items()))
        lines.append(f"By risk: {risks}")
    if by_type:
        top_types = sorted(by_type.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append("Top types: " + ", ".join(f"{k}:{v}" for k, v in top_types))

    # Simple insights
    if total == 0:
        lines.append("Insight: no events in this window.")
    else:
        if high_count + critical_count == 0:
            lines.append("Insight: no high-risk detections in this window.")
        elif (high_count + critical_count) / max(total, 1) > 0.4:
            lines.append("Insight: elevated risk ratio, review camera zones and lighting.")
        else:
            lines.append("Insight: risk distribution looks stable.")

    payload = {
        "period": period,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "total_events": total,
        "by_camera": dict(by_camera),
        "by_risk": dict(by_risk),
        "by_action": dict(by_action),
        "by_type": dict(by_type),
        "peak_hour_utc": peak_hour,
        "text": "\n".join(lines),
    }
    return payload["text"], payload


def format_summary_whatsapp(payload: dict) -> str:
    """Build strict plain-text summary format for WhatsApp delivery."""
    period = str(payload.get("period", "daily")).title()
    start = str(payload.get("window_start", ""))
    end = str(payload.get("window_end", ""))
    total = int(payload.get("total_events", 0))
    by_risk = payload.get("by_risk") or {}
    by_camera = payload.get("by_camera") or {}
    by_type = payload.get("by_type") or {}
    peak_hour = payload.get("peak_hour_utc")

    high = int(by_risk.get("high", 0))
    critical = int(by_risk.get("critical", 0))
    escalations = int((payload.get("by_action") or {}).get("notify_and_alarm", 0)) + int(
        (payload.get("by_action") or {}).get("notify_and_light", 0)
    )

    lines = []
    lines.append(f"Frigate {period} Summary")
    lines.append(f"Window (UTC): {start} to {end}")
    lines.append(f"Total events: {total}")
    lines.append(f"High/Critical events: {high + critical} ({high}/{critical})")
    lines.append(f"Escalation actions: {escalations}")
    if peak_hour is not None:
        lines.append(f"Peak hour (UTC): {int(peak_hour):02d}:00")
    if by_camera:
        cam_s = ", ".join(f"{k}:{v}" for k, v in sorted(by_camera.items()))
        lines.append(f"By camera: {cam_s}")
    if by_risk:
        risk_s = ", ".join(f"{k}:{v}" for k, v in sorted(by_risk.items()))
        lines.append(f"By risk: {risk_s}")
    if by_type:
        top_types = sorted(by_type.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append("Top types: " + ", ".join(f"{k}:{v}" for k, v in top_types))

    insight = "No high-risk detections in this window."
    if total == 0:
        insight = "No events in this window."
    elif (high + critical) / max(total, 1) > 0.4:
        insight = "Elevated risk ratio; review camera zones and lighting."
    lines.append(f"Insight: {insight}")
    return "\n".join(lines)


def publish_mqtt(payload: dict) -> None:
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    info = client.publish(MQTT_TOPIC_SUMMARY, json.dumps(payload), qos=1, retain=True)
    info.wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()


def deliver_whatsapp(payload_data: dict) -> None:
    if not WHATSAPP_ENABLED:
        raise RuntimeError("whatsapp delivery disabled by config")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
    }
    sent = 0
    ts = int(datetime.now(timezone.utc).timestamp())
    report_body = format_summary_whatsapp(payload_data)
    delivery_message = (
        "You are sending a WhatsApp notification.\n"
        "Return only the report body exactly as plain text.\n"
        "Do not add markdown, bullets, headings with #, or any extra commentary.\n"
        "Do not add 'Current time'.\n"
        "REPORT BODY START\n"
        f"{report_body}\n"
        "REPORT BODY END"
    )
    for number in WHATSAPP_TO:
        to = str(number).strip()
        if not to:
            continue
        payload = {
            "message": delivery_message,
            "deliver": True,
            "channel": "whatsapp",
            "to": to,
            "name": "Frigate Summary",
            "sessionKey": f"frigate:summary:{OPENCLAW_DELIVERY_AGENT_NAME}:{to}:{ts}",
            "timeoutSeconds": 60,
        }
        resp = requests.post(OPENCLAW_DELIVERY_WEBHOOK, json=payload, headers=headers, timeout=30)
        if resp.status_code >= 300:
            raise RuntimeError(f"delivery failed for {to}: HTTP {resp.status_code} {resp.text[:200]}")
        sent += 1
        print(f"WhatsApp accepted for {to}: HTTP {resp.status_code}")
    if sent == 0:
        raise RuntimeError("no valid WhatsApp recipients configured")


def main() -> int:
    load_runtime_config()
    parser = argparse.ArgumentParser(description="Generate Phase 8 daily/weekly summaries.")
    parser.add_argument("--period", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--deliver-whatsapp", action="store_true")
    parser.add_argument("--publish-mqtt", action="store_true")
    args = parser.parse_args()

    end = datetime.now(timezone.utc)
    if args.period == "daily":
        start = end - timedelta(days=1)
    else:
        start = end - timedelta(days=7)

    rows = load_rows(EVENT_HISTORY_FILE)
    window_rows = filter_window(rows, start, end)
    text, payload = build_summary(window_rows, args.period, start, end)
    print(text)

    if args.publish_mqtt:
        publish_mqtt(payload)
        print(f"Published summary to MQTT topic: {MQTT_TOPIC_SUMMARY}")

    if args.deliver_whatsapp:
        deliver_whatsapp(payload)
        print("Delivered summary to WhatsApp recipients")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
