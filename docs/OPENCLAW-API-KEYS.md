# OpenClaw API Keys — Step By Step

This guide walks through creating API keys and wiring them into OpenClaw.
It uses **OpenAI GPT-4o-mini** for vision, with **Anthropic** as an optional provider.

---

## OpenAI (Recommended)

### Step 1 — Create an OpenAI API key

1. Open the OpenAI Help article (it links to the API Keys page):

```
https://help.openai.com/en/articles/4936850-where-do-i-find-my-secret-api-key_
```

2. Click **API Keys**.
3. Click **Create new secret key**.
4. Copy the key (it is shown once).

### Step 2 — Paste the key into OpenClaw

```bash
openclaw models auth paste-token --provider openai
```

Paste the key when prompted.

### Step 3 — Set the model

```bash
openclaw models set openai/gpt-4o-mini
```

Reference:

```
https://platform.openai.com/docs/models/gpt-4o-mini
```

---

## Anthropic (Optional)

### Step 1 — Create an Anthropic API key

1. Create/Sign in to the Anthropic Console:

```
https://support.anthropic.com/en/articles/8114521-how-can-i-access-the-anthropic-api
```

2. Go to the API keys section in the Console.
3. Create a new key and copy it.

Reference:

```
https://docs.anthropic.com/en/api/admin-api/apikeys/get-api-key
```

### Step 2 — Paste the key into OpenClaw

```bash
openclaw models auth paste-token --provider anthropic
```

### Step 3 — Suggested Anthropic models

```bash
openclaw models set anthropic/claude-3-5-haiku-latest
openclaw models set anthropic/claude-sonnet-4-20250514
```

---

## OpenClaw Model/Auth Docs

Useful references:

```
https://docs.openclaw.ai/models
https://docs.openclaw.ai/gateway/authentication
```

