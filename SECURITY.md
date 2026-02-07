# Security Policy

## What Is Intentionally Excluded

This repository is designed to be safe for public sharing. The following items are **intentionally excluded** and must never be committed:

- `~/.openclaw/openclaw.json` (real tokens and gateway secrets)
- `~/.openclaw/auth-profiles.json`
- `~/.openclaw/agents/**/sessions/**` (session transcripts and media)
- Any API keys (OpenAI, Anthropic, Telegram, Slack, Discord, etc.)
- WhatsApp phone numbers and allowlists
- MQTT credentials and broker passwords
- Private IPs or internal hostnames
- TLS certificates and keys
- Any `.env` files or secrets files

## Safe Templates

Use these safe templates instead:

- `config/openclaw.json.example`
- `config/frigate-config.yml` (redacted)

## Report a Vulnerability

If you believe sensitive data was committed by mistake, remove it immediately and rotate any exposed keys. Then update `SECURITY.md` if new exclusions are needed.
