# OpenMiniCrew — Personal AI Assistant Framework

> 🇹🇭 [อ่านเป็นภาษาไทย](../../README.md)

OpenMiniCrew is a Telegram-first personal AI assistant framework for everyday automation.
It supports Claude, Gemini, and Matcha, with a plug-and-play tool system and per-user credentials.

## Features

- Telegram-first UX: direct `/commands` and free-text requests
- Multi-provider LLM routing: Claude, Gemini, Matcha
- Per-user API key management via `/setkey`, plus shared env keys where allowed
- Self-registration and onboarding via `/start`
- Per-user Gmail and Google Calendar authorization
- Media-capable tool responses such as QR images and PromptPay QR
- Photo-to-expense capture from receipts or slips
- Plug-and-play tool architecture: add one file in `tools/`
- Long polling and webhook modes
- Memory, scheduler, retries, rate limiting, health checks, and tool usage logging

## Current Tool Surface

Implemented tools are grouped broadly as:

- Email: Gmail summary, Work Email (IMAP), Smart Inbox
- Media: QR Code Generator, PromptPay QR
- Utilities: Unit Converter, Web Search
- Tasks: Todo, Reminder, Google Calendar, Schedule
- Finance: Expense Tracker, Exchange Rate
- Travel and info: Places, Traffic, News, Lotto

Use `/help` in Telegram for the live command list.

## Additional Docs

- [Configuration Reference](CONFIGURATION.md)
- [Architecture](ARCHITECTURE.md)
- [Database](DATABASE.md)
- [Privacy, Consent, and Security](PRIVACY_SECURITY.md)

## Installation

```bash
cd openminicrew
pip install -r requirements.txt
cp .env.example .env
```

## Configuration

### 1. Telegram Bot

1. Create a bot with [@BotFather](https://t.me/BotFather)
2. Put the token in `TELEGRAM_BOT_TOKEN`
3. Get the owner chat ID from [@userinfobot](https://t.me/userinfobot)
4. Put it in `OWNER_TELEGRAM_CHAT_ID`

### 2. LLM Providers

Supported providers:

- Claude → `ANTHROPIC_API_KEY`
- Gemini → `GEMINI_API_KEY`
- Matcha → `MATCHA_API_KEY`

Example `.env` values:

```bash
DEFAULT_LLM=gemini

ANTHROPIC_API_KEY=
GEMINI_API_KEY=

MATCHA_API_KEY=
MATCHA_BASE_URL=
MATCHA_MODEL_CHEAP=
MATCHA_MODEL_MID=
```

Notes:

- Users can also bring their own key with `/setkey` for supported services such as `anthropic`, `gemini`, `matcha`, `tavily`, and `tmd`
- Use `/model` to see which providers are actually available for the current user

### 3. Gmail and Google Calendar

Gmail and Calendar use the same per-user Google OAuth flow.

1. Create a Google Cloud project
2. Enable Gmail API and Google Calendar API
3. Create a Desktop App OAuth client
4. Download the OAuth client JSON from Google Cloud Console
5. Import it into the app:

```bash
python main.py --import-gmail-client-secrets /path/to/downloaded.json
```

Webhook mode:

- Set `WEBHOOK_HOST` to a public HTTPS URL
- Each user runs `/authgmail` in Telegram to authorize their own Gmail and Calendar

Polling mode:

```bash
python main.py --auth-gmail <chat_id>
python main.py --list-gmail
python main.py --revoke-gmail <chat_id>
```

Important:

- There is no cross-user fallback to the owner's Gmail token anymore
- If a user is not authorized yet, Gmail and Calendar tools will ask them to connect with `/authgmail`
- The managed `credentials.json` is now stored encrypted-at-rest when `ENCRYPTION_KEY` is configured
- If an older plaintext `credentials.json` is still present, the app will auto-migrate it on first Gmail OAuth use when `ENCRYPTION_KEY` is available
- Do not hand-edit the encrypted managed file; import a fresh plaintext download instead

### 4. Work Email / IMAP

Work Email credentials are per-user and are set through `/setkey`.

Required services:

- `work_imap_host`
- `work_imap_user`
- `work_imap_password`

Example:

```text
/setkey work_imap_host mail.company.co.th
/setkey work_imap_user yourname@company.co.th
/setkey work_imap_password yourpassword
```

Shared env settings still apply for common runtime configuration:

```bash
WORK_IMAP_PORT=993
WORK_EMAIL_MAX_RESULTS=30
WORK_EMAIL_ATTACHMENT_MAX_MB=5
```

### 5. Other APIs

Supported service names include:

- `anthropic`
- `gemini`
- `matcha`
- `google_maps`
- `tavily`
- `tmd`

Private-only per-user services include:

- `gmail`
- `calendar`
- `work_imap_host`
- `work_imap_user`
- `work_imap_password`

Example:

```text
/setkey tmd <key>
/setkey tavily <key>
/setkey matcha <key>
```

## Running the Bot

```bash
python main.py

BOT_MODE=polling python main.py
BOT_MODE=webhook python main.py
```

## First-Time Usage

### New User Flow

1. Open the bot chat
2. Send `/start`
3. Optionally continue with:
    - `/setname <name>`
    - `/setphone <phone>`
    - `/setid <13-digit-thai-id>`
    - `/consent chat on`
    - `/consent location on`
    - `/authgmail`
    - `/setkey tmd <key>`

### Common System Commands

| Command | Description |
| --- | --- |
| `/start` | Register and show onboarding |
| `/help` | Show the command list |
| `/model` | View or switch the active LLM |
| `/setname` | Update display name |
| `/setphone` | Save phone number |
| `/setid` | Save a Thai national ID |
| `/authgmail` | Connect Gmail and Calendar |
| `/disconnectgmail` | Revoke Gmail access without purging other data |
| `/consent [gmail\|location\|chat] [on\|off]` | View or change explicit consent state |
| `/privacy` | Show retention, consent, and private data handling summary |
| `/clearlocation` | Delete the last saved location |
| `/delete_my_data confirm` | Permanently purge user-linked data |
| `/setkey <service> <value>` | Save a personal API key |
| `/mykeys` | List saved keys |
| `/removekey <service>` | Remove a saved key |
| `/new` | Start a new conversation |
| `/history` | Show recent conversations |

### Privacy and Consent

The current rollout adds explicit privacy controls for sensitive features.

- Chat history can be turned on or off with `/consent chat on\|off`
- Location storage requires explicit consent through `/consent location on`
- Gmail access can be revoked with `/disconnectgmail`
- `/privacy` shows retention settings, consent state, and advisory API key hygiene information
- `/delete_my_data confirm` hard-purges user-linked records and credential artifacts

Consent and data lifecycle behavior:

- location is stored only after explicit consent and is subject to TTL cleanup
- chat history can be revoked and future history writes stop when consent is off
- Gmail revocation disconnects access without deleting unrelated data
- API key rotation reporting is advisory only; existing keys are not blocked automatically

## Usage Examples

### Email

| Command | Description |
| --- | --- |
| `/email` | Summarize Gmail for today |
| `/email 7d` | Summarize the last 7 days |
| `/email force` | Re-run a full summary |
| `/wm` | Summarize work email through IMAP |
| `/wm subject:meeting 7d` | Search work email |
| `/inbox` | Extract action items from recent email |
| `/inbox mode auto` | Auto-create todos from inbox findings |

### Tasks and Calendar

| Command | Description |
| --- | --- |
| `/todo buy groceries` | Add a todo |
| `/todo add finish slides !high due:2026-03-30 18:00` | Add a todo with priority and due date |
| `/todo list` | List todos |
| `/todo done 1` | Mark a todo as done |
| `/remind 2026-03-30 09:00 team meeting` | Create a one-time reminder |
| `/remind list` | List reminders |
| `/calendar list` | List upcoming calendar events |
| `/calendar add 2026-03-30 09:00 10:00 Team Meeting` | Create a calendar event |

### Finance and Utilities

| Command | Description |
| --- | --- |
| `/expense 120 food lunch` | Save an expense |
| `/expense list` | Show recent expenses |
| `/expense summary month` | Summarize monthly expenses |
| Send a receipt or slip photo | Auto-extract and save an expense |
| `/pay 120 0812345678` | Create a PromptPay QR from a Thai mobile number |
| `/pay 500 1234567890121` | Create a PromptPay QR from a Thai national ID |
| `/qr https://example.com` | Generate a QR code |
| `/convert 10 km to mi` | Convert units |
| `/search fuel price today` | Run a web search |
| `/fx` | Check exchange rates |

### Places, Traffic, and Info

| Command | Description |
| --- | --- |
| `/places coffee near me` | Search real places on the map |
| `/traffic Siam to Silom` | Check route and traffic |
| `/news` | Summarize recent news |
| `/lotto` | Check the latest Thai lottery result |

## Media and Photo Workflows

Some tools return media instead of plain text:

- `/qr` returns a QR image
- `/pay` returns a PromptPay QR image
- Expense capture accepts receipt or slip photos sent through Telegram

Tools remain platform-agnostic; Telegram-specific sending is handled by the interface layer.

## Multi-User Management

Two user flows are supported:

- Self-registration via `/start`
- Owner-managed access via `/adduser`, `/removeuser`, and `/listusers`

Owner commands:

| Command | Description |
| --- | --- |
| `/adduser <chat_id> [name]` | Add a user |
| `/removeuser <chat_id>` | Deactivate a user |
| `/listusers` | List all users |

## Adding New Tools

Create one file in `tools/` and the registry will auto-discover it.

```python
from tools.base import BaseTool


class MyTool(BaseTool):
    name = "my_tool"
    description = "Describe what this tool does"
    commands = ["/mytool"]

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        return "Result"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {"type": "string"}
                },
                "required": [],
            },
        }
```

## Project Structure

```text
openminicrew/
├── core/
│   ├── config.py
│   ├── llm.py
│   ├── api_keys.py
│   ├── db.py
│   ├── memory.py
│   ├── security.py
│   ├── gmail_oauth.py
│   ├── user_manager.py
│   └── providers/
│       ├── claude_provider.py
│       ├── gemini_provider.py
│       ├── matcha_provider.py
│       └── registry.py
├── tools/
│   ├── registry.py
│   ├── response.py
│   ├── gmail_summary.py
│   ├── work_email.py
│   ├── smart_inbox.py
│   ├── qrcode_gen.py
│   ├── promptpay.py
│   ├── unit_converter.py
│   ├── web_search.py
│   ├── reminder.py
│   ├── todo.py
│   ├── calendar_tool.py
│   ├── expense.py
│   ├── places.py
│   ├── traffic.py
│   ├── news_summary.py
│   ├── lotto.py
│   └── exchange_rate.py
├── interfaces/
├── dispatcher.py
├── scheduler.py
├── main.py
└── requirements.txt
```

## Webhook / Production

Webhook mode is intended for HTTPS-enabled production deployments.

```bash
BOT_MODE=webhook
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PORT=8443
TELEGRAM_WEBHOOK_SECRET=random-secret-string

python main.py
curl https://your-domain.com/health
```

`/health` is an HTTP operator endpoint, not a Telegram command.

It returns JSON with:

- overall service status
- startup readiness checks
- `ENCRYPTION_KEY` readiness impact summary
- API key hygiene summary
- DB and LLM health
- last scheduler run information

Typical status meanings:

- `ok`: required readiness checks passed
- `degraded`: warning-level readiness or advisory hygiene issues exist
- `fail`: required readiness or DB health failed

For deeper nginx and deployment details, use the dedicated docs later.

<!-- Paste this section into your README.md -->

## License

openminicrew is dual-licensed:

- **[AGPL-3.0](LICENSE)** — Free for open-source use. If you deploy this as a
  network service, you must release your complete source code under AGPL-3.0.
- **Commercial License** — For proprietary/closed-source use. Contact
  kaebmoo (at) gmail.com for terms.

See [LICENSING.md](LICENSING.md) for full details.