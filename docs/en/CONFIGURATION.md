# Configuration Reference

> 🇹🇭 [อ่านเป็นภาษาไทย](../th/CONFIGURATION.md)

All configuration is via environment variables in `.env`. Copy `.env.example` to get started.

## Required Variables

These must be set or the app will refuse to start.

| Variable | Example | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | `123:ABCxxx` | From @BotFather |
| `OWNER_TELEGRAM_CHAT_ID` | `123456789` | Your Telegram chat ID |
| `BOT_API_EXCHANGE_TOKEN` | `...` | Bank of Thailand exchange rate API |
| `BOT_API_HOLIDAY_TOKEN` | `...` | Bank of Thailand holiday API |

## Bot Mode

| Variable | Default | Options | Description |
| --- | --- | --- | --- |
| `BOT_MODE` | `polling` | `polling`, `webhook` | How the bot receives updates |
| `STARTUP_READINESS_POLICY` | `auto` | `auto`, `strict`, `warn` | Startup readiness policy. `auto` resolves to `strict` in webhook mode and `warn` in polling mode |

### Webhook-only settings

| Variable | Default | Description |
| --- | --- | --- |
| `WEBHOOK_HOST` | `(none)` | Your domain (e.g. `https://bot.example.com`) |
| `WEBHOOK_PORT` | `8443` | Port for FastAPI |
| `WEBHOOK_PATH` | `/bot/webhook` | URL path |
| `TELEGRAM_WEBHOOK_SECRET` | `(none)` | Secret token for header verification |

### Health endpoint and readiness behavior

When `BOT_MODE=webhook`, the app exposes `GET /health` for operators and uptime checks.

`/health` reports:

- overall status
- startup readiness checks, including `ENCRYPTION_KEY` readiness
- API key hygiene summary
- database and LLM health
- last scheduler run metadata

Status behavior:

- `ok`: readiness checks passed and DB health is healthy
- `degraded`: at least one readiness warning or advisory API key hygiene warning exists
- `fail`: a required readiness check failed or DB health is not healthy

Boot behavior uses the same readiness model:

- `BOT_MODE=webhook` with `STARTUP_READINESS_POLICY=auto` fails fast on required readiness failures
- `BOT_MODE=polling` with `STARTUP_READINESS_POLICY=auto` warns by default so local/dev startup is less disruptive
- `STARTUP_READINESS_POLICY=strict` forces fail-fast behavior in any mode
- `STARTUP_READINESS_POLICY=warn` keeps startup warning-only even if readiness is incomplete

## LLM Providers

At least one provider API key is required.

| Variable | Default | Description |
| --- | --- | --- |
| `DEFAULT_LLM` | `claude` | Default provider for new users |
| `ANTHROPIC_API_KEY` | `(none)` | Claude API key |
| `GEMINI_API_KEY` | `(none)` | Google Gemini API key |
| `MATCHA_API_KEY` | `(none)` | Matcha/Typhoon API key (or set per-user via `/setkey`) |
| `MATCHA_BASE_URL` | `(none)` | OpenAI-compatible base URL |

### Model Selection

Each provider has a "cheap" (fast/cheap) and "mid" (smart/expensive) tier.

| Variable | Default |
| --- | --- |
| `CLAUDE_MODEL_CHEAP` | `claude-haiku-4-5-20251001` |
| `CLAUDE_MODEL_MID` | `claude-sonnet-4-5-20250929` |
| `GEMINI_MODEL_CHEAP` | `gemini-2.5-flash` |
| `GEMINI_MODEL_MID` | `gemini-2.5-pro` |
| `MATCHA_MODEL_CHEAP` | `typhoon-v2-70b-instruct` |
| `MATCHA_MODEL_MID` | `typhoon-v2-70b-instruct` |

## External APIs

All optional. Tools that need them will show a friendly error if not configured.

| Variable | Used by |
| --- | --- |
| `GOOGLE_MAPS_API_KEY` | Traffic/route tool |
| `FOURSQUARE_API_KEY` | Places/nearby search |
| `TMD_API_KEY` | Thai weather data |
| `TAVILY_API_KEY` | Web search tool |

## Gmail

| Variable | Default | Description |
| --- | --- | --- |
| `GMAIL_MAX_RESULTS` | `30` | Max emails to fetch per query |

Gmail OAuth uses a managed `credentials.json` file at the project root for the app-level Google OAuth client configuration.

Current storage flow:

- download the plaintext OAuth client JSON from Google Cloud Console
- import it with `python main.py --import-gmail-client-secrets /path/to/downloaded.json`
- the app stores the managed `credentials.json` in encrypted-at-rest form when `ENCRYPTION_KEY` is configured
- existing plaintext `credentials.json` files are auto-migrated to encrypted storage on first Gmail OAuth use when `ENCRYPTION_KEY` is available
- per-user tokens are stored separately in `credentials/gmail_{user_id}.json` and remain encrypted-at-rest as well

Operational note:

- do not hand-edit the managed encrypted `credentials.json`; re-import a fresh plaintext download instead

### Operator Runbook: Rotate Gmail Client Secrets

Use this sequence for a production-safe rotation:

1. Download a fresh OAuth client JSON from Google Cloud Console to a temporary plaintext path on the admin machine.
2. Verify `ENCRYPTION_KEY` is configured in the target deployment before importing.
3. Run `python main.py --import-gmail-client-secrets /path/to/downloaded.json` on the target deployment.
4. Confirm the import succeeded, then run a Gmail OAuth action such as `/authgmail` or the owner auth flow to verify runtime loading still works.
5. Delete the temporary plaintext download from the admin machine after the import is confirmed.

Production notes:

- do not edit the managed encrypted `credentials.json` by hand
- if the app still has an older plaintext managed file, first Gmail OAuth use will auto-migrate it when `ENCRYPTION_KEY` is present
- per-user Gmail token files in `credentials/gmail_{user_id}.json` do not need to be rotated as part of client secret replacement unless you are separately revoking user grants

## Work Email (IMAP)

| Variable | Default | Description |
| --- | --- | --- |
| `WORK_IMAP_HOST` | `(none)` | IMAP server (e.g. `mail.company.co.th`) |
| `WORK_IMAP_PORT` | `993` | IMAP port |
| `WORK_IMAP_USER` | `(none)` | Email address |
| `WORK_IMAP_PASSWORD` | `(none)` | Password |
| `WORK_EMAIL_MAX_RESULTS` | `30` | Max emails per query |
| `WORK_EMAIL_ATTACHMENT_MAX_MB` | `5` | Max attachment size to process |

## Memory & Chat

| Variable | Default | Description |
| --- | --- | --- |
| `MAX_CONTEXT_MESSAGES` | `10` | Messages sent as LLM context |
| `CHAT_HISTORY_RETENTION_DAYS` | `30` | Days before auto-cleanup |

## Scheduling

| Variable | Default | Description |
| --- | --- | --- |
| `TIMEZONE` | `Asia/Bangkok` | System timezone |
| `MORNING_BRIEFING_TIME` | `07:00` | Daily briefing cron time |
| `MORNING_BRIEFING_TOOL` | `gmail_summary` | Tool to run for briefing |

## Timeouts

| Variable | Default | Description |
| --- | --- | --- |
| `DISPATCH_TIMEOUT` | `120` | Max seconds for full dispatch cycle |
| `TOOL_EXEC_TIMEOUT` | `120` | Max seconds for single tool execution |
| `POLLING_TIMEOUT` | `30` | Long-poll timeout (seconds) |
| `POLLING_REQUEST_TIMEOUT` | `35` | HTTP request timeout for polling |

## Data Retention

| Variable | Default | Description |
| --- | --- | --- |
| `TOOL_LOG_RETENTION_DAYS` | `90` | Tool logs cleanup |
| `EMAIL_LOG_RETENTION_DAYS` | `90` | Processed emails cleanup |
| `PENDING_MSG_RETENTION_DAYS` | `7` | Pending messages cleanup |
| `JOB_RUN_RETENTION_DAYS` | `30` | Cron job runs cleanup |

## Other

| Variable | Default | Description |
| --- | --- | --- |
| `OWNER_DISPLAY_NAME` | `Owner` | Display name for the owner user |
| `LOCATION_TTL_MINUTES` | `60` | GPS location cache TTL (0 = never expires) |
| `ENCRYPTION_KEY` | `(none)` | Fernet key for encrypting per-user API keys |
| `ENCRYPTION_KEY_PREVIOUS` | `(none)` | Previous Fernet key kept for decrypt-only compatibility during key rollover |
| `ENCRYPTION_KEY_PREVIOUS_LIST` | `(none)` | Comma-separated additional previous Fernet keys for staged migrations |
| `API_KEY_ROTATION_DAYS_DEFAULT` | `180` | Advisory rotation period for most per-user API keys |
| `WORK_IMAP_PASSWORD_ROTATION_DAYS` | `90` | Advisory rotation period for stored IMAP passwords |
| `WORK_IMAP_USER_ROTATION_DAYS` | `180` | Advisory rotation period for stored IMAP usernames |
| `WORK_IMAP_HOST_ROTATION_DAYS` | `365` | Advisory rotation period for stored IMAP hosts |
| `MISSED_JOB_WINDOW_HOURS` | `12` | Window to catch missed cron jobs |
| `HEARTBEAT_INTERVAL_MINUTES` | `30` | Scheduler heartbeat interval |
| `DB_PATH` | `data/openminicrew.db` | Override database file location |

API key rotation reporting is advisory only in the current rollout. Overdue keys are reported in `/mykeys`, `/privacy`, and `/health`, but existing keys are not blocked automatically.

For encryption key rollover:

1. Set a new `ENCRYPTION_KEY`.
2. Keep old key(s) in `ENCRYPTION_KEY_PREVIOUS` or `ENCRYPTION_KEY_PREVIOUS_LIST`.
3. Run `python main.py --rotate-encryption` to re-encrypt stored artifacts with the new primary key.
4. Remove old keys from config after validation.
