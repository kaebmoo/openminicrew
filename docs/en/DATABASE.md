# Database Reference

> 🇹🇭 [อ่านเป็นภาษาไทย](../th/DATABASE.md)

OpenMiniCrew uses **SQLite** with WAL mode. Single file, zero configuration.

**Location:** `data/openminicrew.db`

## Connection Model

- Thread-local connections via `threading.local()`
- Each thread reuses its own connection (no pool manager needed)
- WAL mode enables concurrent reads + single writer
- All tables auto-created on first startup (`CREATE TABLE IF NOT EXISTS`)

## Tables

### users

Core user table. Each Telegram user maps to one row.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| user_id | TEXT PK | | UUID |
| telegram_chat_id | TEXT UNIQUE | | Telegram chat ID |
| display_name | TEXT | | User's display name |
| phone_number | TEXT | | Phone number |
| status | TEXT | `'active'` | Account status |
| role | TEXT | `'user'` | `owner` or `user` |
| default_llm | TEXT | `'gemini'` | Preferred LLM provider |
| smart_inbox_mode | TEXT | `'confirm'` | Smart inbox behavior |
| timezone | TEXT | `'Asia/Bangkok'` | User timezone |
| gmail_authorized | INTEGER | `0` | Gmail OAuth completed? |
| is_active | INTEGER | `1` | Soft delete flag |
| created_at | TEXT | | ISO datetime |
| updated_at | TEXT | | ISO datetime |

### chat_history

Chat memory for LLM context.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| role | TEXT | `user` or `assistant` |
| content | TEXT | Message text |
| tool_used | TEXT | Tool name (if any) |
| llm_model | TEXT | Model used |
| token_used | INTEGER | Tokens consumed |
| conversation_id | TEXT | Groups messages into conversations |
| created_at | TEXT | ISO datetime |

**Index:** `idx_chat_user_time` on `(user_id, created_at DESC)`

### conversations

Conversation sessions for `/new` and `/history`.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| user_id | TEXT FK | → users |
| title | TEXT | Auto-generated title |
| is_active | INTEGER | Current conversation? |
| message_count | INTEGER | Message counter |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |

**Index:** `idx_conv_user_time` on `(user_id, updated_at DESC)`

### user_api_keys

Per-user encrypted API keys (set via `/setkey`).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| service | TEXT | Service name (e.g. `matcha`, `tavily`) |
| api_key | TEXT | Fernet-encrypted key |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |

**Unique constraint:** `(user_id, service)`

### tool_logs

Audit trail for every tool execution.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| tool_name | TEXT | Tool that was called |
| input_summary | TEXT | Input arguments |
| output_summary | TEXT | Result summary |
| llm_model | TEXT | Model used |
| token_used | INTEGER | Tokens consumed |
| status | TEXT | `success` or `error` |
| error_message | TEXT | Error detail if failed |
| created_at | TEXT | ISO datetime |

### processed_emails

Deduplication for email summaries.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| message_id | TEXT | Gmail/IMAP message ID |
| subject | TEXT | Email subject |
| sender | TEXT | Sender address |
| processed_at | TEXT | ISO datetime |

**Unique constraint:** `(user_id, message_id)`

### schedules

Per-user cron jobs.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| tool_name | TEXT | Tool to run |
| cron_expr | TEXT | Cron expression |
| args | TEXT | JSON arguments |
| is_active | INTEGER | Enabled? |
| last_run_at | TEXT | Last execution time |

### reminders

User reminders with scheduled notifications.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| text | TEXT | Reminder text |
| remind_at | TEXT | When to remind |
| status | TEXT | `pending`, `done`, `cancelled` |
| schedule_id | INTEGER | APScheduler job reference |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |

### todos

User todo items.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| title | TEXT | Todo title |
| notes | TEXT | Additional notes |
| priority | TEXT | `low`, `medium`, `high` |
| status | TEXT | `open`, `done` |
| due_at | TEXT | Due datetime |
| source_type | TEXT | Where it came from (e.g. `email`) |
| source_ref | TEXT | Reference ID |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |

### expenses

Expense tracking.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| amount | REAL | Amount |
| currency | TEXT | Default `THB` |
| category | TEXT | Category label |
| note | TEXT | Description |
| expense_date | TEXT | When the expense occurred |
| created_at | TEXT | ISO datetime |

### Supporting Tables

| Table | Purpose |
|-------|---------|
| **user_locations** | Last known GPS location per user (TTL-based) |
| **oauth_states** | Temporary OAuth state tokens for Gmail auth |
| **pending_messages** | Queued messages when user hasn't registered yet |
| **job_runs** | Cron job execution log (dedup + audit) |

## Retention & Cleanup

The scheduler runs a daily cleanup job that prunes old data:

| Table | Retention | Config key |
|-------|-----------|------------|
| chat_history | 30 days | `CHAT_HISTORY_RETENTION_DAYS` |
| tool_logs | 90 days | `TOOL_LOG_RETENTION_DAYS` |
| processed_emails | 90 days | `EMAIL_LOG_RETENTION_DAYS` |
| pending_messages | 7 days | `PENDING_MSG_RETENTION_DAYS` |
| job_runs | 30 days | `JOB_RUN_RETENTION_DAYS` |
