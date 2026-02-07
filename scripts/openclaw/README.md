# OpenClaw Setup & Reference Guide

## Installation

OpenClaw was installed globally via npm with a local prefix (no root required):

```bash
mkdir -p ~/.npm-global
npm config set prefix '~/.npm-global'
npm install -g openclaw@latest
```

**PATH** (added to `~/.bashrc`):
```bash
export PATH="$HOME/.npm-global/bin:$PATH"
```

Reload your shell or run `source ~/.bashrc` after changes.

## Version

```
OpenClaw 2026.1.30
```

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.openclaw/openclaw.json` | Main config (gateway, model, agents) |
| `~/.openclaw/auth-profiles.json` | API key storage (permissions: 600) |
| `~/.openclaw/workspace/` | Agent workspace directory |
| `~/.openclaw/agents/main/sessions/` | Conversation sessions |
| `~/.openclaw/credentials/` | OAuth credentials directory |
| `~/.openclaw/identity/device.json` | Device identity |

## LLM Model Configuration

**Recommended model for this pipeline:** `openai/gpt-4o-mini` (vision capable)

### Change the default model

```bash
# Recommended for vision
openclaw models set openai/gpt-4o-mini

# Balanced cost/quality
openclaw models set anthropic/claude-sonnet-4-20250514

# Most capable (expensive)
openclaw models set anthropic/claude-opus-4-5
```

### List configured models

```bash
openclaw models list
openclaw models status
```

### Update API key

```bash
# OpenAI (recommended)
openclaw models auth paste-token --provider openai

# Anthropic (optional)
openclaw models auth paste-token --provider anthropic
```

Then paste your `sk-ant-...` key when prompted.

## Gateway

### Start the gateway

```bash
# Foreground (verbose), bound to LAN (accessible from 192.168.1.10)
openclaw gateway --port 18789 --bind lan --verbose

# With auto-restart on crash
openclaw gateway --port 18789 --bind lan --verbose --force
```

**Bind modes:** `loopback` (localhost only), `lan` (local network), `tailnet`, `auto`, `custom`

The gateway runs on `ws://192.168.1.10:18789` (LAN accessible).

Canvas UI available at: `http://192.168.1.10:18789/__openclaw__/canvas/`

### Install as a systemd service (auto-start on boot)

```bash
openclaw onboard --install-daemon
```

### Check gateway health

```bash
openclaw health
openclaw status
```

## Sending Messages

```bash
# Test the agent locally (no channel needed)
openclaw agent --local --session-id test --message "Hello, are you working?"

# Continue an existing session
openclaw agent --local --session-id test --message "What did I ask before?"

# Send to a specific contact (requires channel setup)
openclaw message send --target +1234567890 --message "Hello"

# Send via Telegram
openclaw message send --channel telegram --target @mychat --message "Hi"
```

**Note:** Without `--local` and `--session-id`, the agent tries to route through a
messaging channel (WhatsApp, Telegram, etc.) which requires channel setup first.

## Channels

Connect messaging platforms:

```bash
# Interactive channel login
openclaw channels login --verbose

# Supported channels: WhatsApp, Telegram, Slack, Discord,
# Google Chat, Signal, iMessage, Microsoft Teams, WebChat,
# Matrix, and more.
```

## Skills

```bash
# List available skills
openclaw skills

# Install a skill
openclaw skills install <skill-name>
```

## Diagnostics

```bash
# Full health check
openclaw doctor

# Auto-fix issues
openclaw doctor --fix

# Security audit
openclaw security audit --deep

# View logs
openclaw logs
```

## Common Operations

```bash
# Open the web dashboard
openclaw dashboard

# List conversation sessions
openclaw sessions

# Reset config (keeps CLI installed)
openclaw reset

# Update CLI
openclaw update

# Uninstall
openclaw uninstall
```

## Budget Notes

With Claude Haiku 3.5 pricing (~$0.80/1M input, $4/1M output tokens), a $3-5 budget provides substantial usage for a personal assistant. Monitor your usage at https://console.anthropic.com/settings/billing.

## Useful Links

- GitHub: https://github.com/openclaw/openclaw
- Docs: https://docs.openclaw.ai
- CLI Docs: https://docs.openclaw.ai/cli
- Security: https://docs.openclaw.ai/security
- Anthropic Console: https://console.anthropic.com
