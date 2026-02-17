#!/usr/bin/env python3
"""Drishtik control panel (API + UI) on a unique port.

No third-party dependencies; uses stdlib HTTP server.
"""

from __future__ import annotations

import argparse
import json
import time
import subprocess
import socket
import secrets
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib import request as ureq
from urllib import error as uerr


APP_HOST = "0.0.0.0"
APP_PORT = 18777
CONFIG_PATH = Path("/home/techposts/frigate/bridge-runtime-config.json")
SECRETS_ENV_PATH = Path("/home/techposts/frigate/.secrets.env")
BRIDGE_SERVICE = "frigate-openclaw-bridge"
BRIDGE_FILE = "/home/techposts/frigate/frigate-openclaw-bridge.py"
SUMMARY_FILE = "/home/techposts/frigate/phase8-summary.py"
VENV_PYTHON = "/home/techposts/frigate/bridge-venv/bin/python3"
FRIGATE_CONFIG_FILE = Path("/home/techposts/frigate/config.yml")
FRIGATE_COMPOSE_FILE = "/home/techposts/frigate/docker-compose.yml"
ACTION_HISTORY_FILE = Path("/home/techposts/frigate/storage/control-actions.jsonl")
CONFIG_VERSIONS_DIR = Path("/home/techposts/frigate/storage/config-versions")
OPENCLAW_CONFIG_FILE = Path("/home/techposts/.openclaw/openclaw.json")
OPENCLAW_CONFIG_BACKUPS_DIR = Path("/home/techposts/frigate/storage/openclaw-config-backups")
SESSION_TTL_SECONDS = 24 * 3600
SESSIONS: dict[str, dict] = {}
APPROVAL_TTL_SECONDS = 15 * 60
APPROVALS: dict[str, dict] = {}


DEFAULT_CONFIG = {
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_pass": "",
    "mqtt_topic_subscribe": "frigate/events",
    "mqtt_topic_publish": "openclaw/frigate/analysis",
    "frigate_api": "http://localhost:5000",
    "openclaw_analysis_webhook": "http://localhost:18789/hooks/agent",
    "openclaw_delivery_webhook": "http://localhost:18789/hooks/agent",
    "openclaw_token": "",
    "openclaw_analysis_agent_name": "main",
    "openclaw_delivery_agent_name": "main",
    "openclaw_analysis_model": "",
    "openclaw_analysis_model_fallback": "",
    "openclaw_analysis_webhook_fallback": "",
    "ollama_api": "",
    "ollama_model": "qwen2.5vl:7b",
    "whatsapp_to": [],
    "cooldown_seconds": 30,
    "ha_url": "",
    "ha_token": "REPLACE_WITH_HA_LONG_LIVED_TOKEN",
    "camera_zone_lights": {},
    "camera_zone_lights_default": [],
    "alarm_entity": "",
    "quiet_hours_start": 23,
    "quiet_hours_end": 6,
    "ha_home_mode_entity": "input_select.home_mode",
    "ha_known_faces_entity": "binary_sensor.known_faces_present",
    "exclude_known_faces": False,
    "camera_context_notes": {},
    "camera_policy_zones": {},
    "camera_policy_zone_default": "entry",
    "recent_events_window_seconds": 600,
    "event_history_file": "",
    "event_history_window_seconds": 1800,
    "event_history_max_lines": 5000,
    "phase3_enabled": True,
    "phase4_enabled": True,
    "phase5_enabled": True,
    "phase8_enabled": True,
    "phase5_confirm_delay_seconds": 4,
    "phase5_confirm_timeout_seconds": 90,
    "phase5_confirm_risks": ["high", "critical"],
    "ui_auth_enabled": True,
    "ui_users": {
        "admin": {"password": "changeme-admin", "role": "admin"},
        "operator": {"password": "changeme-operator", "role": "operator"},
        "viewer": {"password": "changeme-viewer", "role": "viewer"},
    },
    "whatsapp_enabled": True,
    "whatsapp_min_risk_level": "medium",
    "approval_required_high_impact": True,
    "audit_signing_key": "change-me-audit-key",
    "cluster_node_id": "node-1",
    "cluster_peers": [],
}

ALLOWED_KEYS = set(DEFAULT_CONFIG.keys())


def run_cmd(args: list[str], timeout: int | None = None, cwd: str | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout, cwd=cwd)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _read_secrets_env() -> dict:
    if not SECRETS_ENV_PATH.exists():
        return {}
    out = {}
    for ln in SECRETS_ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip("'").strip('"')
    return out


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        out = dict(DEFAULT_CONFIG)
        out.update(raw)
        sec = _read_secrets_env()
        if sec.get("FRIGATE_MQTT_PASS"):
            out["mqtt_pass"] = sec["FRIGATE_MQTT_PASS"]
        if sec.get("OPENCLAW_TOKEN"):
            out["openclaw_token"] = sec["OPENCLAW_TOKEN"]
        if sec.get("HA_TOKEN"):
            out["ha_token"] = sec["HA_TOKEN"]
        return out
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _looks_masked_secret(val) -> bool:
    s = str(val or "").strip()
    return s.startswith("********")


def _role_rank(role: str) -> int:
    return {"viewer": 1, "operator": 2, "admin": 3}.get(str(role), 0)


def _parse_cookie(header: str | None) -> dict:
    out = {}
    if not header:
        return out
    for part in header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k] = v
    return out


def _audit_chain_hash(payload: dict, prev_hash: str, key: str) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + "|" + key + "|" + blob).encode("utf-8")).hexdigest()


def _last_action_hash() -> str:
    if not ACTION_HISTORY_FILE.exists():
        return ""
    try:
        lines = ACTION_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        for ln in reversed(lines):
            if not ln.strip():
                continue
            row = json.loads(ln)
            return str(row.get("hash", ""))
    except Exception:
        return ""
    return ""


def append_action(action: str, ok: bool, details: dict | None = None) -> None:
    payload = {
        "timestamp": time.time(),
        "action": action,
        "ok": bool(ok),
        "details": details or {},
    }
    try:
        ACTION_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg = load_config()
        key = str(cfg.get("audit_signing_key", "change-me-audit-key"))
        prev = _last_action_hash()
        row = dict(payload)
        row["prev_hash"] = prev
        row["hash"] = _audit_chain_hash(payload, prev, key)
        with ACTION_HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception:
        pass


def read_actions(limit: int = 100) -> list[dict]:
    if not ACTION_HISTORY_FILE.exists():
        return []
    rows = []
    for ln in ACTION_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows[-max(1, min(limit, 500)):]


def verify_action_history() -> dict:
    if not ACTION_HISTORY_FILE.exists():
        return {"ok": True, "checked": 0, "signed_checked": 0, "unsigned_legacy": 0, "error": ""}
    cfg = load_config()
    key = str(cfg.get("audit_signing_key", "change-me-audit-key"))
    prev = ""
    checked = 0
    signed_checked = 0
    unsigned_legacy = 0
    for idx, ln in enumerate(ACTION_HISTORY_FILE.read_text(encoding="utf-8").splitlines(), start=1):
        ln = ln.strip()
        if not ln:
            continue
        checked += 1
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            return {"ok": False, "checked": checked, "signed_checked": signed_checked, "unsigned_legacy": unsigned_legacy, "error": f"invalid json at line {idx}"}
        if "hash" not in row or "prev_hash" not in row:
            unsigned_legacy += 1
            continue
        signed_checked += 1
        payload = {k: row.get(k) for k in ("timestamp", "action", "ok", "details")}
        row_prev = str(row.get("prev_hash", ""))
        row_hash = str(row.get("hash", ""))
        if row_prev != prev:
            return {"ok": False, "checked": checked, "signed_checked": signed_checked, "unsigned_legacy": unsigned_legacy, "error": f"chain break at line {idx}"}
        expect = _audit_chain_hash(payload, prev, key)
        if row_hash != expect:
            return {"ok": False, "checked": checked, "signed_checked": signed_checked, "unsigned_legacy": unsigned_legacy, "error": f"hash mismatch at line {idx}"}
        prev = row_hash
    return {"ok": True, "checked": checked, "signed_checked": signed_checked, "unsigned_legacy": unsigned_legacy, "error": ""}


def save_config_version(cfg: dict, reason: str = "", actor: str = "system") -> str:
    CONFIG_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    name = f"config-{ts}.json"
    path = CONFIG_VERSIONS_DIR / name
    envelope = {
        "timestamp": ts,
        "actor": actor,
        "reason": reason,
        "config": cfg,
    }
    path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    return str(path)


def list_config_versions(limit: int = 50) -> list[str]:
    if not CONFIG_VERSIONS_DIR.exists():
        return []
    files = [p for p in CONFIG_VERSIONS_DIR.iterdir() if p.is_file() and p.name.startswith("config-") and p.suffix == ".json"]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in files[:max(1, min(limit, 200))]]


def load_config_version(path_str: str) -> dict:
    p = Path(path_str)
    if not p.exists():
        raise FileNotFoundError(f"config version not found: {p}")
    if p.parent != CONFIG_VERSIONS_DIR:
        raise ValueError("config version must be inside config-versions directory")
    data = json.loads(p.read_text(encoding="utf-8"))
    cfg = data.get("config")
    if not isinstance(cfg, dict):
        raise ValueError("invalid config version format")
    return cfg


def diff_config_dicts(left: dict, right: dict) -> dict:
    keys = sorted(set(left.keys()) | set(right.keys()))
    changed = []
    for k in keys:
        if left.get(k) != right.get(k):
            changed.append({"key": k, "left": left.get(k), "right": right.get(k)})
    return {"changed_count": len(changed), "changes": changed}


def request_approval(action: str, note: str = "", username: str = "unknown") -> dict:
    aid = secrets.token_urlsafe(18)
    now = int(time.time())
    row = {
        "approval_id": aid,
        "action": action,
        "note": note,
        "requested_by": username,
        "issued_at": now,
        "expires_at": now + APPROVAL_TTL_SECONDS,
        "used": False,
    }
    APPROVALS[aid] = row
    return row


def validate_approval(approval_id: str, action: str) -> tuple[bool, str]:
    row = APPROVALS.get(approval_id)
    if not row:
        return False, "invalid approval_id"
    if row.get("used"):
        return False, "approval already used"
    if int(row.get("expires_at", 0)) < int(time.time()):
        return False, "approval expired"
    if str(row.get("action")) != str(action):
        return False, "approval action mismatch"
    row["used"] = True
    APPROVALS[approval_id] = row
    return True, ""


def _tcp_up(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _service_active(name: str) -> bool:
    rc, out, _ = run_cmd(["systemctl", "--user", "is-active", name])
    return rc == 0 and out.strip() == "active"


def _proc_active(pattern: str) -> bool:
    rc, out, _ = run_cmd(["pgrep", "-af", pattern])
    if rc != 0:
        return False
    return any(pattern in line for line in out.splitlines())


def make_health() -> dict:
    cfg = load_config()
    mqtt_host = str(cfg.get("mqtt_host", "127.0.0.1"))
    mqtt_port = int(cfg.get("mqtt_port", 1883))
    ha_url = str(cfg.get("ha_url", "http://127.0.0.1:8123"))
    oc_url = str(cfg.get("openclaw_analysis_webhook", "http://127.0.0.1:18789/hooks/agent"))

    def _host_port(url: str, default_port: int) -> tuple[str, int]:
        try:
            p = urlparse(url)
            return p.hostname or "127.0.0.1", int(p.port or default_port)
        except Exception:
            return "127.0.0.1", default_port

    ha_host, ha_port = _host_port(ha_url, 8123)
    oc_host, oc_port = _host_port(oc_url, 18789)

    # Check Frigate via its API (works even without docker group)
    frigate_running = False
    try:
        import urllib.request as _ureq
        with _ureq.urlopen("http://127.0.0.1:5000/api/version", timeout=3) as _r:
            frigate_running = _r.status == 200
    except Exception:
        # Fallback to docker ps
        rc, _, _ = run_cmd(["docker", "ps", "--format", "{{.Names}}"])
        if rc == 0:
            rc2, out2, _ = run_cmd(["docker", "ps", "--format", "{{.Names}}"])
            frigate_running = "frigate" in out2.splitlines()

    bridge_active = _service_active(BRIDGE_SERVICE) or _proc_active("frigate-openclaw-bridge.py")
    control_panel_active = _service_active("frigate-control-panel") or _proc_active("frigate-control-panel.py")

    return {
        "bridge": bridge_active,
        "control_panel": control_panel_active,
        "frigate": frigate_running,
        "ha": _tcp_up(ha_host, ha_port),
        "openclaw": _tcp_up(oc_host, oc_port),
        "mqtt": _tcp_up(mqtt_host, mqtt_port),
        "updated_at": int(time.time()),
    }


def make_status() -> dict:
    rc, out, err = run_cmd(["systemctl", "--user", "is-active", BRIDGE_SERVICE])
    active = (rc == 0 and out == "active")
    _, svc_out, _ = run_cmd(["systemctl", "--user", "status", BRIDGE_SERVICE, "--no-pager"])
    status_lines = "\n".join(svc_out.splitlines()[:20]) if svc_out else err
    return {
        "bridge_active": active,
        "bridge_state": out or err,
        "service_status_head": status_lines,
        "health": make_health(),
    }


def redacted_config(cfg: dict) -> dict:
    out = dict(cfg)
    for key in ("mqtt_pass", "ha_token", "openclaw_token"):
        v = str(out.get(key, ""))
        if v:
            out[key] = "********" + v[-4:]
    users = out.get("ui_users")
    if isinstance(users, dict):
        red = {}
        for name, u in users.items():
            if isinstance(u, dict):
                red[name] = {"role": u.get("role", "viewer"), "password": "********"}
        out["ui_users"] = red
    return out


def run_summary(period: str, publish_mqtt: bool, deliver_whatsapp: bool) -> tuple[int, str, str]:
    cmd = [VENV_PYTHON, SUMMARY_FILE, "--period", period]
    if publish_mqtt:
        cmd.append("--publish-mqtt")
    if deliver_whatsapp:
        cmd.append("--deliver-whatsapp")
    return run_cmd(cmd)


def send_test_whatsapp(message: str) -> tuple[int, str, str]:
    cfg = load_config()
    webhook = str(cfg.get("openclaw_delivery_webhook", "")).strip()
    token = str(cfg.get("openclaw_token", "")).strip()
    recipients = cfg.get("whatsapp_to", [])
    if not bool(cfg.get("whatsapp_enabled", True)):
        return 1, "", "WhatsApp delivery disabled by config"
    if not webhook or not token:
        return 1, "", "Missing openclaw webhook/token"
    if not isinstance(recipients, list) or not recipients:
        return 1, "", "No whatsapp recipients configured"
    body = {
        "message": message,
        "deliver": True,
        "channel": "whatsapp",
        "to": str(recipients[0]),
        "name": "Frigate Test",
        "sessionKey": f"frigate:notify:test:{int(time.time())}",
        "timeoutSeconds": 60,
    }
    req = ureq.Request(
        webhook,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with ureq.urlopen(req, timeout=15) as resp:
            out = resp.read().decode("utf-8")
            return 0, out, ""
    except Exception as exc:
        return 1, "", str(exc)


def test_openclaw_analysis() -> tuple[int, str, str]:
    cfg = load_config()
    webhook = str(cfg.get("openclaw_analysis_webhook", "")).strip()
    token = str(cfg.get("openclaw_token", "")).strip()
    if not webhook or not token:
        return 1, "", "Missing openclaw analysis webhook/token"
    body = {
        "message": "Health check: reply exactly with OK.",
        "deliver": False,
        "sessionKey": f"frigate:health:analysis:{int(time.time())}",
        "timeoutSeconds": 20,
    }
    req = ureq.Request(
        webhook,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with ureq.urlopen(req, timeout=15) as resp:
            out = resp.read().decode("utf-8")
            return 0, out, ""
    except Exception as exc:
        return 1, "", str(exc)


def openclaw_gateway_cmd(op: str) -> tuple[int, str, str]:
    unit = "openclaw-gateway.service"
    if op == "status":
        return run_cmd(["systemctl", "--user", "status", unit, "--no-pager"])
    if op == "start":
        return run_cmd(["systemctl", "--user", "start", unit])
    if op == "stop":
        return run_cmd(["systemctl", "--user", "stop", unit])
    if op == "restart":
        return run_cmd(["systemctl", "--user", "restart", unit])
    return 1, "", f"unsupported op: {op}"


def load_openclaw_config_text() -> tuple[int, str, str]:
    if not OPENCLAW_CONFIG_FILE.exists():
        return 1, "", f"missing file: {OPENCLAW_CONFIG_FILE}"
    try:
        return 0, OPENCLAW_CONFIG_FILE.read_text(encoding="utf-8"), ""
    except Exception as exc:
        return 1, "", str(exc)


def save_openclaw_config_text(content: str) -> tuple[int, str, str]:
    try:
        parsed = json.loads(content or "{}")
        if not isinstance(parsed, dict):
            return 1, "", "openclaw.json must be a JSON object"
    except Exception as exc:
        return 1, "", f"invalid JSON: {exc}"

    try:
        OPENCLAW_CONFIG_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        if OPENCLAW_CONFIG_FILE.exists():
            stamp = int(time.time())
            b = OPENCLAW_CONFIG_BACKUPS_DIR / f"openclaw.json.bak.{stamp}"
            b.write_text(OPENCLAW_CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        OPENCLAW_CONFIG_FILE.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
        return 0, f"saved {OPENCLAW_CONFIG_FILE}", ""
    except Exception as exc:
        return 1, "", str(exc)


def run_synthetic_trigger(event_id: str, camera: str, label: str) -> tuple[int, str, str]:
    """Trigger a test event using a real Frigate event (for valid snapshot/clip).
    If event_id looks synthetic or has no snapshot, find the latest real event."""
    cfg = load_config()
    frigate_api = cfg.get("frigate_api", "http://localhost:5000")
    m_host = cfg.get("mqtt_host", "127.0.0.1")
    m_port = int(cfg.get("mqtt_port", 1883))
    m_user = cfg.get("mqtt_user", "")
    m_pass = cfg.get("mqtt_pass", "")
    m_topic = cfg.get("mqtt_topic_subscribe", "frigate/events")

    # Try to find a real event with a snapshot
    real_event_id = event_id
    real_camera = camera
    real_label = label
    try:
        import urllib.request, json as _json
        resp = urllib.request.urlopen(f"{frigate_api}/api/events?limit=5&has_snapshot=1", timeout=5)
        events = _json.loads(resp.read())
        if events:
            best = events[0]
            real_event_id = best["id"]
            real_camera = best.get("camera", camera)
            real_label = best.get("label", label)
    except Exception as exc:
        pass  # Fall back to user-provided values

    code = (
        "import json\n"
        "import paho.mqtt.client as mqtt\n"
        f"payload={{'type':'new','before':{{}},'after':{{'id':'{real_event_id}','camera':'{real_camera}','label':'{real_label}'}}}}\n"
        "c=mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)\n"
        f"c.username_pw_set('{m_user}','{m_pass}')\n"
        f"c.connect('{m_host}',{m_port},60)\n"
        f"c.loop_start(); i=c.publish('{m_topic}', json.dumps(payload), qos=1, retain=False)\n"
        "i.wait_for_publish(timeout=5); print(i.rc)\n"
        "c.loop_stop(); c.disconnect()\n"
    )
    rc, out, err = run_cmd([VENV_PYTHON, "-c", code])
    # Add info about which event was used
    info = f"Used event: {real_event_id} (camera={real_camera}, label={real_label})"
    out = f"{out}\n{info}" if out else info
    return rc, out, err


def restart_frigate() -> tuple[int, str, str]:
    """Best-effort Frigate restart using docker compose and container fallback."""
    docker_bin = "/usr/bin/docker" if Path("/usr/bin/docker").exists() else "docker"
    compose_dir = str(Path(FRIGATE_COMPOSE_FILE).parent)
    rc, out, err = run_cmd(
        [docker_bin, "compose", "-f", FRIGATE_COMPOSE_FILE, "restart", "frigate"],
        timeout=60,
        cwd=compose_dir,
    )
    if rc == 0:
        return rc, out, err
    rc2, out2, err2 = run_cmd([docker_bin, "restart", "frigate"], timeout=30)
    if rc2 == 0:
        return rc2, out2, err2
    combined_out = out + ("\n" + out2 if out2 else "")
    combined_err = err + ("\n" + err2 if err2 else "")
    if "timed out" in combined_err.lower():
        combined_err += "\nRestart command timed out. Check docker daemon/container health."
    return rc, combined_out, combined_err


def list_frigate_backups() -> list[str]:
    pattern = "config.yml.bak."
    files = [p for p in FRIGATE_CONFIG_FILE.parent.iterdir() if p.is_file() and p.name.startswith(pattern)]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in files[:30]]


def validate_frigate_config_text(content: str) -> tuple[bool, list[str]]:
    """Heuristic config validation (safe pre-check; not full Frigate parser)."""
    errs: list[str] = []
    text = content or ""
    if not text.strip():
        errs.append("Config is empty.")
        return False, errs
    if "\t" in text:
        errs.append("Tabs found. Use spaces only in YAML.")
    if "mqtt:" not in text:
        errs.append("Missing top-level 'mqtt:' block.")
    if "cameras:" not in text:
        errs.append("Missing top-level 'cameras:' block.")
    for i, ln in enumerate(text.splitlines(), start=1):
        if ln.strip() and ln.startswith(" ") and (len(ln) - len(ln.lstrip(" "))) % 2 != 0:
            errs.append(f"Odd indentation on line {i}. Use consistent 2-space indentation.")
            break
    return len(errs) == 0, errs


def fetch_ha_entities(domain: str | None = None) -> tuple[bool, dict]:
    cfg = load_config()
    ha_url = str(cfg.get("ha_url", "")).rstrip("/")
    token = str(cfg.get("ha_token", "")).strip()
    if not ha_url or not token:
        return False, {"error": "HA URL/token not configured"}
    url = f"{ha_url}/api/states"
    req = ureq.Request(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with ureq.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (uerr.URLError, TimeoutError) as exc:
        return False, {"error": f"HA request failed: {exc}"}
    except Exception as exc:
        return False, {"error": f"HA parse failed: {exc}"}
    entities = []
    for item in data if isinstance(data, list) else []:
        eid = str(item.get("entity_id", ""))
        if not eid:
            continue
        if domain and not eid.startswith(domain + "."):
            continue
        entities.append({
            "entity_id": eid,
            "state": item.get("state"),
            "friendly_name": (item.get("attributes") or {}).get("friendly_name", ""),
        })
    entities.sort(key=lambda x: x["entity_id"])
    return True, {"count": len(entities), "entities": entities}


def _load_event_rows() -> list[dict]:
    cfg = load_config()
    path = Path(str(cfg.get("event_history_file", "/home/techposts/frigate/storage/events-history.jsonl")))
    if not path.exists():
        return []
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows


def reports_data(days: int = 7) -> dict:
    now = int(time.time())
    rows = _load_event_rows()
    buckets = {}
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    action_counts: dict[str, int] = {}
    for i in range(days):
        day = time.strftime("%Y-%m-%d", time.gmtime(now - i * 86400))
        buckets[day] = 0
    for r in rows:
        ts = str(r.get("timestamp", ""))
        day = ts[:10] if len(ts) >= 10 else None
        if day in buckets:
            buckets[day] += 1
            risk = str(r.get("risk", "low")).lower()
            if risk in risk_counts:
                risk_counts[risk] += 1
            action = str(r.get("action", "notify_only"))
            action_counts[action] = action_counts.get(action, 0) + 1
    daily = [{"day": d, "count": buckets[d]} for d in sorted(buckets.keys())]
    return {
        "daily": daily,
        "risk_counts": risk_counts,
        "action_counts": action_counts,
        "total_events": sum(x["count"] for x in daily),
    }


def call_ha_service(domain: str, service: str, data: dict | None = None) -> tuple[int, str, str]:
    cfg = load_config()
    ha_url = str(cfg.get("ha_url", "")).rstrip("/")
    token = str(cfg.get("ha_token", "")).strip()
    if not ha_url or not token:
        return 1, "", "HA URL/token missing"
    payload = data or {}
    req = ureq.Request(
        f"{ha_url}/api/services/{domain}/{service}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with ureq.urlopen(req, timeout=12) as resp:
            out = resp.read().decode("utf-8")
            return 0, out, ""
    except uerr.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        msg = f"HTTP {exc.code}: {exc.reason}"
        if detail:
            msg += f" | {detail}"
        return 1, "", msg
    except Exception as exc:
        return 1, "", str(exc)


def simulate_policy(camera: str, risk: str, action: str, known_faces_present: bool, home_mode: str) -> dict:
    risk_in = str(risk or "low").lower()
    action_in = str(action or "notify_only")
    safe_risk = risk_in if risk_in in {"low", "medium", "high", "critical"} else "low"
    safe_action = action_in if action_in in {
        "notify_only", "notify_and_save_clip", "notify_and_light", "notify_and_speaker", "notify_and_alarm",
    } else "notify_only"

    # enterprise-safe constraints
    if safe_risk in {"low", "medium"} and safe_action in {"notify_and_alarm", "notify_and_speaker", "notify_and_light"}:
        safe_action = "notify_only"
    if known_faces_present and safe_risk in {"low", "medium"}:
        safe_action = "notify_only"
    if home_mode.lower() in {"sleep", "night"} and safe_risk in {"low", "medium"}:
        safe_action = "notify_only"

    out = {
        "camera": camera,
        "input": {
            "risk": risk_in,
            "action": action_in,
            "known_faces_present": bool(known_faces_present),
            "home_mode": home_mode,
        },
        "effective": {
            "risk": safe_risk,
            "action": safe_action,
        },
        "dry_run_only": True,
        "would_execute": {
            "notify": True,
            "light": safe_action == "notify_and_light",
            "speaker": safe_action == "notify_and_speaker",
            "alarm": safe_action == "notify_and_alarm",
        },
    }
    return out


def _rows_within_seconds(rows: list[dict], seconds: int) -> list[dict]:
    now = time.time()
    out = []
    for r in rows:
        ts = str(r.get("timestamp", ""))
        try:
            epoch = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")) if ts else 0.0
        except Exception:
            epoch = 0.0
        if epoch and (now - epoch) <= seconds:
            out.append(r)
    return out


def slo_metrics() -> dict:
    events = _load_event_rows()
    last_24h = _rows_within_seconds(events, 24 * 3600)
    high_critical = sum(1 for r in last_24h if str(r.get("risk", "")).lower() in {"high", "critical"})
    total = len(last_24h)

    actions = read_actions(500)
    now = time.time()
    recent = [a for a in actions if float(a.get("timestamp", 0)) >= now - 7 * 24 * 3600]
    summary = [a for a in recent if a.get("action") == "summary.run"]
    notify_tests = [a for a in recent if a.get("action") == "notify.test"]
    openclaw_tests = [a for a in recent if a.get("action") == "openclaw.test_analysis"]

    def _rate(rows: list[dict]) -> float:
        if not rows:
            return 1.0
        ok = sum(1 for r in rows if bool(r.get("ok", False)))
        return ok / max(1, len(rows))

    return {
        "generated_at": int(now),
        "events_24h": total,
        "high_critical_24h": high_critical,
        "high_critical_ratio_24h": round(high_critical / max(1, total), 4),
        "summary_runs_7d": len(summary),
        "summary_success_rate_7d": round(_rate(summary), 4),
        "notify_test_runs_7d": len(notify_tests),
        "notify_test_success_rate_7d": round(_rate(notify_tests), 4),
        "openclaw_test_runs_7d": len(openclaw_tests),
        "openclaw_test_success_rate_7d": round(_rate(openclaw_tests), 4),
        "service_health_snapshot": make_health(),
        "false_positive_trend": "manual_labeling_required",
    }


def run_test_suite(include_synthetic: bool = False) -> dict:
    started = int(time.time())
    tests = []

    def add(name: str, ok: bool, detail: str = ""):
        tests.append({"name": name, "ok": bool(ok), "detail": detail})

    h = make_health()
    add("bridge_service_active", bool(h.get("bridge")), json.dumps(h))
    add("control_panel_active", bool(h.get("control_panel")), json.dumps(h))
    add("mqtt_reachable", bool(h.get("mqtt")), json.dumps(h))
    add("openclaw_tcp_reachable", bool(h.get("openclaw")), json.dumps(h))

    rc, out, err = test_openclaw_analysis()
    add("openclaw_analysis_webhook", rc == 0, out or err)

    cfg = load_config()
    if bool(cfg.get("whatsapp_enabled", True)):
        rc, out, err = send_test_whatsapp("Control suite WhatsApp delivery test")
        add("whatsapp_delivery_test", rc == 0, out or err)
    else:
        add("whatsapp_delivery_test", True, "skipped (disabled)")

    rc, out, err = run_summary(period="daily", publish_mqtt=False, deliver_whatsapp=False)
    add("summary_generation", rc == 0, out or err)

    if include_synthetic:
        rc, out, err = run_synthetic_trigger("suite-test-event", "TopStairCam", "person")
        add("synthetic_trigger", rc == 0, out or err)
    else:
        add("synthetic_trigger", True, "skipped")

    passed = sum(1 for t in tests if t["ok"])
    return {
        "started_at": started,
        "finished_at": int(time.time()),
        "total": len(tests),
        "passed": passed,
        "failed": len(tests) - passed,
        "ok": passed == len(tests),
        "tests": tests,
    }


def cluster_status() -> dict:
    cfg = load_config()
    node_id = str(cfg.get("cluster_node_id", "node-1"))
    peers = cfg.get("cluster_peers", [])
    if not isinstance(peers, list):
        peers = []
    peer_rows = []
    for p in peers[:20]:
        url = str(p).strip().rstrip("/")
        if not url:
            continue
        try:
            req = ureq.Request(url + "/api/health")
            with ureq.urlopen(req, timeout=4) as resp:
                ok = (resp.status == 200)
                body = resp.read().decode("utf-8")
            peer_rows.append({"peer": url, "ok": ok, "detail": body[:180]})
        except Exception as exc:
            peer_rows.append({"peer": url, "ok": False, "detail": str(exc)})
    return {
        "node_id": node_id,
        "peer_count": len(peer_rows),
        "peers": peer_rows,
        "local_health": make_health(),
    }


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Drishtik Control Panel</title>
  <style>
    :root {
      --bg: #030a03;
      --panel: #061106;
      --line: #183a18;
      --ink: #b8ffb8;
      --ink-dim: #7fd67f;
      --accent: #39ff14;
      --danger: #ff5f5f;
      --space-1: 10px;
      --space-2: 14px;
      --space-3: 18px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at 15% 20%, #0e2a0e 0, transparent 45%),
        radial-gradient(circle at 85% 15%, #0b250b 0, transparent 42%),
        var(--bg);
      color: var(--ink);
      font-family: "JetBrains Mono", "Fira Code", "Menlo", monospace;
      font-size: 15px;
    }
    .wrap { max-width: min(1760px, 97vw); margin: 18px auto; padding: 0 var(--space-2) var(--space-3); }
    .top {
      border: 1px solid var(--line);
      background: linear-gradient(180deg, #061406, #040b04);
      border-radius: 12px;
      padding: var(--space-2);
      margin-bottom: var(--space-2);
    }
    h1 { margin: 0; font-size: clamp(20px, 2.1vw, 30px); color: var(--accent); text-shadow: 0 0 10px rgba(57,255,20,.25); }
    .sub { margin-top: 5px; color: var(--ink-dim); font-size: 13px; }
    .grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: var(--space-2); align-items: start; }
    .menuToggle {
      display: none;
      margin-top: 10px;
      width: 100%;
    }
    .menu {
      display:flex;
      gap:8px;
      flex-wrap: nowrap;
      margin-top: 10px;
      overflow-x: auto;
      scrollbar-width: thin;
      padding-bottom: 4px;
    }
    .menu button { padding:8px 11px; font-size:12px; white-space: nowrap; }
    .menu button.active { border-color:#45b645; box-shadow:0 0 0 1px #45b645 inset; }
    .modeBar { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
    .modeBar button { padding:6px 10px; font-size:12px; }
    .modeBar button.active { border-color:#45b645; box-shadow:0 0 0 1px #45b645 inset; }
    .tabHidden { display:none !important; }
    .health { grid-column: span 12; }
    .card {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: linear-gradient(180deg, #071207, #040a04);
      padding: 12px;
      grid-column: span 12;
    }
    .wide { grid-column: span 12 !important; }
    .card h2 { margin: 0 0 9px; font-size: 15px; color: #95ff95; }
    label { display: block; font-size: 12px; color: var(--ink-dim); margin: 8px 0 5px; }
    input, textarea, select {
      width: 100%;
      border: 1px solid #1e5f1e;
      background: #020602;
      color: var(--ink);
      border-radius: 8px;
      padding: 10px;
      font-family: inherit;
      font-size: 13px;
    }
    textarea { min-height: 120px; }
    .row { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
    .row > * { min-width: 0; }
    .btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 11px; }
    button {
      border: 1px solid #2b7d2b;
      background: #0a260a;
      color: var(--accent);
      border-radius: 8px;
      padding: 9px 12px;
      cursor: pointer;
      font-weight: 600;
      font-family: inherit;
    }
    button.alt { color: #9dc8ff; border-color: #275b8a; background: #081522; }
    button.danger { color: #ffc0c0; border-color: #7f2f2f; background: #2a0d0d; }
    .kpiGrid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .kpi {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px;
      background: #051005;
    }
    .kpi .k { font-size: 11px; color: var(--ink-dim); }
    .kpi .v { font-size: 18px; font-weight: 700; color: var(--accent); margin-top: 3px; }
    .vizGrid { display: grid; grid-template-columns: 1fr; gap: 10px; margin-top: 10px; }
    .vizCard {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #041004;
    }
    .vizCard h3 { margin: 0 0 8px; font-size: 13px; color: #a9f9a9; }
    .chartRows { display: grid; gap: 7px; }
    .chartRow {
      display: grid;
      grid-template-columns: minmax(88px, 140px) 1fr auto;
      align-items: center;
      gap: 8px;
      font-size: 12px;
    }
    .chartLabel { color: #c7fbc7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .chartTrack {
      position: relative;
      height: 10px;
      border-radius: 999px;
      border: 1px solid #225b22;
      background: #021002;
      overflow: hidden;
    }
    .chartFill {
      position: absolute;
      inset: 0 auto 0 0;
      width: 0%;
      border-radius: 999px;
      background: linear-gradient(90deg, #2fa42f, #71ff71);
    }
    .chartValue { font-variant-numeric: tabular-nums; color: #ddffdd; font-size: 12px; }
    .summaryStatus {
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 9px;
      background: #051205;
      font-size: 12px;
      color: #dcffdc;
    }
    .summaryStatus.good { border-color: #2f7f2f; color: #90ff90; }
    .summaryStatus.bad { border-color: #7f2f2f; color: #ffb3b3; }
    .summaryDetailGrid { display: grid; grid-template-columns: 1fr; gap: 7px; margin-top: 10px; }
    .summaryLine {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #040d04;
      padding: 7px 8px;
      font-size: 12px;
      color: #cefbce;
    }
    .pill {
      display: inline-block; border: 1px solid var(--line); border-radius: 999px;
      padding: 3px 8px; font-size: 11px; color: var(--ink-dim); margin-right: 5px;
    }
    .switches { display: grid; grid-template-columns: 1fr; gap: 7px; }
    .sw { border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: #031003; }
    .sw label { margin: 0; color: var(--ink); font-size: 13px; display:flex; gap:8px; align-items:flex-start; flex-wrap: wrap; }
    pre {
      margin: 8px 0 0;
      background: #010401;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: #bfffbf;
      padding: 8px;
      font-size: 12px;
      overflow: auto;
      max-height: 210px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    details { margin-top: 10px; }
    details summary { cursor: pointer; color: #9ddf9d; font-size: 12px; }
    #toast {
      position: fixed; left: 50%; top: 10px; transform: translateX(-50%); z-index: 9999;
      border: 1px solid var(--line); background: #0a180a; color: var(--accent);
      padding: 8px 10px; border-radius: 8px; font-size: 12px; display: none;
      min-width: 220px;
      text-align: center;
    }
    #loginGate {
      position: fixed; inset: 0; z-index: 9998;
      background: rgba(0,0,0,.86);
      display: none;
      align-items: center; justify-content: center;
      padding: 12px;
    }
    #loginCard {
      width: min(420px, 96vw);
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #041004;
      padding: 14px;
    }
    .badges { margin-top: 6px; display:flex; gap:6px; flex-wrap:wrap; }
    .badge { border:1px solid var(--line); border-radius:999px; padding:3px 8px; font-size:11px; }
    .ok { color:#84ff84; border-color:#267326; }
    .bad { color:#ffb0b0; border-color:#7a2f2f; }
    @media (min-width: 760px) {
      .card { grid-column: span 6; }
      .health { grid-column: span 6; }
      .switches { grid-template-columns: 1fr 1fr; }
      .vizGrid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .summaryDetailGrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (min-width: 1400px) {
      .card { grid-column: span 4; }
      .health { grid-column: span 4; }
    }
    @media (max-width: 760px) {
      .wrap { max-width: 100%; margin: 10px auto; padding: 0 10px 14px; }
      .menuToggle { display: inline-block; }
      .menu { display: none; flex-direction: column; }
      .menu.open { display: flex; }
      .menu button { width: 100%; text-align: left; }
      .card, .health, .wide { grid-column: span 12 !important; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h1>Drishtik Control Panel</h1>
      <div class="sub">Simple view for daily changes. Port: <b>18777</b>. Save always applies immediately (bridge restart).</div>
      <div class="modeBar">
        <button id="modeBasic" class="active" onclick="setMode('basic', this)">Simple</button>
        <button id="modeAdvanced" class="alt" onclick="setMode('advanced', this)">Expert</button>
      </div>
      <div class="badges" id="healthBadges"></div>
      <button id="menuToggle" class="menuToggle alt" onclick="toggleMenu()" aria-expanded="false">Menu</button>
      <div class="menu" id="menuTabs">
        <button data-mode="basic advanced" data-role="viewer operator admin" onclick="showPage('dashboard', this)">Overview</button>
        <button data-mode="advanced" data-role="operator admin" onclick="showPage('policies', this)">Features</button>
        <button data-mode="basic advanced" data-role="viewer operator admin" onclick="showPage('ha', this)">Home Assistant</button>
        <button data-mode="basic advanced" data-role="viewer operator admin" onclick="showPage('openclaw', this)">WhatsApp Agent</button>
        <button data-mode="advanced" data-role="admin" onclick="showPage('frigate', this)">Camera NVR</button>
        <button data-mode="basic advanced" data-role="viewer operator admin" onclick="showPage('reports', this)">Summaries</button>
        <button data-mode="advanced" data-role="operator admin" onclick="showPage('metrics', this)">Performance</button>
        <button data-mode="advanced" data-role="operator admin" onclick="showPage('tests', this)">Diagnostics</button>
        <button data-mode="advanced" data-role="operator admin" onclick="showPage('logs', this)">Service Logs</button>
        <button data-mode="advanced" data-role="admin" onclick="showPage('audit', this)">Activity</button>
        <button data-mode="advanced" data-role="admin" onclick="showPage('security', this)">Admin</button>
      </div>
    </div>

    <div class="grid">
      <div class="card health" data-page="dashboard" data-mode="basic advanced">
        <h2>System Health</h2>
        <div class="btns">
          <button onclick="refreshStatus()">Refresh</button>
          <button class="alt" onclick="restartBridge()">Apply / Restart Bridge</button>
        </div>
        <pre id="statusBox">Loading status...</pre>
      </div>

      <div class="card" data-page="ha" data-mode="basic advanced">
        <h2>Core Settings</h2>
        <label>WhatsApp Numbers (comma separated)</label>
        <input id="whatsList" placeholder="+911..., +911..."/>
        <h3 style="margin-top:14px;">MQTT Settings</h3>
        <div class="row">
          <div>
            <label>MQTT Host</label>
            <input id="mqttHost" placeholder="your-server-ip"/>
          </div>
          <div>
            <label>MQTT Port</label>
            <input id="mqttPort" type="number" placeholder="1883"/>
          </div>
        </div>
        <div class="row">
          <div>
            <label>MQTT User</label>
            <input id="mqttUser" placeholder="mqtt-user"/>
          </div>
          <div>
            <label>MQTT Password</label>
            <input id="mqttPass" type="password" placeholder="mqtt password"/>
          </div>
        </div>
        <div class="row">
          <div>
            <label>MQTT Subscribe Topic</label>
            <input id="mqttTopicSub" placeholder="frigate/events"/>
          </div>
          <div>
            <label>MQTT Publish Topic</label>
            <input id="mqttTopicPub" placeholder="openclaw/frigate/analysis"/>
          </div>
        </div>
        <h3 style="margin-top:14px;">Frigate & Ollama</h3>
        <div class="row">
          <div>
            <label>Frigate API URL</label>
            <input id="frigateApi" placeholder="http://localhost:5000"/>
          </div>
          <div>
            <label>Ollama API URL</label>
            <input id="ollamaApi" placeholder="http://ollama-host:11434"/>
          </div>
        </div>
        <div class="row">
          <div>
            <label>Ollama Model</label>
            <input id="ollamaModel" placeholder="qwen2.5vl:7b"/>
          </div>
          <div>
            <label>Cooldown (seconds)</label>
            <input id="cooldownSec" type="number" placeholder="30"/>
          </div>
        </div>
        <div class="row">
          <div>
            <label>Quiet Hours Start</label>
            <input id="quietStart" type="number" min="0" max="23"/>
          </div>
          <div>
            <label>Quiet Hours End</label>
            <input id="quietEnd" type="number" min="0" max="23"/>
          </div>
        </div>
        <label>Home Assistant URL</label>
        <input id="haUrl"/>
        <label>Home Assistant Token</label>
        <input id="haToken" type="password"/>
        <div class="row">
          <div>
            <label>Home Mode Entity</label>
            <input id="homeModeEntity" placeholder="input_select.home_mode"/>
          </div>
          <div>
            <label>Known Faces Entity</label>
            <input id="knownFacesEntity" placeholder="binary_sensor.known_faces_present"/>
          </div>
        </div>
        <div class="sub">Known Faces expects a Home Assistant binary sensor. Auto face recognition requires a face stack (for example Double Take + CompreFace); otherwise use a manual helper sensor.</div>
        <div class="sw" style="margin-top:8px;"><label><input type="checkbox" id="excludeKnownFaces"/> Exclude Known Faces (skip alert + model analysis when known faces are present)</label></div>
        <label style="margin-top:10px;">Camera Context Notes & Light Entities</label>
        <div class="sub">Auto-detected from Frigate. Describe what each camera sees (used in AI prompt).</div>
        <div class="btns" style="margin-bottom:8px;">
          <button class="alt" onclick="refreshCameraFields()">Refresh Cameras from Frigate</button>
          <button class="alt" onclick="discoverHaEntities()">Discover HA Entities</button>
          <button class="alt" onclick="discoverHaControlEntities()">Discover HA Control Entities</button>
        </div>
        <pre id="haDiscoverOut"></pre>
        <div id="cameraFieldsContainer">
          <div class="sub" style="color:#999;">Click "Refresh Cameras from Frigate" or save settings to auto-detect cameras.</div>
        </div>
        <label>Alarm/Siren Entity</label>
        <input id="alarmEntity" placeholder="switch.security_siren"/>
        <div class="row">
          <div>
            <label>HA Test Domain</label>
            <select id="haTestDomain">
              <option value="auto" selected>Auto (from entity)</option>
              <option value="light">light</option>
              <option value="switch">switch</option>
              <option value="input_boolean">input_boolean</option>
              <option value="script">script</option>
              <option value="scene">scene</option>
            </select>
          </div>
          <div>
            <label>HA Test Service</label>
            <input id="haTestService" value="turn_on"/>
          </div>
          <div>
            <label>HA Test Entity ID</label>
            <input id="haTestEntity" placeholder="light.garage"/>
          </div>
        </div>
        <div class="btns">
          <button class="alt" onclick="testHaService()">Test HA Service Call</button>
        </div>
        <pre id="haTestOut"></pre>
        <div class="btns">
          <button onclick="saveQuick()">Save Quick Settings</button>
        </div>
      </div>

      <div class="card" data-page="policies" data-mode="advanced">
        <h2>Features</h2>
        <span class="pill">Smart Policy</span><span class="pill">Event Memory</span><span class="pill">Confirmation Gate</span><span class="pill">Reports</span>
        <div class="switches" style="margin-top:8px;">
          <div class="sw"><label><input type="checkbox" id="phase3"/> Smart Policy</label></div>
          <div class="sw"><label><input type="checkbox" id="phase4"/> Event Memory</label></div>
          <div class="sw"><label><input type="checkbox" id="phase5"/> Confirm Before Escalate</label></div>
          <div class="sw"><label><input type="checkbox" id="phase8"/> Reports & Summaries</label></div>
        </div>
        <div class="btns">
          <button onclick="saveToggles()">Save Feature Switches</button>
        </div>
      </div>

      <div class="card" data-page="openclaw" data-mode="basic advanced">
        <h2>OpenClaw Settings</h2>
        <label>Analysis Webhook</label>
        <input id="ocAnalysisWebhook" placeholder="http://localhost:18789/hooks/agent"/>
        <label>Delivery Webhook</label>
        <input id="ocDeliveryWebhook" placeholder="http://localhost:18789/hooks/agent"/>
        <label>OpenClaw Token</label>
        <input id="ocTokenOpenclaw" type="password"/>
        <div class="row">
          <div>
            <label>Analysis Agent Name</label>
            <input id="ocAnalysisAgent" placeholder="main"/>
          </div>
          <div>
            <label>Delivery Agent Name</label>
            <input id="ocDeliveryAgent" placeholder="main"/>
          </div>
        </div>
        <label>WhatsApp Recipients (comma separated)</label>
        <input id="ocWhatsList" placeholder="+919..., +919..."/>
        <div class="sw"><label><input type="checkbox" id="ocWhatsappEnabled"/> Enable WhatsApp Delivery</label></div>
        <div class="row">
          <div>
            <label>Min Alert Level for WhatsApp</label>
            <select id="ocMinRiskLevel">
              <option value="low">Low (all alerts)</option>
              <option value="medium" selected>Medium (medium+)</option>
              <option value="high">High (high+critical only)</option>
              <option value="critical">Critical only</option>
            </select>
          </div>
        </div>
        <h2 style="margin-top:10px;">OpenClaw WhatsApp Channel Policy</h2>
        <div class="row">
          <div>
            <label>DM Policy</label>
            <input id="ocWaDmPolicy" placeholder="allowlist"/>
          </div>
          <div>
            <label>Group Policy</label>
            <input id="ocWaGroupPolicy" placeholder="allowlist"/>
          </div>
        </div>
        <label>Allow From (comma separated numbers)</label>
        <input id="ocWaAllowFrom" placeholder="+9188..., +9198..."/>
        <div class="btns">
          <button class="alt" onclick="loadOpenClawChannelPolicy()">Load Channel Policy</button>
          <button class="alt" onclick="saveOpenClawChannelPolicy()">Save Channel Policy</button>
        </div>
        <div class="btns">
          <button onclick="saveOpenClawSettings()">Save OpenClaw Settings</button>
          <button class="alt" onclick="testOpenClawAnalysis()">Test Analysis Webhook</button>
          <button class="alt" onclick="sendNotifyTest()">Test WhatsApp Delivery</button>
        </div>
        <div class="btns">
          <button class="alt" onclick="openclawGatewayStatus()">Gateway Status</button>
          <button class="alt" onclick="openclawGatewayStart()">Gateway Start</button>
          <button class="alt" onclick="openclawGatewayStop()">Gateway Stop</button>
          <button class="alt" onclick="openclawGatewayRestart()">Gateway Restart</button>
        </div>
        <details>
          <summary>Edit openclaw.json</summary>
          <textarea id="openclawJsonBox" rows="14" placeholder="OpenClaw config JSON"></textarea>
          <div class="btns">
            <button class="alt" onclick="loadOpenClawConfig()">Load openclaw.json</button>
            <button class="danger" onclick="saveOpenClawConfig()">Save openclaw.json</button>
          </div>
          <pre id="openclawJsonOut">No openclaw.json action yet.</pre>
        </details>
        <pre id="openclawOut">No action yet.</pre>
      </div>

      <div class="card" data-page="reports" data-mode="basic advanced">
        <h2>Run Summary</h2>
        <div class="row">
          <div>
            <label>Period</label>
            <select id="period"><option value="daily">Daily</option><option value="weekly">Weekly</option></select>
          </div>
          <div class="sw"><label><input type="checkbox" id="pubMqtt" checked/> Send to Home Assistant (MQTT)</label></div>
          <div class="sw"><label><input type="checkbox" id="wa"/> Send to WhatsApp</label></div>
        </div>
        <div class="btns">
          <button onclick="runSummary()">Run Report Now</button>
        </div>
        <div id="summaryStatus" class="summaryStatus">No summary run yet.</div>
        <div id="summaryDetailGrid" class="summaryDetailGrid"></div>
        <details>
          <summary>Show Raw Summary Output</summary>
          <pre id="summaryOut">No summary output yet.</pre>
        </details>
        <div class="btns">
          <button class="alt" onclick="refreshReportsGraph()">Refresh Summary Dashboard</button>
        </div>
        <div class="kpiGrid">
          <div class="kpi"><div class="k">Total Events (7d)</div><div class="v" id="kpiTotalEvents">0</div></div>
          <div class="kpi"><div class="k">High + Critical</div><div class="v" id="kpiHighCritical">0</div></div>
          <div class="kpi"><div class="k">High/Critical Ratio</div><div class="v" id="kpiRiskRatio">0%</div></div>
          <div class="kpi"><div class="k">Active Days</div><div class="v" id="kpiActiveDays">0</div></div>
        </div>
        <div class="vizGrid">
          <div class="vizCard">
            <h3>Daily Events</h3>
            <div id="dailyChart" class="chartRows"></div>
          </div>
          <div class="vizCard">
            <h3>Risk Distribution</h3>
            <div id="riskChart" class="chartRows"></div>
          </div>
          <div class="vizCard">
            <h3>Action Distribution</h3>
            <div id="actionChart" class="chartRows"></div>
          </div>
        </div>
        <details>
          <summary>Show Raw Report Data</summary>
          <pre id="reportsGraphOut">No report data loaded.</pre>
        </details>
        <div class="btns">
          <button class="alt" onclick="sendNotifyTest()">Send WhatsApp Test</button>
        </div>
      </div>

      <div class="card" data-page="metrics" data-mode="advanced">
        <h2>Performance Metrics</h2>
        <div class="btns">
          <button onclick="refreshMetrics()">Refresh Metrics</button>
        </div>
        <pre id="metricsOut">No metrics loaded.</pre>
      </div>

      <div class="card" data-page="tests" data-mode="advanced">
        <h2>Diagnostics Suite</h2>
        <div class="sw"><label><input type="checkbox" id="suiteSynthetic"/> Include synthetic trigger</label></div>
        <div class="btns">
          <button onclick="runTestSuite()">Run All Tests</button>
          <button class="alt" onclick="exportTestReport()">Export Last Report</button>
        </div>
        <pre id="testSuiteOut">No suite run yet.</pre>
      </div>

      <div class="card" data-page="tests" data-mode="advanced">
        <h2>Policy Simulator (Dry-Run)</h2>
        <div class="row">
          <div><label>Camera</label><input id="simCamera" value="TopStairCam"/></div>
          <div><label>Risk</label><select id="simRisk"><option>low</option><option>medium</option><option>high</option><option>critical</option></select></div>
          <div><label>Action</label><select id="simAction"><option>notify_only</option><option>notify_and_save_clip</option><option>notify_and_light</option><option>notify_and_speaker</option><option>notify_and_alarm</option></select></div>
        </div>
        <div class="row">
          <div><label>Home Mode</label><input id="simHomeMode" value="home"/></div>
          <div class="sw"><label><input type="checkbox" id="simKnownFaces"/> Known faces present</label></div>
        </div>
        <div class="btns">
          <button onclick="simulatePolicy()">Simulate</button>
        </div>
        <pre id="simOut">No simulation run yet.</pre>
      </div>

      <div class="card wide" data-page="dashboard" data-mode="advanced">
        <h2>Synthetic Event Test</h2>
        <div class="row">
          <div><label>Event ID</label><input id="eventId" value="1771006387.217811-5r946l"/></div>
          <div><label>Camera</label><input id="camera" value="TopStairCam"/></div>
          <div><label>Label</label><input id="label" value="person"/></div>
        </div>
        <div class="btns">
          <button onclick="triggerSynthetic()">Trigger Test Event</button>
        </div>
        <pre id="testOut"></pre>
      </div>

      <div class="card wide" data-page="security" data-mode="advanced">
        <h2>Admin Config (JSON)</h2>
        <details>
          <summary>Show full config editor</summary>
          <textarea id="configBox" rows="18"></textarea>
          <div class="btns">
            <button onclick="reloadConfig()">Reload Config</button>
            <button class="danger" onclick="saveConfig()">Save Full Config + Restart</button>
          </div>
        </details>
        <div class="btns">
          <button class="alt" onclick="verifyAudit()">Verify Audit Chain</button>
          <button class="alt" onclick="refreshCluster()">Cluster Status</button>
          <button class="alt" onclick="refreshSecretsStatus()">Secrets Status</button>
        </div>
        <pre id="securityOut">No security action yet.</pre>
        <h2 style="margin-top:12px;">Config Versions</h2>
        <div class="btns">
          <button class="alt" onclick="listConfigVersions()">List Versions</button>
          <button class="alt" onclick="diffSelectedConfigVersion()">Diff Selected vs Current</button>
          <button class="danger" onclick="rollbackConfigVersion()">Rollback Selected + Restart</button>
        </div>
        <label>Selected Config Version Path</label>
        <input id="cfgVersionPath" placeholder="/home/techposts/frigate/storage/config-versions/config-....json"/>
        <pre id="cfgVersionsOut">No versions loaded.</pre>
      </div>

      <div class="card wide" data-page="dashboard frigate" data-mode="advanced">
        <h2>Frigate Config (config.yml)</h2>
        <details>
          <summary>Show Frigate config editor</summary>
          <textarea id="frigateCfgBox" rows="16" placeholder="Frigate config.yml"></textarea>
          <div class="btns">
            <button onclick="loadFrigateConfig()">Load Frigate Config</button>
            <button class="alt" onclick="listFrigateBackups()">Show Backups</button>
            <button class="alt" onclick="validateFrigateConfig()">Validate Only</button>
            <button class="alt" onclick="saveFrigateConfig(false)">Save Only</button>
            <button class="danger" onclick="saveFrigateConfig(true)">Save + Restart Frigate</button>
            <button onclick="restartFrigate()">Restart Frigate</button>
          </div>
          <pre id="frigateSaveOut">No action yet.</pre>
          <label>Restore Backup (paste full path from list)</label>
          <input id="backupPath" placeholder="/home/techposts/frigate/config.yml.bak.1234567890"/>
          <div class="btns">
            <button class="danger" onclick="restoreFrigateBackup()">Restore Backup + Restart</button>
            <button class="danger" onclick="restoreLatestBackup()">Rollback Latest Backup</button>
          </div>
          <pre id="frigateBackupOut"></pre>
        </details>
      </div>

      <div class="card wide" data-page="logs" data-mode="advanced">
        <h2>Service Logs</h2>
        <div class="row">
          <div>
            <label>Service</label>
            <select id="logService">
              <option value="bridge">Bridge</option>
              <option value="control">Control Panel</option>
            </select>
          </div>
          <div>
            <label>Lines</label>
            <input id="logLines" type="number" min="20" max="1000" value="120"/>
          </div>
        </div>
        <div class="btns">
          <button onclick="refreshLogs()">Refresh Logs</button>
        </div>
        <pre id="logsOut"></pre>
      </div>

      <div class="card wide" data-page="audit" data-mode="advanced">
        <h2>Activity History</h2>
        <div class="btns">
          <button onclick="refreshHistory()">Refresh History</button>
          <button class="alt" onclick="logout()">Logout</button>
        </div>
        <pre id="historyOut"></pre>
      </div>

      <div class="card wide" data-page="dashboard" data-mode="basic advanced">
        <h2>Operator Runbook</h2>
        <pre>1) Save config: use Quick Setup, then verify System Health stays green.
2) If Frigate update fails: Validate Only -> Save Only -> Restart Frigate.
3) If alerts stop: Trigger Synthetic Event, then check Live Logs.
4) If broken: Show Backups -> Restore latest backup.
5) Confirm notification channel: Send WhatsApp Test.
</pre>
      </div>
    </div>
  </div>
  <div id="toast"></div>
  <div id="loginGate">
    <div id="loginCard">
      <h2 style="margin:0 0 8px;color:#9eff9e;">Login</h2>
      <label>Username</label>
      <input id="loginUser" value="admin"/>
      <label>Password</label>
      <input id="loginPass" type="password" value="changeme-admin"/>
      <div class="btns">
        <button onclick="login()">Login</button>
      </div>
      <pre id="loginOut"></pre>
    </div>
  </div>
    <script src="/app.js" defer></script>

</body>
</html>"""


APP_JS = r"""
    let currentMode = 'basic';
    let currentPage = 'dashboard';
    let currentRole = 'admin';
    let lastSuiteReport = null;

    function toast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg; t.style.display = 'block';
      setTimeout(() => t.style.display = 'none', 2600);
    }
    function toggleMenu(forceClose=false) {
      const menu = document.getElementById('menuTabs');
      const btn = document.getElementById('menuToggle');
      if (!menu || !btn) return;
      if (forceClose) {
        menu.classList.remove('open');
      } else {
        menu.classList.toggle('open');
      }
      btn.setAttribute('aria-expanded', menu.classList.contains('open') ? 'true' : 'false');
    }
    function closeMenuIfMobile() {
      if (window.innerWidth <= 760) toggleMenu(true);
    }
    function _modeAllowed(tagString, mode) {
      const tags = String(tagString || '').trim().split(/\s+/).filter(Boolean);
      if (!tags.length) return true;
      return tags.includes(mode);
    }
    function _roleRank(role) {
      return ({viewer:1, operator:2, admin:3}[String(role||'viewer')] || 1);
    }
    function _roleAllowed(tagString, role) {
      const tags = String(tagString || '').trim().split(/\s+/).filter(Boolean);
      if (!tags.length) return true;
      return tags.includes(role);
    }
    function applyRole(role) {
      currentRole = role || 'viewer';
      if (_roleRank(currentRole) < _roleRank('operator')) {
        const adv = document.getElementById('modeAdvanced');
        if (adv) adv.classList.add('tabHidden');
        setMode('basic');
      } else {
        const adv = document.getElementById('modeAdvanced');
        if (adv) adv.classList.remove('tabHidden');
      }
    }
    function setMode(mode, btnRef=null) {
      currentMode = (mode === 'advanced') ? 'advanced' : 'basic';
      try { localStorage.setItem('ui_mode', currentMode); } catch (_) {}
      const basicBtn = document.getElementById('modeBasic');
      const advBtn = document.getElementById('modeAdvanced');
      if (basicBtn) basicBtn.classList.toggle('active', currentMode === 'basic');
      if (advBtn) advBtn.classList.toggle('active', currentMode === 'advanced');

      document.querySelectorAll('#menuTabs button').forEach(b => {
        const modeOk = _modeAllowed(b.getAttribute('data-mode') || 'basic advanced', currentMode);
        const roleOk = _roleAllowed(b.getAttribute('data-role') || 'viewer operator admin', currentRole);
        const ok = modeOk && roleOk;
        b.classList.toggle('tabHidden', !ok);
      });
      const visibleActive = document.querySelector('#menuTabs button.active:not(.tabHidden)');
      if (!visibleActive) {
        const firstVisible = document.querySelector('#menuTabs button:not(.tabHidden)');
        if (firstVisible) {
          const page = (firstVisible.textContent || '').toLowerCase().trim().replace(/\s+/g, '');
          showPage(page === 'homeassistant' ? 'ha' : page, firstVisible);
          return;
        }
      }
      showPage(currentPage);
    }
    function showPage(page, btnRef=null) {
      currentPage = page;
      const cards = document.querySelectorAll('.grid .card');
      cards.forEach(c => { c.style.display = 'none'; });
      cards.forEach(c => {
        const p = (c.getAttribute('data-page') || '').trim();
        const tags = p ? p.split(/\s+/) : [];
        const modeOk = _modeAllowed(c.getAttribute('data-mode') || 'basic advanced', currentMode);
        const roleOk = _roleAllowed(c.getAttribute('data-role') || 'viewer operator admin', currentRole);
        const pageOk = (!p || tags.includes(page));
        c.style.display = (modeOk && roleOk && pageOk) ? '' : 'none';
      });
      document.querySelectorAll('#menuTabs button').forEach(b => b.classList.remove('active'));
      if (btnRef && !btnRef.classList.contains('tabHidden')) btnRef.classList.add('active');
      else {
        const btn = Array.from(document.querySelectorAll('#menuTabs button')).find(b =>
          !b.classList.contains('tabHidden') && (b.textContent || '').toLowerCase().includes(page)
        );
        if (btn) btn.classList.add('active');
      }
      closeMenuIfMobile();
      if (page === 'logs') refreshLogs();
      if (page === 'audit') refreshHistory();
      if (page === 'metrics') refreshMetrics();
    }
    function toastErr(msg) {
      const t = document.getElementById('toast');
      t.textContent = 'Error: ' + msg; t.style.display = 'block';
      t.style.color = '#ffbdbd';
      setTimeout(() => { t.style.display = 'none'; t.style.color = ''; }, 3200);
    }
    function firstLine(txt) {
      const s = String(txt || '').split('\n').map(x => x.trim()).find(Boolean);
      return s || '';
    }
    function summarizeResult(title, d) {
      const ok = Number(d && d.rc || 0) === 0;
      let line = `${title}: ${ok ? 'Success' : 'Failed'}`;
      if (title.toLowerCase().includes('status')) {
        const lineOut = firstLine(d && d.stdout);
        if (lineOut) line += `\nCurrent state: ${lineOut}`;
      } else {
        const lineOut = firstLine(d && d.stdout);
        const lineErr = firstLine(d && d.stderr);
        if (lineOut) line += `\n${lineOut}`;
        if (!ok && lineErr) line += `\nReason: ${lineErr}`;
      }
      return line + `\n\nRaw JSON:\n` + JSON.stringify(d || {}, null, 2);
    }
    async function api(path, opts={}) {
      const res = await fetch(path, Object.assign({headers:{'content-type':'application/json'}}, opts));
      const txt = await res.text();
      let data = {};
      try { data = JSON.parse(txt); } catch (e) { data = {raw: txt}; }
      if (res.status === 401) {
        document.getElementById('loginGate').style.display = 'flex';
      }
      if (!res.ok) {
        let msg = data.error || txt || ('HTTP ' + res.status);
        if (data.details) msg += ' | ' + JSON.stringify(data.details);
        throw new Error(msg);
      }
      return data;
    }
    async function requestApproval(action, note='') {
      const d = await api('/api/approvals/request', {
        method:'POST',
        body: JSON.stringify({action, note})
      });
      return d.approval_id;
    }
    async function withApproval(action, payload) {
      const note = prompt('Approval note for ' + action + ':', 'approved from UI');
      if (note === null) throw new Error('approval cancelled');
      const aid = await requestApproval(action, note);
      const out = Object.assign({}, payload || {});
      out.approval_id = aid;
      return out;
    }
    function applyQuickFields(cfg) {
      document.getElementById('whatsList').value = (cfg.whatsapp_to || []).join(', ');
      document.getElementById('quietStart').value = (cfg.quiet_hours_start == null) ? 23 : cfg.quiet_hours_start;
      document.getElementById('quietEnd').value = (cfg.quiet_hours_end == null) ? 6 : cfg.quiet_hours_end;
      document.getElementById('haUrl').value = cfg.ha_url || '';
      document.getElementById('haToken').value = cfg.ha_token || '';
      document.getElementById('homeModeEntity').value = cfg.ha_home_mode_entity || '';
      document.getElementById('knownFacesEntity').value = cfg.ha_known_faces_entity || '';
      document.getElementById('excludeKnownFaces').checked = !!cfg.exclude_known_faces;
      // Dynamic camera fields - render from config
      renderCameraFields(cfg);
      document.getElementById('alarmEntity').value = cfg.alarm_entity || '';
      document.getElementById('phase3').checked = !!cfg.phase3_enabled;
      document.getElementById('phase4').checked = !!cfg.phase4_enabled;
      document.getElementById('phase5').checked = !!cfg.phase5_enabled;
      document.getElementById('phase8').checked = !!cfg.phase8_enabled;
      if (document.getElementById('ocAnalysisWebhook')) {
        document.getElementById('ocAnalysisWebhook').value = cfg.openclaw_analysis_webhook || '';
        document.getElementById('ocDeliveryWebhook').value = cfg.openclaw_delivery_webhook || '';
        document.getElementById('ocTokenOpenclaw').value = cfg.openclaw_token || '';
        document.getElementById('ocAnalysisAgent').value = cfg.openclaw_analysis_agent_name || 'main';
        document.getElementById('ocDeliveryAgent').value = cfg.openclaw_delivery_agent_name || 'main';
        document.getElementById('ocWhatsList').value = (cfg.whatsapp_to || []).join(', ');
        document.getElementById('ocWhatsappEnabled').checked = !!cfg.whatsapp_enabled;
        if (document.getElementById("ocMinRiskLevel")) { document.getElementById("ocMinRiskLevel").value = cfg.whatsapp_min_risk_level || "medium"; }
      }
    }
    function patchCfgFromQuick(cfg) {
      cfg.whatsapp_to = document.getElementById('whatsList').value
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);
      cfg.quiet_hours_start = parseInt(document.getElementById('quietStart').value || '23', 10);
      cfg.quiet_hours_end = parseInt(document.getElementById('quietEnd').value || '6', 10);
      cfg.ha_url = document.getElementById('haUrl').value.trim();
      cfg.ha_token = document.getElementById('haToken').value.trim();
      cfg.ha_home_mode_entity = document.getElementById('homeModeEntity').value.trim();
      cfg.ha_known_faces_entity = document.getElementById('knownFacesEntity').value.trim();
      cfg.exclude_known_faces = !!document.getElementById('excludeKnownFaces').checked;
      // Read dynamic camera fields
      cfg.camera_context_notes = {};
      cfg.camera_zone_lights = {};
      document.querySelectorAll('[data-cam-ctx]').forEach(el => {
        cfg.camera_context_notes[el.dataset.camCtx] = el.value.trim();
      });
      document.querySelectorAll('[data-cam-light]').forEach(el => {
        const v = el.value.trim();
        cfg.camera_zone_lights[el.dataset.camLight] = v ? [v] : [];
      });
      cfg.alarm_entity = document.getElementById('alarmEntity').value.trim();
      cfg.phase3_enabled = document.getElementById('phase3').checked;
      cfg.phase4_enabled = document.getElementById('phase4').checked;
      cfg.phase5_enabled = document.getElementById('phase5').checked;
      cfg.phase8_enabled = document.getElementById('phase8').checked;
      return cfg;
    }
    function patchCfgFromOpenClaw(cfg) {
      cfg.openclaw_analysis_webhook = document.getElementById('ocAnalysisWebhook').value.trim();
      cfg.openclaw_delivery_webhook = document.getElementById('ocDeliveryWebhook').value.trim();
      cfg.openclaw_token = document.getElementById('ocTokenOpenclaw').value.trim();
      cfg.openclaw_analysis_agent_name = document.getElementById('ocAnalysisAgent').value.trim() || 'main';
      cfg.openclaw_delivery_agent_name = document.getElementById('ocDeliveryAgent').value.trim() || 'main';
      cfg.whatsapp_to = document.getElementById('ocWhatsList').value.split(',').map(s => s.trim()).filter(Boolean);
      cfg.whatsapp_enabled = !!document.getElementById('ocWhatsappEnabled').checked;
      cfg.whatsapp_min_risk_level = document.getElementById("ocMinRiskLevel") ? document.getElementById("ocMinRiskLevel").value : "medium";
      return cfg;
    }
    // ---- Dynamic camera fields ----
    let _cachedCameras = null;
    async function fetchFrigateCameras() {
      try {
        const cfg = (await api('/api/config/raw')).config || {};
        const frigateApi = cfg.frigate_api || 'http://localhost:5000';
        // Use our backend proxy to avoid CORS
        const d = await api('/api/frigate/cameras');
        return d.cameras || [];
      } catch (e) { return []; }
    }
    function renderCameraFields(cfg) {
      const container = document.getElementById('cameraFieldsContainer');
      if (!container) return;
      const ctx = cfg.camera_context_notes || {};
      const lights = cfg.camera_zone_lights || {};
      // Get camera names from config keys + any from Frigate
      const cameras = new Set([...Object.keys(ctx), ...Object.keys(lights)]);
      if (_cachedCameras) _cachedCameras.forEach(c => cameras.add(c));
      if (cameras.size === 0) {
        container.innerHTML = '<div class="sub" style="color:#999;">No cameras found. Click "Refresh Cameras from Frigate".</div>';
        return;
      }
      let html = '';
      for (const cam of [...cameras].sort()) {
        html += `<div class="row" style="margin-bottom:4px;">
          <div style="flex:2"><label>${cam} Context</label><input data-cam-ctx="${cam}" placeholder="Describe what ${cam} sees" value="${(ctx[cam]||'').replace(/"/g,'&quot;')}"/></div>
          <div style="flex:1"><label>${cam} Light</label><input data-cam-light="${cam}" placeholder="light.entity" value="${((lights[cam]||[])[0]||'').replace(/"/g,'&quot;')}"/></div>
        </div>`;
      }
      container.innerHTML = html;
    }
    async function refreshCameraFields() {
      try {
        const cameras = await fetchFrigateCameras();
        _cachedCameras = cameras;
        const d = await api('/api/config/raw');
        const cfg = d.config || {};
        // Add any new cameras from Frigate to context notes
        cameras.forEach(cam => {
          if (!cfg.camera_context_notes) cfg.camera_context_notes = {};
          if (!(cam in cfg.camera_context_notes)) cfg.camera_context_notes[cam] = '';
          if (!cfg.camera_zone_lights) cfg.camera_zone_lights = {};
          if (!(cam in cfg.camera_zone_lights)) cfg.camera_zone_lights[cam] = [];
        });
        renderCameraFields(cfg);
        toast('Cameras refreshed from Frigate.');
      } catch (e) {
        toastErr(e.message || e);
      }
    }

    async function refreshStatus() {
      try {
        const d = await api('/api/status');
        document.getElementById('statusBox').textContent = JSON.stringify(d, null, 2);
      } catch (e) {
        document.getElementById('statusBox').textContent = String(e);
        toastErr(e.message || e);
      }
    }
    async function reloadConfig() {
      try {
        const d = await api('/api/config/raw');
        document.getElementById('configBox').value = JSON.stringify(d.config, null, 2);
        applyQuickFields(d.config);
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function saveQuick() {
      try {
        const d = await api('/api/config/raw');
        const cfg = patchCfgFromQuick(d.config);
        await api('/api/config', {method:'PUT', body: JSON.stringify({config: cfg, restart: true})});
        await reloadConfig(); await refreshStatus();
        toast('Saved and applied.');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function saveConfig() {
      try {
        const cfg = JSON.parse(document.getElementById('configBox').value);
        const body = await withApproval('config_restart', {config: cfg, restart: true});
        await api('/api/config', {method:'PUT', body: JSON.stringify(body)});
        await reloadConfig(); await refreshStatus();
        toast('Full config saved and applied.');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function saveToggles() {
      try {
        const d = await api('/api/config/raw');
        const cfg = patchCfgFromQuick(d.config);
        await api('/api/config', {method:'PUT', body: JSON.stringify({config: cfg, restart: true})});
        await reloadConfig(); await refreshStatus();
        toast('Feature switches saved.');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function saveOpenClawSettings() {
      try {
        const d = await api('/api/config/raw');
        const cfg = patchCfgFromOpenClaw(d.config);
        await api('/api/config', {method:'PUT', body: JSON.stringify({config: cfg, restart: true})});
        await reloadConfig(); await refreshStatus();
        document.getElementById('openclawOut').textContent = 'Saved and applied OpenClaw settings.';
        toast('OpenClaw settings saved.');
      } catch (e) {
        document.getElementById('openclawOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function loadOpenClawConfig() {
      try {
        const d = await api('/api/openclaw/config');
        document.getElementById('openclawJsonBox').value = d.content || '';
        document.getElementById('openclawJsonOut').textContent = JSON.stringify({path: d.path, bytes: (d.content || '').length}, null, 2);
      } catch (e) {
        document.getElementById('openclawJsonOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function loadOpenClawChannelPolicy() {
      try {
        const d = await api('/api/openclaw/config');
        const obj = JSON.parse(d.content || '{}');
        const wa = (((obj || {}).channels || {}).whatsapp || {});
        document.getElementById('ocWaDmPolicy').value = wa.dmPolicy || '';
        document.getElementById('ocWaGroupPolicy').value = wa.groupPolicy || '';
        document.getElementById('ocWaAllowFrom').value = (wa.allowFrom || []).join(', ');
        document.getElementById('openclawJsonOut').textContent = 'Loaded WhatsApp channel policy from openclaw.json';
        toast('Channel policy loaded.');
      } catch (e) {
        document.getElementById('openclawJsonOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function saveOpenClawChannelPolicy() {
      try {
        const d = await api('/api/openclaw/config');
        const obj = JSON.parse(d.content || '{}');
        if (!obj.channels || typeof obj.channels !== 'object') obj.channels = {};
        if (!obj.channels.whatsapp || typeof obj.channels.whatsapp !== 'object') obj.channels.whatsapp = {};
        obj.channels.whatsapp.dmPolicy = document.getElementById('ocWaDmPolicy').value.trim();
        obj.channels.whatsapp.groupPolicy = document.getElementById('ocWaGroupPolicy').value.trim();
        obj.channels.whatsapp.allowFrom = document.getElementById('ocWaAllowFrom').value
          .split(',').map(s => s.trim()).filter(Boolean);
        const out = await api('/api/openclaw/config', {method:'PUT', body: JSON.stringify({content: JSON.stringify(obj, null, 2)})});
        document.getElementById('openclawJsonOut').textContent = JSON.stringify(out, null, 2);
        toast('Channel policy saved.');
        await loadOpenClawConfig();
      } catch (e) {
        document.getElementById('openclawJsonOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function saveOpenClawConfig() {
      try {
        const content = document.getElementById('openclawJsonBox').value;
        const d = await api('/api/openclaw/config', {method:'PUT', body: JSON.stringify({content: content})});
        document.getElementById('openclawJsonOut').textContent = JSON.stringify(d, null, 2);
        toast('openclaw.json saved.');
      } catch (e) {
        document.getElementById('openclawJsonOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function testOpenClawAnalysis() {
      try {
        const d = await api('/api/openclaw/test-analysis', {method:'POST', body:'{}'});
        document.getElementById('openclawOut').textContent = summarizeResult('OpenClaw analysis test', d);
        if (d.rc === 0) toast('OpenClaw analysis webhook reachable.');
        else toastErr('OpenClaw analysis webhook test failed.');
      } catch (e) {
        document.getElementById('openclawOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function openclawGatewayStatus() {
      try {
        const d = await api('/api/openclaw/gateway/status');
        document.getElementById('openclawOut').textContent = summarizeResult('Gateway status', d);
      } catch (e) {
        document.getElementById('openclawOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function openclawGatewayStart() {
      try {
        const d = await api('/api/openclaw/gateway/start', {method:'POST', body:'{}'});
        document.getElementById('openclawOut').textContent = summarizeResult('Gateway start', d);
        if (d.rc === 0) toast('OpenClaw gateway started.');
        else toastErr('OpenClaw gateway start failed.');
      } catch (e) {
        document.getElementById('openclawOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function openclawGatewayStop() {
      try {
        const d = await api('/api/openclaw/gateway/stop', {method:'POST', body:'{}'});
        document.getElementById('openclawOut').textContent = summarizeResult('Gateway stop', d);
        if (d.rc === 0) toast('OpenClaw gateway stopped.');
        else toastErr('OpenClaw gateway stop failed.');
      } catch (e) {
        document.getElementById('openclawOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function openclawGatewayRestart() {
      try {
        const d = await api('/api/openclaw/gateway/restart', {method:'POST', body:'{}'});
        document.getElementById('openclawOut').textContent = summarizeResult('Gateway restart', d);
        if (d.rc === 0) toast('OpenClaw gateway restarted.');
        else toastErr('OpenClaw gateway restart failed.');
      } catch (e) {
        document.getElementById('openclawOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function restartBridge() {
      try {
        await api('/api/runtime/restart', {method:'POST', body:'{}'});
        await refreshStatus();
        toast('Bridge restarted.');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function triggerSynthetic() {
      try {
        const payload = {
          event_id: document.getElementById('eventId').value,
          camera: document.getElementById('camera').value,
          label: document.getElementById('label').value
        };
        const d = await api('/api/test/synthetic-trigger', {method:'POST', body: JSON.stringify(payload)});
        document.getElementById('testOut').textContent = JSON.stringify(d, null, 2);
        toast('Synthetic event sent.');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function runSummary() {
      try {
        const payload = {
          period: document.getElementById('period').value.toLowerCase(),
          publish_mqtt: document.getElementById('pubMqtt').checked,
          deliver_whatsapp: document.getElementById('wa').checked
        };
        const d = await api('/api/summary/run', {method:'POST', body: JSON.stringify(payload)});
        document.getElementById('summaryOut').textContent = JSON.stringify(d, null, 2);
        renderSummaryResult(d, payload.period);
        await refreshReportsGraph();
        if (Number(d.rc || 0) === 0) toast('Summary completed.');
        else toastErr('Summary run failed. Check output.');
      } catch (e) {
        document.getElementById('summaryOut').textContent = String(e.message || e);
        renderSummaryResult({rc: 1, stderr: String(e.message || e)}, document.getElementById('period').value || 'daily');
        toastErr(e.message || e);
      }
    }
    function escHtml(v) {
      return String(v == null ? '' : v)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;');
    }
    function parseSummaryText(raw) {
      const lines = String(raw || '').split('\n').map(x => x.trim()).filter(Boolean);
      const out = {title: '', details: []};
      if (!lines.length) return out;
      out.title = lines[0];
      for (const ln of lines.slice(1)) {
        const i = ln.indexOf(':');
        if (i > 0) out.details.push({k: ln.slice(0, i).trim(), v: ln.slice(i + 1).trim()});
        else out.details.push({k: 'Note', v: ln});
      }
      return out;
    }
    function renderSummaryResult(result, period) {
      const status = document.getElementById('summaryStatus');
      const box = document.getElementById('summaryDetailGrid');
      const ok = Number(result && result.rc || 0) === 0;
      status.classList.remove('good', 'bad');
      status.classList.add(ok ? 'good' : 'bad');
      status.textContent = ok
        ? `Summary generated successfully (${String(period || 'daily')}).`
        : `Summary failed: ${String(result && (result.stderr || result.error || 'unknown error'))}`;
      const parsed = parseSummaryText(result && result.stdout || '');
      const items = [];
      if (parsed.title) items.push({k: 'Report', v: parsed.title});
      items.push(...parsed.details);
      if (!items.length && result && result.stderr) items.push({k: 'Error', v: String(result.stderr)});
      box.innerHTML = items.map(it => `<div class="summaryLine"><b>${escHtml(it.k)}:</b> ${escHtml(it.v)}</div>`).join('');
    }
    function renderChartRows(containerId, rows) {
      const root = document.getElementById(containerId);
      if (!root) return;
      const list = Array.isArray(rows) ? rows : [];
      if (!list.length) {
        root.innerHTML = '<div class="summaryLine">No data available.</div>';
        return;
      }
      const max = Math.max(1, ...list.map(x => Number(x.value || 0)));
      root.innerHTML = list.map(item => {
        const val = Number(item.value || 0);
        const pct = Math.max(0, Math.min(100, Math.round((val / max) * 100)));
        return (
          `<div class="chartRow">` +
            `<div class="chartLabel" title="${escHtml(item.label)}">${escHtml(item.label)}</div>` +
            `<div class="chartTrack"><div class="chartFill" style="width:${pct}%"></div></div>` +
            `<div class="chartValue">${val}</div>` +
          `</div>`
        );
      }).join('');
    }
    async function sendNotifyTest() {
      try {
        const d = await api('/api/notify/test', {method:'POST', body: JSON.stringify({message:'Drishtik control panel test message'})});
        document.getElementById('summaryOut').textContent = JSON.stringify(d, null, 2);
        if (d.rc === 0) toast('Test message sent.');
        else toastErr('Notify test failed');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function loadFrigateConfig() {
      try {
        const d = await api('/api/frigate/config');
        document.getElementById('frigateCfgBox').value = d.content || '';
        document.getElementById('frigateSaveOut').textContent = JSON.stringify({loaded: d.path, bytes: (d.content || '').length}, null, 2);
        toast('Frigate config loaded.');
      } catch (e) {
        document.getElementById('frigateSaveOut').textContent = 'Load failed: ' + (e.message || e);
        toastErr(e.message || e);
      }
    }
    async function saveFrigateConfig(withRestart) {
      try {
        const content = document.getElementById('frigateCfgBox').value;
        let payload = {content: content, restart: !!withRestart};
        if (withRestart) payload = await withApproval('frigate_config_restart', payload);
        const d = await api('/api/frigate/config', {method:'PUT', body: JSON.stringify(payload)});
        document.getElementById('frigateSaveOut').textContent = JSON.stringify(d, null, 2);
        if (withRestart && Number(d.restart_rc || 0) !== 0) {
          toastErr('Config saved but Frigate restart failed.');
        } else {
          toast(d.message || 'Frigate config saved.');
        }
      } catch (e) {
        document.getElementById('frigateSaveOut').textContent = 'Save failed: ' + (e.message || e);
        toastErr(e.message || e);
      }
    }
    async function validateFrigateConfig() {
      try {
        const content = document.getElementById('frigateCfgBox').value;
        const d = await api('/api/frigate/validate', {method:'POST', body: JSON.stringify({content: content})});
        document.getElementById('frigateSaveOut').textContent = JSON.stringify(d, null, 2);
        if (d.ok) toast('Frigate config looks valid.');
        else toastErr('Validation failed');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function restartFrigate() {
      try {
        const body = await withApproval('frigate_restart', {});
        const d = await api('/api/frigate/restart', {method:'POST', body: JSON.stringify(body)});
        document.getElementById('frigateSaveOut').textContent = JSON.stringify(d, null, 2);
        if (d.rc === 0) toast('Frigate restarted.');
        else toastErr('Frigate restart failed. Check output.');
      } catch (e) {
        document.getElementById('frigateSaveOut').textContent = 'Restart failed: ' + (e.message || e);
        toastErr(e.message || e);
      }
    }
    async function listFrigateBackups() {
      try {
        const d = await api('/api/frigate/backups');
        document.getElementById('frigateBackupOut').textContent = JSON.stringify(d, null, 2);
        toast('Backup list loaded.');
      } catch (e) {
        document.getElementById('frigateBackupOut').textContent = 'Backup list failed: ' + (e.message || e);
        toastErr(e.message || e);
      }
    }
    async function restoreFrigateBackup() {
      try {
        const backupPath = document.getElementById('backupPath').value.trim();
        const payload = await withApproval('frigate_restore', {backup_path: backupPath, restart: true});
        const d = await api('/api/frigate/restore', {method:'POST', body: JSON.stringify(payload)});
        document.getElementById('frigateBackupOut').textContent = JSON.stringify(d, null, 2);
        toast('Backup restored.');
      } catch (e) {
        document.getElementById('frigateBackupOut').textContent = 'Restore failed: ' + (e.message || e);
        toastErr(e.message || e);
      }
    }
    async function restoreLatestBackup() {
      try {
        const payload = await withApproval('frigate_restore_latest', {restart: true});
        const d = await api('/api/frigate/restore-latest', {method:'POST', body: JSON.stringify(payload)});
        document.getElementById('frigateBackupOut').textContent = JSON.stringify(d, null, 2);
        toast('Latest backup restored.');
      } catch (e) {
        document.getElementById('frigateBackupOut').textContent = 'Restore failed: ' + (e.message || e);
        toastErr(e.message || e);
      }
    }
    async function discoverHaEntities() {
      try {
        const modeRes = await api('/api/ha/entities?domain=input_select');
        const faceRes = await api('/api/ha/entities?domain=binary_sensor');
        const mode = (modeRes.entities || []).map(x => x.entity_id).filter(x => x.includes('home') || x.includes('mode'));
        const faces = (faceRes.entities || []).map(x => x.entity_id).filter(x => x.includes('face') || x.includes('person') || x.includes('known'));
        if (mode.length) document.getElementById('homeModeEntity').value = mode[0];
        if (faces.length) document.getElementById('knownFacesEntity').value = faces[0];
        document.getElementById('haDiscoverOut').textContent = JSON.stringify({
          picked_home_mode: mode[0] || null,
          picked_known_faces: faces[0] || null,
          top_home_mode_candidates: mode.slice(0,10),
          top_known_face_candidates: faces.slice(0,10)
        }, null, 2);
        toast('HA discovery completed.');
      } catch (e) {
        document.getElementById('haDiscoverOut').textContent = 'Discovery failed: ' + (e.message || e);
        toastErr(e.message || e);
      }
    }
    async function discoverHaControlEntities() {
      try {
        const lightsRes = await api('/api/ha/entities?domain=light');
        const switchRes = await api('/api/ha/entities?domain=switch');
        const lights = (lightsRes.entities || []).map(x => x.entity_id);
        const sw = (switchRes.entities || []).map(x => x.entity_id);
        const pick = (arr, words) => arr.find(e => words.some(w => e.includes(w))) || arr[0] || '';
        // HA entity discovery populates camera fields dynamically
        document.getElementById('topStairLightEntity').value = pick(lights, ['stair', 'top']);
        document.getElementById('terraceLightEntity').value = pick(lights, ['terrace', 'balcony']);
        document.getElementById('alarmEntity').value = pick(sw, ['siren', 'alarm', 'security']);
        document.getElementById('haDiscoverOut').textContent = JSON.stringify({
          picked: {
            garage: document.getElementById('garageLightEntity').value,
            topstair: document.getElementById('topStairLightEntity').value,
            terrace: document.getElementById('terraceLightEntity').value,
            alarm: document.getElementById('alarmEntity').value
          },
          light_candidates: lights.slice(0, 20),
          switch_candidates: sw.slice(0, 20)
        }, null, 2);
        toast('Control entities discovered.');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function testHaService() {
      try {
        const entity = document.getElementById('haTestEntity').value.trim();
        const selectedDomain = (document.getElementById('haTestDomain').value || 'auto').trim();
        const autoDomain = entity.includes('.') ? entity.split('.', 1)[0] : '';
        const resolvedDomain = (selectedDomain && selectedDomain !== 'auto') ? selectedDomain : autoDomain;
        const payload = {
          service: document.getElementById('haTestService').value.trim(),
          entity_id: entity
        };
        if (resolvedDomain) payload.domain = resolvedDomain;
        const d = await api('/api/ha/test-service', {method:'POST', body: JSON.stringify(payload)});
        document.getElementById('haTestOut').textContent = JSON.stringify(d, null, 2);
        if (d.rc === 0) toast('HA service test succeeded.');
        else toastErr('HA service test failed.');
      } catch (e) {
        document.getElementById('haTestOut').textContent = String(e);
        toastErr(e.message || e);
      }
    }
    async function refreshReportsGraph() {
      try {
        const d = await api('/api/reports/data?days=7');
        const daily = d.daily || [];
        const risk = d.risk_counts || {};
        const actions = d.action_counts || {};
        const totalEvents = Number(d.total_events || 0);
        const highCritical = Number(risk.high || 0) + Number(risk.critical || 0);
        const activeDays = daily.filter(x => Number(x.count || 0) > 0).length;
        const riskPct = totalEvents > 0 ? Math.round((highCritical / totalEvents) * 100) : 0;

        document.getElementById('kpiTotalEvents').textContent = String(totalEvents);
        document.getElementById('kpiHighCritical').textContent = String(highCritical);
        document.getElementById('kpiRiskRatio').textContent = `${riskPct}%`;
        document.getElementById('kpiActiveDays').textContent = String(activeDays);

        const dailyRows = daily.map(r => ({label: String(r.day || '').slice(5), value: Number(r.count || 0)}));
        const riskRows = ['low','medium','high','critical'].map(k => ({label: k, value: Number(risk[k] || 0)}));
        const actionRows = Object.entries(actions)
          .map(([k, v]) => ({label: k.replaceAll('_', ' '), value: Number(v || 0)}))
          .sort((a, b) => b.value - a.value)
          .slice(0, 8);

        renderChartRows('dailyChart', dailyRows);
        renderChartRows('riskChart', riskRows);
        renderChartRows('actionChart', actionRows);
        document.getElementById('reportsGraphOut').textContent = JSON.stringify(d, null, 2);
      } catch (e) {
        document.getElementById('reportsGraphOut').textContent = String(e);
        renderChartRows('dailyChart', []);
        renderChartRows('riskChart', []);
        renderChartRows('actionChart', []);
        toastErr(e.message || e);
      }
    }
    async function refreshMetrics() {
      try {
        const d = await api('/api/metrics/slo');
        document.getElementById('metricsOut').textContent = JSON.stringify(d, null, 2);
      } catch (e) {
        document.getElementById('metricsOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function runTestSuite() {
      try {
        const payload = {include_synthetic: !!document.getElementById('suiteSynthetic').checked};
        const d = await api('/api/tests/run-all', {method:'POST', body: JSON.stringify(payload)});
        lastSuiteReport = d;
        document.getElementById('testSuiteOut').textContent = JSON.stringify(d, null, 2);
        if (d.ok) toast('Test suite passed.');
        else toastErr('Test suite has failures.');
      } catch (e) {
        document.getElementById('testSuiteOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    function exportTestReport() {
      try {
        if (!lastSuiteReport) throw new Error('No test report to export.');
        const text = JSON.stringify(lastSuiteReport, null, 2);
        const blob = new Blob([text], {type:'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'frigate-test-report.json';
        document.body.appendChild(a);
        a.click();
        a.remove();
        toast('Report exported.');
      } catch (e) {
        toastErr(e.message || e);
      }
    }
    async function simulatePolicy() {
      try {
        const payload = {
          camera: document.getElementById('simCamera').value.trim(),
          risk: document.getElementById('simRisk').value,
          action: document.getElementById('simAction').value,
          known_faces_present: !!document.getElementById('simKnownFaces').checked,
          home_mode: document.getElementById('simHomeMode').value.trim()
        };
        const d = await api('/api/policy/simulate', {method:'POST', body: JSON.stringify(payload)});
        document.getElementById('simOut').textContent = JSON.stringify(d, null, 2);
      } catch (e) {
        document.getElementById('simOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function verifyAudit() {
      try {
        const d = await api('/api/audit/verify');
        document.getElementById('securityOut').textContent = JSON.stringify(d, null, 2);
        if (d.ok) toast('Audit chain verified.');
        else toastErr('Audit verification failed.');
      } catch (e) {
        document.getElementById('securityOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function refreshCluster() {
      try {
        const d = await api('/api/cluster/status');
        document.getElementById('securityOut').textContent = JSON.stringify(d, null, 2);
      } catch (e) {
        document.getElementById('securityOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function refreshSecretsStatus() {
      try {
        const d = await api('/api/secrets/status');
        document.getElementById('securityOut').textContent = JSON.stringify(d, null, 2);
      } catch (e) {
        document.getElementById('securityOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function listConfigVersions() {
      try {
        const d = await api('/api/config/versions?limit=30');
        document.getElementById('cfgVersionsOut').textContent = JSON.stringify(d, null, 2);
        const first = (d.versions || [])[0];
        if (first) document.getElementById('cfgVersionPath').value = first;
      } catch (e) {
        document.getElementById('cfgVersionsOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function diffSelectedConfigVersion() {
      try {
        const p = document.getElementById('cfgVersionPath').value.trim();
        const d = await api('/api/config/diff', {method:'POST', body: JSON.stringify({left_path: p, right: 'current'})});
        document.getElementById('cfgVersionsOut').textContent = JSON.stringify(d, null, 2);
      } catch (e) {
        document.getElementById('cfgVersionsOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function rollbackConfigVersion() {
      try {
        const p = document.getElementById('cfgVersionPath').value.trim();
        const payload = await withApproval('config_rollback', {version_path: p, restart: true});
        const d = await api('/api/config/rollback', {method:'POST', body: JSON.stringify(payload)});
        document.getElementById('cfgVersionsOut').textContent = JSON.stringify(d, null, 2);
        await reloadConfig(); await refreshStatus();
        toast('Config rollback applied.');
      } catch (e) {
        document.getElementById('cfgVersionsOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function refreshHealthBadges() {
      try {
        const d = await api('/api/health');
        const keys = ['bridge','control_panel','frigate','ha','openclaw','mqtt'];
        const html = keys.map(k => {
          const ok = !!d[k];
          return `<span class="badge ${ok ? 'ok':'bad'}">${k.toUpperCase()}: ${ok ? 'OK':'DOWN'}</span>`;
        }).join('');
        document.getElementById('healthBadges').innerHTML = html;
      } catch (e) {
        document.getElementById('healthBadges').innerHTML = `<span class="badge bad">HEALTH: ERROR</span>`;
      }
    }
    async function refreshLogs() {
      try {
        const lines = parseInt(document.getElementById('logLines').value || '120', 10);
        const service = encodeURIComponent(document.getElementById('logService').value || 'bridge');
        const d = await api('/api/logs?lines=' + lines + '&service=' + service);
        document.getElementById('logsOut').textContent = d.stdout || d.stderr || '';
      } catch (e) {
        document.getElementById('logsOut').textContent = String(e);
      }
    }
    async function refreshHistory() {
      try {
        const d = await api('/api/actions/history?limit=120');
        document.getElementById('historyOut').textContent = JSON.stringify(d, null, 2);
      } catch (e) {
        document.getElementById('historyOut').textContent = String(e);
      }
    }
    async function login() {
      try {
        const username = document.getElementById('loginUser').value.trim();
        const password = document.getElementById('loginPass').value;
        await api('/api/auth/login', {method:'POST', body: JSON.stringify({username, password})});
        document.getElementById('loginGate').style.display = 'none';
        document.getElementById('loginOut').textContent = '';
        toast('Logged in.');
        await bootstrap();
      } catch (e) {
        document.getElementById('loginOut').textContent = String(e.message || e);
        toastErr(e.message || e);
      }
    }
    async function logout() {
      try {
        await api('/api/auth/logout', {method:'POST', body:'{}'});
      } catch (_) {}
      document.getElementById('loginGate').style.display = 'flex';
      currentRole = 'viewer';
      toast('Logged out.');
    }
    async function bootstrap() {
      let savedMode = 'basic';
      try {
        savedMode = (localStorage.getItem('ui_mode') || 'basic').toLowerCase();
      } catch (e) {
        savedMode = 'basic';
      }
      setMode(savedMode === 'advanced' ? 'advanced' : 'basic');
      const firstBtn = document.querySelector('#menuTabs button:not(.tabHidden)');
      showPage('dashboard', firstBtn || null);

      try {
        const me = await api('/api/auth/me');
        if (!me.authenticated) {
          document.getElementById('loginGate').style.display = 'flex';
          return;
        }
        document.getElementById('loginGate').style.display = 'none';
        applyRole(me.role || 'viewer');
      } catch (e) {
        document.getElementById('loginGate').style.display = 'flex';
        return;
      }
      await reloadConfig();
      await refreshStatus();
      await refreshHealthBadges();
      await refreshLogs();
      await refreshHistory();
      await refreshReportsGraph();
      await refreshMetrics();
      loadOpenClawConfig();
      loadOpenClawChannelPolicy();
    }
    bootstrap();
    setInterval(() => { refreshHealthBadges(); refreshStatus(); }, 8000);
  """

APP_JS_COMPAT = r"""

// CSP-safe bridge for legacy inline onclick handlers.
(function bindLegacyOnclickHandlers() {
  function splitArgs(src) {
    const out = [];
    let cur = '';
    let q = '';
    for (let i = 0; i < src.length; i++) {
      const ch = src[i];
      if (q) {
        cur += ch;
        if (ch === q && src[i - 1] !== '\\\\') q = '';
        continue;
      }
      if (ch === '"' || ch === "'") {
        q = ch;
        cur += ch;
        continue;
      }
      if (ch === ',') {
        out.push(cur.trim());
        cur = '';
        continue;
      }
      cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }

  function parseArg(token, el) {
    const t = String(token || '').trim();
    if (!t) return undefined;
    if (t === 'this') return el;
    if (t === 'true') return true;
    if (t === 'false') return false;
    if (t === 'null') return null;
    if (t === 'undefined') return undefined;
    if (/^-?\\d+(?:\\.\\d+)?$/.test(t)) return Number(t);
    if ((t.startsWith("'") && t.endsWith("'")) || (t.startsWith('"') && t.endsWith('"'))) {
      return t.slice(1, -1).replace(/\\\\'/g, "'").replace(/\\\\\"/g, '"');
    }
    return t;
  }

  document.querySelectorAll('[onclick]').forEach((el) => {
    if (typeof el.onclick === 'function') return;
    const raw = el.getAttribute('onclick') || '';
    const m = raw.match(/^\\s*([A-Za-z_$][A-Za-z0-9_$]*)\\s*\\((.*)\\)\\s*;?\\s*$/);
    if (!m) return;
    const fnName = m[1];
    const argExpr = m[2] || '';
    el.addEventListener('click', (ev) => {
      ev.preventDefault();
      const fn = window[fnName];
      if (typeof fn !== 'function') return;
      const args = splitArgs(argExpr).map((a) => parseArg(a, el));
      fn.apply(window, args);
    });
  });
})();
"""


class Handler(BaseHTTPRequestHandler):
    def _cfg(self) -> dict:
        return load_config()

    def _session(self) -> dict | None:
        cfg = self._cfg()
        if not bool(cfg.get("ui_auth_enabled", False)):
            return {"username": "public", "role": "admin"}
        cookies = _parse_cookie(self.headers.get("Cookie"))
        sid = cookies.get("session_id")
        if not sid:
            return None
        sess = SESSIONS.get(sid)
        if not sess:
            return None
        if sess.get("expires_at", 0) < time.time():
            SESSIONS.pop(sid, None)
            return None
        return sess

    def _require_role(self, min_role: str) -> bool:
        sess = self._session()
        if not sess:
            self._json(401, {"error": "unauthorized"})
            return False
        if _role_rank(sess.get("role", "")) < _role_rank(min_role):
            self._json(403, {"error": "forbidden"})
            return False
        return True

    def _require_approval(self, data: dict, action: str) -> bool:
        cfg = self._cfg()
        if not bool(cfg.get("approval_required_high_impact", True)):
            return True
        aid = str(data.get("approval_id", "")).strip()
        if not aid:
            self._json(409, {"error": "approval required", "action": action})
            return False
        ok, err = validate_approval(aid, action)
        if not ok:
            self._json(409, {"error": f"approval invalid: {err}", "action": action})
            return False
        return True

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0:
            return {}
        raw = self.rfile.read(n).decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/app.js":
            body = (APP_JS + "\n" + APP_JS_COMPAT).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/auth/me":
            sess = self._session()
            if not sess:
                self._json(200, {"authenticated": False})
            else:
                self._json(200, {"authenticated": True, "username": sess.get("username"), "role": sess.get("role")})
            return
        if not self._require_role("viewer"):
            return
        if parsed.path == "/api/status":
            self._json(200, make_status())
            return
        if parsed.path == "/api/health":
            self._json(200, make_health())
            return
        if parsed.path == "/api/config":
            cfg = self._cfg()
            self._json(200, {"config": redacted_config(cfg), "config_path": str(CONFIG_PATH)})
            return
        if parsed.path == "/api/config/raw":
            if not self._require_role("admin"):
                return
            self._json(200, {"config": self._cfg(), "config_path": str(CONFIG_PATH)})
            return
        if parsed.path == "/api/config/versions":
            if not self._require_role("admin"):
                return
            qs = parse_qs(parsed.query)
            limit = int((qs.get("limit") or ["30"])[0])
            self._json(200, {"versions": list_config_versions(limit)})
            return
        if parsed.path == "/api/frigate/config":
            if not self._require_role("operator"):
                return
            if not FRIGATE_CONFIG_FILE.exists():
                self._json(404, {"error": f"missing file: {FRIGATE_CONFIG_FILE}"})
                return
            content = FRIGATE_CONFIG_FILE.read_text(encoding="utf-8")
            self._json(200, {"path": str(FRIGATE_CONFIG_FILE), "content": content})
            return
        if parsed.path == "/api/frigate/backups":
            self._json(200, {"backups": list_frigate_backups()})
            return
        if parsed.path == "/api/ha/entities":
            if not self._require_role("operator"):
                return
            qs = parse_qs(parsed.query)
            domain = (qs.get("domain") or [None])[0]
            ok, payload = fetch_ha_entities(domain)
            self._json(200 if ok else 502, payload)
            return
        if parsed.path == "/api/actions/history":
            self._json(200, {"items": read_actions(int((parse_qs(parsed.query).get("limit") or ["100"])[0]))})
            return
        if parsed.path == "/api/reports/data":
            qs = parse_qs(parsed.query)
            try:
                days = int((qs.get("days") or ["7"])[0])
            except Exception:
                days = 7
            self._json(200, reports_data(days))
            return
        if parsed.path == "/api/metrics/slo":
            self._json(200, slo_metrics())
            return
        if parsed.path == "/api/audit/verify":
            if not self._require_role("admin"):
                return
            self._json(200, verify_action_history())
            return
        if parsed.path == "/api/cluster/status":
            if not self._require_role("operator"):
                return
            self._json(200, cluster_status())
            return
        if parsed.path == "/api/openclaw/gateway/status":
            if not self._require_role("operator"):
                return
            rc, out, err = openclaw_gateway_cmd("status")
            self._json(200 if rc == 0 else 502, {"rc": rc, "stdout": out, "stderr": err})
            return
        if parsed.path == "/api/openclaw/config":
            if not self._require_role("admin"):
                return
            rc, out, err = load_openclaw_config_text()
            self._json(200 if rc == 0 else 502, {"rc": rc, "path": str(OPENCLAW_CONFIG_FILE), "content": out, "stderr": err})
            return
        if parsed.path == "/api/secrets/status":
            if not self._require_role("admin"):
                return
            sec = _read_secrets_env()
            self._json(200, {
                "path": str(SECRETS_ENV_PATH),
                "exists": SECRETS_ENV_PATH.exists(),
                "keys": sorted(sec.keys()),
            })
            return
        if parsed.path == "/api/logs":
            qs = parse_qs(parsed.query)
            lines = int((qs.get("lines") or ["120"])[0])
            svc = (qs.get("service") or ["bridge"])[0]
            unit = f"{BRIDGE_SERVICE}.service"
            if svc == "control":
                unit = "frigate-control-panel.service"
            rc, out, err = run_cmd([
                "journalctl", "--user", "-u", unit,
                "-n", str(max(10, min(lines, 1000))), "--no-pager",
            ])
            self._json(200, {"rc": rc, "stdout": out, "stderr": err})
            return
        self._json(404, {"error": "not found"})

    def do_PUT(self) -> None:
        if not self._require_role("operator"):
            return
        try:
            data = self._read_json()
        except Exception as exc:
            self._json(400, {"error": str(exc)})
            return

        if self.path == "/api/config":
            try:
                cfg_in = data.get("config", {})
                if not isinstance(cfg_in, dict):
                    raise ValueError("config must be an object")
                unknown = sorted(set(cfg_in.keys()) - ALLOWED_KEYS)
                if unknown:
                    raise ValueError(f"unknown keys: {', '.join(unknown)}")
                merged = dict(DEFAULT_CONFIG)
                merged.update(cfg_in)

                # Prevent accidentally persisting redacted placeholders as secrets.
                current = load_config()
                for k in ("mqtt_pass", "openclaw_token", "ha_token"):
                    incoming = merged.get(k)
                    if _looks_masked_secret(incoming):
                        cur = current.get(k, "")
                        if cur and not _looks_masked_secret(cur):
                            merged[k] = cur
                        elif k in ("mqtt_pass", "openclaw_token"):
                            merged[k] = DEFAULT_CONFIG[k]
                    elif str(incoming or "").strip() == "":
                        cur = current.get(k, "")
                        if cur:
                            merged[k] = cur
                actor = str((self._session() or {}).get("username", "system"))
                save_config_version(current, reason=str(data.get("reason", "pre-save snapshot")), actor=actor)
                save_config(merged)
                save_config_version(merged, reason=str(data.get("reason", "post-save snapshot")), actor=actor)
                if bool(data.get("restart", False)):
                    run_cmd(["systemctl", "--user", "restart", BRIDGE_SERVICE])
                append_action("config.save", True, {"restart": bool(data.get("restart", False))})
                self._json(200, {"message": "config saved", "config_path": str(CONFIG_PATH)})
            except Exception as exc:
                append_action("config.save", False, {"error": str(exc)})
                self._json(400, {"error": str(exc)})
            return

        if self.path == "/api/frigate/config":
            try:
                content = str(data.get("content", ""))
                valid, errs = validate_frigate_config_text(content)
                if not valid:
                    self._json(400, {"error": "validation failed", "details": errs})
                    return
                if bool(data.get("restart", False)):
                    if not self._require_approval(data, "frigate_config_restart"):
                        return
                FRIGATE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                if FRIGATE_CONFIG_FILE.exists():
                    stamp = int(time.time())
                    backup = FRIGATE_CONFIG_FILE.with_suffix(f".yml.bak.{stamp}")
                    backup.write_text(FRIGATE_CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
                FRIGATE_CONFIG_FILE.write_text(content, encoding="utf-8")
                rc = out = err = ""
                if bool(data.get("restart", False)):
                    rc, out, err = restart_frigate()
                append_action("frigate.config.save", True, {"restart": bool(data.get("restart", False)), "restart_rc": rc})
                if bool(data.get("restart", False)) and int(rc or 0) != 0:
                    self._json(500, {
                        "error": "frigate config saved but restart failed",
                        "path": str(FRIGATE_CONFIG_FILE),
                        "restart_rc": rc,
                        "restart_stdout": out,
                        "restart_stderr": err,
                    })
                    return
                self._json(200, {
                    "message": "frigate config saved",
                    "path": str(FRIGATE_CONFIG_FILE),
                    "restart_rc": rc,
                    "restart_stdout": out,
                    "restart_stderr": err,
                })
            except Exception as exc:
                append_action("frigate.config.save", False, {"error": str(exc)})
                self._json(500, {"error": str(exc)})
            return
        if self.path == "/api/openclaw/config":
            if not self._require_role("admin"):
                return
            content = str(data.get("content", ""))
            rc, out, err = save_openclaw_config_text(content)
            append_action("openclaw.config.save", rc == 0, {"rc": rc})
            self._json(200 if rc == 0 else 502, {"rc": rc, "stdout": out, "stderr": err, "path": str(OPENCLAW_CONFIG_FILE)})
            return

        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            data = self._read_json()
        except Exception as exc:
            self._json(400, {"error": str(exc)})
            return

        if self.path == "/api/auth/login":
            cfg = self._cfg()
            users = cfg.get("ui_users", {})
            username = str(data.get("username", "")).strip()
            password = str(data.get("password", ""))
            user = users.get(username) if isinstance(users, dict) else None
            if not user or str(user.get("password", "")) != password:
                self._json(401, {"error": "invalid credentials"})
                return
            sid = secrets.token_urlsafe(24)
            sess = {"username": username, "role": str(user.get("role", "viewer")), "expires_at": time.time() + SESSION_TTL_SECONDS}
            SESSIONS[sid] = sess
            body = json.dumps({"ok": True, "role": sess["role"], "username": username}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"session_id={sid}; HttpOnly; Path=/; Max-Age={SESSION_TTL_SECONDS}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            append_action("auth.login", True, {"username": username, "role": sess["role"]})
            return

        if self.path == "/api/auth/logout":
            cookies = _parse_cookie(self.headers.get("Cookie"))
            sid = cookies.get("session_id")
            if sid:
                SESSIONS.pop(sid, None)
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "session_id=; HttpOnly; Path=/; Max-Age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            append_action("auth.logout", True, {})
            return

        if self.path == "/api/approvals/request":
            if not self._require_role("admin"):
                return
            action = str(data.get("action", "")).strip()
            if not action:
                self._json(400, {"error": "action is required"})
                return
            note = str(data.get("note", "")).strip()
            who = str((self._session() or {}).get("username", "unknown"))
            row = request_approval(action, note, who)
            append_action("approval.request", True, {"action": action, "approval_id": row["approval_id"]})
            self._json(200, row)
            return

        if not self._require_role("operator"):
            return

        if self.path == "/api/config/diff":
            if not self._require_role("admin"):
                return
            left_path = str(data.get("left_path", "")).strip()
            right = str(data.get("right", "current")).strip()
            if not left_path:
                self._json(400, {"error": "left_path is required"})
                return
            try:
                left_cfg = load_config_version(left_path)
                if right == "current":
                    right_cfg = self._cfg()
                else:
                    right_cfg = load_config_version(right)
                self._json(200, diff_config_dicts(left_cfg, right_cfg))
            except Exception as exc:
                self._json(400, {"error": str(exc)})
            return

        if self.path == "/api/config/rollback":
            if not self._require_role("admin"):
                return
            if not self._require_approval(data, "config_rollback"):
                return
            version_path = str(data.get("version_path", "")).strip()
            if not version_path:
                self._json(400, {"error": "version_path is required"})
                return
            try:
                old = self._cfg()
                cfg = load_config_version(version_path)
                save_config_version(old, reason="pre-rollback snapshot", actor=str((self._session() or {}).get("username", "system")))
                save_config(cfg)
                save_config_version(cfg, reason="post-rollback snapshot", actor=str((self._session() or {}).get("username", "system")))
                if bool(data.get("restart", True)):
                    run_cmd(["systemctl", "--user", "restart", BRIDGE_SERVICE])
                append_action("config.rollback", True, {"version_path": version_path})
                self._json(200, {"message": "rollback applied", "version_path": version_path})
            except Exception as exc:
                append_action("config.rollback", False, {"error": str(exc)})
                self._json(400, {"error": str(exc)})
            return

        if self.path == "/api/runtime/restart":
            rc, out, err = run_cmd(["systemctl", "--user", "restart", BRIDGE_SERVICE])
            append_action("bridge.restart", rc == 0, {"rc": rc})
            self._json(200, {"rc": rc, "stdout": out, "stderr": err})
            return
        if self.path == "/api/frigate/restart":
            if not self._require_role("admin"):
                return
            if not self._require_approval(data, "frigate_restart"):
                return
            rc, out, err = restart_frigate()
            append_action("frigate.restart", rc == 0, {"rc": rc})
            self._json(200, {"rc": rc, "stdout": out, "stderr": err})
            return
        if self.path == "/api/frigate/validate":
            content = str(data.get("content", ""))
            ok, errs = validate_frigate_config_text(content)
            self._json(200, {"ok": ok, "errors": errs})
            return
        if self.path == "/api/frigate/restore-latest":
            if not self._require_role("admin"):
                return
            if not self._require_approval(data, "frigate_restore_latest"):
                return
            backups = list_frigate_backups()
            if not backups:
                self._json(404, {"error": "no backups found"})
                return
            data = {"backup_path": backups[0], "restart": bool(data.get("restart", True)), "_approval_checked": True}
            # fallthrough to restore logic
            self.path = "/api/frigate/restore"
        if self.path == "/api/frigate/restore":
            if not self._require_role("admin"):
                return
            if not bool(data.get("_approval_checked", False)):
                if not self._require_approval(data, "frigate_restore"):
                    return
            backup_path = str(data.get("backup_path", "")).strip()
            if not backup_path:
                self._json(400, {"error": "backup_path is required"})
                return
            src = Path(backup_path)
            if not src.exists():
                self._json(404, {"error": f"backup not found: {src}"})
                return
            if src.parent != FRIGATE_CONFIG_FILE.parent:
                self._json(400, {"error": "backup must be in config directory"})
                return
            try:
                content = src.read_text(encoding="utf-8")
                valid, errs = validate_frigate_config_text(content)
                if not valid:
                    self._json(400, {"error": "backup validation failed", "details": errs})
                    return
                FRIGATE_CONFIG_FILE.write_text(content, encoding="utf-8")
                rc = out = err = ""
                if bool(data.get("restart", True)):
                    rc, out, err = restart_frigate()
                append_action("frigate.restore", True, {"backup_path": backup_path, "restart_rc": rc})
                self._json(200, {"message": "backup restored", "restart_rc": rc, "restart_stdout": out, "restart_stderr": err})
            except Exception as exc:
                append_action("frigate.restore", False, {"error": str(exc)})
                self._json(500, {"error": str(exc)})
            return

        if self.path == "/api/test/synthetic-trigger":
            event_id = str(data.get("event_id", "1771006387.217811-5r946l"))
            camera = str(data.get("camera", "TopStairCam"))
            label = str(data.get("label", "person"))
            rc, out, err = run_synthetic_trigger(event_id, camera, label)
            append_action("test.synthetic_trigger", rc == 0, {"event_id": event_id, "camera": camera, "rc": rc})
            self._json(200, {"rc": rc, "stdout": out, "stderr": err, "event_id": event_id, "camera": camera})
            return

        if self.path == "/api/notify/test":
            if not self._require_role("admin"):
                return
            msg = str(data.get("message", "Drishtik test message"))
            rc, out, err = send_test_whatsapp(msg)
            append_action("notify.test", rc == 0, {"rc": rc})
            self._json(200, {"rc": rc, "stdout": out, "stderr": err})
            return
        if self.path == "/api/openclaw/test-analysis":
            rc, out, err = test_openclaw_analysis()
            append_action("openclaw.test_analysis", rc == 0, {"rc": rc})
            self._json(200 if rc == 0 else 502, {"rc": rc, "stdout": out, "stderr": err})
            return
        if self.path == "/api/openclaw/gateway/start":
            if not self._require_role("admin"):
                return
            rc, out, err = openclaw_gateway_cmd("start")
            append_action("openclaw.gateway.start", rc == 0, {"rc": rc})
            self._json(200 if rc == 0 else 502, {"rc": rc, "stdout": out, "stderr": err})
            return
        if self.path == "/api/openclaw/gateway/stop":
            if not self._require_role("admin"):
                return
            rc, out, err = openclaw_gateway_cmd("stop")
            append_action("openclaw.gateway.stop", rc == 0, {"rc": rc})
            self._json(200 if rc == 0 else 502, {"rc": rc, "stdout": out, "stderr": err})
            return
        if self.path == "/api/openclaw/gateway/restart":
            if not self._require_role("admin"):
                return
            rc, out, err = openclaw_gateway_cmd("restart")
            append_action("openclaw.gateway.restart", rc == 0, {"rc": rc})
            self._json(200 if rc == 0 else 502, {"rc": rc, "stdout": out, "stderr": err})
            return
        if self.path == "/api/tests/run-all":
            include_synthetic = bool(data.get("include_synthetic", False))
            report = run_test_suite(include_synthetic=include_synthetic)
            append_action("tests.run_all", bool(report.get("ok", False)), {"total": report.get("total"), "failed": report.get("failed")})
            self._json(200 if bool(report.get("ok", False)) else 502, report)
            return
        if self.path == "/api/policy/simulate":
            payload = simulate_policy(
                camera=str(data.get("camera", "TopStairCam")),
                risk=str(data.get("risk", "low")),
                action=str(data.get("action", "notify_only")),
                known_faces_present=bool(data.get("known_faces_present", False)),
                home_mode=str(data.get("home_mode", "home")),
            )
            self._json(200, payload)
            return
        if self.path == "/api/ha/test-service":
            entity_id = str(data.get("entity_id", "")).strip()
            service = str(data.get("service", "toggle")).strip()
            requested_domain = str(data.get("domain", "")).strip()
            if "." not in entity_id:
                self._json(400, {"error": "entity_id must look like domain.object_id"})
                return
            entity_domain = entity_id.split(".", 1)[0]
            domain = entity_domain
            warning = ""
            if requested_domain and requested_domain != entity_domain:
                warning = f"domain mismatch: entity is {entity_domain}, payload asked for {requested_domain}; using {entity_domain}"
            payload = {"entity_id": entity_id}
            # `transition` is valid for lights, but causes 400 for switch.* services.
            if domain == "light" and service in ("turn_on", "turn_off"):
                payload["transition"] = 1
            rc, out, err = call_ha_service(domain, service, payload)
            ok = int(rc) == 0
            append_action("ha.test_service", ok, {"entity_id": entity_id, "service": service, "rc": rc})
            self._json(200 if ok else 502, {
                "rc": rc,
                "stdout": out,
                "stderr": err,
                "resolved_domain": domain,
                "warning": warning,
            })
            return

        if self.path == "/api/summary/run":
            period = str(data.get("period", "daily"))
            if period not in ("daily", "weekly"):
                self._json(400, {"error": "period must be daily or weekly"})
                return
            rc, out, err = run_summary(
                period=period,
                publish_mqtt=bool(data.get("publish_mqtt", False)),
                deliver_whatsapp=bool(data.get("deliver_whatsapp", False)),
            )
            ok = (rc == 0)
            append_action("summary.run", ok, {"period": period, "publish_mqtt": bool(data.get("publish_mqtt", False)), "deliver_whatsapp": bool(data.get("deliver_whatsapp", False)), "rc": rc})
            self._json(200 if ok else 502, {"rc": rc, "stdout": out, "stderr": err})
            return

        self._json(404, {"error": "not found"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Drishtik control panel")
    parser.add_argument("--host", default=APP_HOST)
    parser.add_argument("--port", type=int, default=APP_PORT)
    args = parser.parse_args()
    save_config(load_config())
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Drishtik control panel listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
