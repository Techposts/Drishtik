# OpenClaw Configuration (Gateway + Messaging)

This document explains where OpenClaw is configured and how WhatsApp and other messaging channels are wired.
All values here are **placeholders** — do not commit real tokens.

---

## 1. Core OpenClaw Config File

**Path:**
```
~/.openclaw/openclaw.json
```

Key sections you typically edit:

- `hooks` — enable webhooks (bridge → OpenClaw)
- `gateway` — port and bind settings
- `channels` — messaging providers (WhatsApp, Telegram, etc.)

---

## 2. Webhook (Bridge → OpenClaw)

OpenClaw webhooks must be enabled for the bridge to call `/hooks/agent`.

Example:
```json
"hooks": {
  "enabled": true,
  "token": "<HOOK_TOKEN>",
  "path": "/hooks"
}
```

**Used by bridge:**
```
http://<OPENCLAW_HOST>:18789/hooks/agent
```

---

## 3. Gateway Settings

```json
"gateway": {
  "port": 18789
}
```

Gateway health:
```bash
systemctl --user status openclaw-gateway.service
```

---

## 4. Messaging: WhatsApp (Primary)

OpenClaw uses an allowlist for DM safety.

```json
"channels": {
  "whatsapp": {
    "dmPolicy": "allowlist",
    "allowFrom": [
      "+1234567890"
    ]
  }
}
```

### WhatsApp Login
```bash
openclaw channels login --channel whatsapp --verbose
```

---

## 5. Messaging: Telegram (Optional)

```bash
openclaw channels add --channel telegram --token <BOT_TOKEN>
```

---

## 6. Messaging: Discord (Optional)

```bash
openclaw channels add --channel discord --token <DISCORD_BOT_TOKEN>
```

---

## 7. Messaging: Slack (Optional)

```bash
openclaw channels add --channel slack --bot-token <SLACK_BOT_TOKEN> --app-token <SLACK_APP_TOKEN>
```

---

## 8. Where the Bridge Reads/Writes

Bridge config file:
```
/home/<HOME_USER>/frigate/frigate-openclaw-bridge.py
```

Important fields:
- `OPENCLAW_WEBHOOK`
- `OPENCLAW_TOKEN`
- `WHATSAPP_TO`

---

## 9. Safe Example Config

Use this repo template (safe):

```
config/openclaw.json.example
```

---

## 10. Security Notes

- Never commit real tokens or phone numbers.
- Keep `~/.openclaw/auth-profiles.json` private.
- Use `SECURITY.md` in this repo as the exclusion reference.

