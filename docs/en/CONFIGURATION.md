# Configuration Reference

> 🇹🇭 [อ่านเป็นภาษาไทย](../th/CONFIGURATION.md)

All configuration is via environment variables in `.env`. Copy `.env.example` to get started.

## Required Variables

These must be set or the app will refuse to start.

| Variable | Example | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | `123:ABCxxx` | From @BotFather |
| `OWNER_TELEGRAM_CHAT_ID` | `123456789` | Your Telegram chat ID |
| `BOT_API_EXCHANGE_TOKEN` | `...` | Bank of Thailand exchange rate API |
| `BOT_API_HOLIDAY_TOKEN` | `...` | Bank of Thailand holiday API |

## Bot Mode

| Variable | Default | Options | Description |
|----------|---------|---------|-------------|
| `BOT_MODE` | `polling` | `polling`, `webhook` | How the bot receives updates |

### Webhook-only settings

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBHOOK_HOST` | | Your domain (e.g. `https://bot.example.com`) |
| `WEBHOOK_PORT` | `8443` | Port for FastAPI |
| `WEBHOOK_PATH` | `/bot/webhook` | URL path |
| `TELEGRAM_WEBHOOK_SECRET` | | Secret token for header verification |

## LLM Providers

At least one provider API key is required.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_LLM` | `claude` | Default provider for new users |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `GEMINI_API_KEY` | | Google Gemini API key |
| `MATCHA_API_KEY` | | Matcha/Typhoon API key (or set per-user via `/setkey`) |
| `MATCHA_BASE_URL` | | OpenAI-compatible base URL |

### Model Selection

Each provider has a "cheap" (fast/cheap) and "mid" (smart/expensive) tier.

| Variable | Default |
|----------|---------|
| `CLAUDE_MODEL_CHEAP` | `claude-haiku-4-5-20251001` |
| `CLAUDE_MODEL_MID` | `claude-sonnet-4-5-20250929` |
| `GEMINI_MODEL_CHEAP` | `gemini-2.5-flash` |
| `GEMINI_MODEL_MID` | `gemini-2.5-pro` |
| `MATCHA_MODEL_CHEAP` | `typhoon-v2-70b-instruct` |
| `MATCHA_MODEL_MID` | `typhoon-v2-70b-instruct` |

## External APIs

All optional. Tools that need them will show a friendly error if not configured.

| Variable | Used by |
|----------|---------|
| `GOOGLE_MAPS_API_KEY` | Traffic/route tool |
| `FOURSQUARE_API_KEY` | Places/nearby search |
| `TMD_API_KEY` | Thai weather data |
| `TAVILY_API_KEY` | Web search tool |

## Gmail

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_MAX_RESULTS` | `30` | Max emails to fetch per query |

Gmail OAuth requires `credentials.json` from Google Cloud Console. Per-user tokens are stored in `credentials/gmail_{user_id}.json`.

## Work Email (IMAP)

| Variable | Default | Description |
|----------|---------|-------------|
| `WORK_IMAP_HOST` | | IMAP server (e.g. `mail.company.co.th`) |
| `WORK_IMAP_PORT` | `993` | IMAP port |
| `WORK_IMAP_USER` | | Email address |
| `WORK_IMAP_PASSWORD` | | Password |
| `WORK_EMAIL_MAX_RESULTS` | `30` | Max emails per query |
| `WORK_EMAIL_ATTACHMENT_MAX_MB` | `5` | Max attachment size to process |

## Memory & Chat

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_CONTEXT_MESSAGES` | `10` | Messages sent as LLM context |
| `CHAT_HISTORY_RETENTION_DAYS` | `30` | Days before auto-cleanup |

## Scheduling

| Variable | Default | Description |
|----------|---------|-------------|
| `TIMEZONE` | `Asia/Bangkok` | System timezone |
| `MORNING_BRIEFING_TIME` | `07:00` | Daily briefing cron time |
| `MORNING_BRIEFING_TOOL` | `gmail_summary` | Tool to run for briefing |

## Timeouts

| Variable | Default | Description |
|----------|---------|-------------|
| `DISPATCH_TIMEOUT` | `120` | Max seconds for full dispatch cycle |
| `TOOL_EXEC_TIMEOUT` | `120` | Max seconds for single tool execution |
| `POLLING_TIMEOUT` | `30` | Long-poll timeout (seconds) |
| `POLLING_REQUEST_TIMEOUT` | `35` | HTTP request timeout for polling |

## Data Retention

| Variable | Default | Description |
|----------|---------|-------------|
| `TOOL_LOG_RETENTION_DAYS` | `90` | Tool logs cleanup |
| `EMAIL_LOG_RETENTION_DAYS` | `90` | Processed emails cleanup |
| `PENDING_MSG_RETENTION_DAYS` | `7` | Pending messages cleanup |
| `JOB_RUN_RETENTION_DAYS` | `30` | Cron job runs cleanup |

## Other

| Variable | Default | Description |
|----------|---------|-------------|
| `OWNER_DISPLAY_NAME` | `Owner` | Display name for the owner user |
| `LOCATION_TTL_MINUTES` | `60` | GPS location cache TTL (0 = never expires) |
| `ENCRYPTION_KEY` | | Fernet key for encrypting per-user API keys |
| `MISSED_JOB_WINDOW_HOURS` | `12` | Window to catch missed cron jobs |
| `HEARTBEAT_INTERVAL_MINUTES` | `30` | Scheduler heartbeat interval |
| `DB_PATH` | `data/openminicrew.db` | Override database file location |
