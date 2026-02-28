# OpenMiniCrew — Personal AI Assistant Framework

> 🇹🇭 [อ่านเป็นภาษาไทย](../../README.md)

A personal AI assistant you control through Telegram. Supports Claude + Gemini, with a plug-and-play tool system.

## Features

- Control via Telegram — both `/commands` and free-text messages
- Choose your LLM (Claude / Gemini / easily add more) switchable anytime
- Add new tools by creating a single file — no core changes needed
- Add new LLM providers by creating a file in `core/providers/` (Provider Registry)
- Telegram Bot supports both long polling and webhook modes
- Chat memory — maintains conversation context
- Automated morning email briefing via cron
- Smart email summaries — grouped by category, prioritized by importance, searchable
- Multi-tenant ready — built to scale to multiple users without refactoring
- Production ready — retry, error handling, rate limiting, health checks

## Installation

```bash
# 1. Clone the project
cd openminicrew

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy environment file
cp .env.example .env
# Edit .env following the steps below
```

## Configuration

### 1. Create a Telegram Bot

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and set a name
3. Get the Bot Token → put it in `TELEGRAM_BOT_TOKEN`
4. Talk to [@userinfobot](https://t.me/userinfobot) to get your Chat ID
5. Put your Chat ID in `OWNER_TELEGRAM_CHAT_ID`

### 2. Set Up LLM

**Claude:**
1. Get an API key at [console.anthropic.com](https://console.anthropic.com)
2. Put it in `ANTHROPIC_API_KEY`

**Gemini:**
1. Get an API key at [aistudio.google.com](https://aistudio.google.com)
2. Put it in `GEMINI_API_KEY`

> **Note:** Set `DEFAULT_LLM` in `.env` to `claude` or `gemini` depending on which API key you have.

### 3. Set Up Gmail (for email summary tool)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new Project (or use an existing one)
3. Enable the Gmail API
4. Create an OAuth 2.0 Client ID (select **Desktop App** type)
5. Download `credentials.json` and place it at the project root

> **Important:** Make sure you download `credentials.json` from the correct project — the project name set in Google Cloud Console will be displayed on the consent screen during authorization.

### 4. Run

```bash
# Normal run — auto-detects Gmail auth
# If not yet authorized, will open browser automatically
python main.py

# Or authorize Gmail separately
python main.py --auth-gmail
python main.py
```

```bash
# Mode A: Long Polling (for development / home machine)
BOT_MODE=polling python main.py

# Mode B: Webhook (for VPS / production)
BOT_MODE=webhook python main.py
```

### Startup Flow

```
python main.py
  │
  ├── [1/6] Init database (SQLite + WAL)
  ├── [2/6] Init owner user
  ├── [3/6] Gmail auth check
  │         ├── Token exists → OK
  │         └── No token → Opens browser for authorization
  ├── [4/6] Discover tools
  ├── [5/6] Start scheduler
  └── [6/6] Start bot (polling / webhook)
```

## Usage

### Basic Commands

| Command | Description |
|---|---|
| `/email` | Summarize unread emails (today) |
| `/model` | Show available LLM providers |
| `/model claude` | Switch to Claude |
| `/model gemini` | Switch to Gemini |
| `/help` | Show all commands |
| Free text | AI will choose a tool or respond directly |

### Email Summary — Advanced Options

| Command | Description |
|---|---|
| `/email` | Summarize today's emails (default) |
| `/email today` | Same as `/email` |
| `/email 3d` | Summarize emails from last 3 days |
| `/email 7d` | Summarize emails from last 7 days |
| `/email 30d` | Summarize emails from last 30 days |
| `/email force` | Re-summarize all (even previously processed) |
| `/email credit card` | Search for specific topic |
| `/email from:ktc.co.th` | Search by sender |
| `/email from:grab.com 7d` | Emails from Grab, last 7 days |
| `/email force credit card 7d` | Combine all options |

**Summary Format:**
- 📋 Overview — Quick summary of all emails
- 🔴 Action Required — Emails that need your attention (verify transactions, reply, etc.)
- Grouped by Category — 💰 Finance, 💼 Work, 📊 Investment, 🛒 Promotions, etc.
- 🎯 Priority Summary — What to focus on first

## Adding New Tools

Create a file in `tools/` — the registry will auto-discover it:

```python
# tools/my_tool.py

from tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Describe what this tool does"
    commands = ["/mytool"]

    async def execute(self, user_id: str, args: str = "") -> str:
        # Main logic
        return "Result"

    def get_tool_spec(self) -> dict:
        return {
            "name": "my_tool",
            "description": "Describe what this tool does",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }
```

That's it — works with both `/mytool` command and free-text messages.

> 📖 See [TOOLS_GUIDE.md](TOOLS_GUIDE.md) for detailed examples including Weather, Google Maps Traffic, and News Summary tools.

## Project Structure

```
openminicrew/
├── core/              Shared modules
│   ├── config.py      Load .env + validation
│   ├── llm.py         LLM Router (thin wrapper)
│   ├── providers/     LLM Provider Registry
│   │   ├── base.py    BaseLLMProvider abstract class
│   │   ├── claude_provider.py
│   │   ├── gemini_provider.py
│   │   └── registry.py   Auto-discover providers
│   ├── db.py          SQLite + WAL mode
│   ├── memory.py      Chat context
│   ├── security.py    Token management + Gmail OAuth
│   ├── user_manager.py  User auth
│   └── logger.py      Logging
├── tools/             Tool system
│   ├── base.py        BaseTool abstract class
│   ├── registry.py    Auto-discover
│   └── email_summary.py  Email summary (time range + search + force)
├── interfaces/        Telegram interface
│   ├── telegram_polling.py   Long polling
│   ├── telegram_webhook.py   Webhook + FastAPI
│   └── telegram_common.py    Shared logic
├── dispatcher.py      Command routing + LLM dispatch
├── scheduler.py       Cron jobs (APScheduler)
├── main.py            Entry point (auto Gmail auth)
├── credentials.json   OAuth client secret (from Google Cloud)
├── credentials/       Gmail tokens per user (auto-generated)
└── data/              SQLite database
```

## Production Deployment (Webhook Mode)

```bash
# Requires domain + HTTPS
# Configure in .env:
BOT_MODE=webhook
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PORT=8443
TELEGRAM_WEBHOOK_SECRET=random-secret-string

# Run
python main.py

# Health check
curl https://your-domain.com/health
```

## Future: Multi-user Expansion

The architecture is already prepared. What needs to be added:
1. `/start` command for new users
2. `/approve` command for owner
3. OAuth callback endpoint for per-user Gmail
4. Admin commands (`/users`, `/usage`, `/disable`)

What doesn't need to change: tools, dispatcher, LLM router, memory, DB schema, scheduler
